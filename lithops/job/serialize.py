#
# Copyright 2018 PyWren Team
# (C) Copyright IBM Corp. 2019
# (C) Copyright Cloudlab URV 2020
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import posixpath
import glob
import importlib
import logging
import inspect
import cloudpickle
from pathlib import Path
from dis import Bytecode
from functools import partial, reduce
from importlib import import_module
from types import CodeType, FunctionType, ModuleType
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from lithops.libs import imp
from lithops.libs import inspect as linspect
from lithops.utils import bytes_to_b64str, b64str_to_bytes
from lithops.libs.multyvac.module_dependency import ModuleDependencyAnalyzer

logger = logging.getLogger(__name__)

_BUILTIN_MODULES = {'__builtin__', 'builtins'}


def _is_user_function(obj: Any) -> bool:
    return inspect.isfunction(obj) or (
        inspect.ismethod(obj) and inspect.isfunction(obj.__func__)
    )


def _joined_or_none(names: Set[str]) -> Optional[str]:
    return ", ".join(names) if names else None


def write_module_data(dest_dir: str, module_data: Optional[Dict[str, str]]) -> None:
    """
    Writes the encoded module payloads into dest_dir, recreating the package
    directories they belong to
    """
    if not module_data:
        return
    for m_filename, m_data in module_data.items():
        # The keys are posix paths built on the client, which may be a
        # different platform than the one unpacking them
        posix_name = m_filename.replace('\\', '/').lstrip('/')
        parent = posixpath.dirname(posix_name)
        dest_subdir = (
            os.path.join(dest_dir, *parent.split('/')) if parent else dest_dir
        )
        os.makedirs(dest_subdir, exist_ok=True)
        full_filename = os.path.join(
            dest_subdir, posixpath.basename(posix_name)
        )
        with open(full_filename, 'wb') as fid:
            fid.write(b64str_to_bytes(m_data))


class SerializeIndependent:
    """
    Serializes the function and the data of a job, and finds the modules they
    depend on and the runtime does not already provide
    """

    def __init__(self, preinstalls: List):
        # Lithops is always in the runtime, even when it is not preinstalled
        self.preinstalled_modules = list(preinstalls) + [['lithops', True]]
        self._modulemgr = None

    def dumps(self, list_of_objs: List) -> List[bytes]:
        """Serializes every object on its own, so they can be split apart"""
        return [cloudpickle.dumps(obj) for obj in list_of_objs]

    def _preinstalled_names(self) -> Set[str]:
        return {name for name, _ in self.preinstalled_modules}

    def _referenced_module_paths(
        self,
        list_of_objs: List,
        exclude_modules: Iterable[str]
    ) -> Set[str]:
        """
        Finds the paths of the modules the objects reference, leaving out the
        ones the runtime already has and the ones explicitly excluded
        """
        self._modulemgr = ModuleDependencyAnalyzer()
        self._modulemgr.ignore(self._preinstalled_names())
        self._modulemgr.ignore(exclude_modules)

        ref_modules = set()
        for obj in list_of_objs:
            ref_modules.update(self._module_inspect(obj))

        logger.debug(f"Referenced Modules: {_joined_or_none(ref_modules)}")

        mod_paths = set()
        for module_name in ref_modules:
            if module_name in ['__main__', None]:
                continue
            try:
                mod_spec = importlib.util.find_spec(module_name)
            except Exception:
                mod_spec = None

            origin = mod_spec.origin if mod_spec else module_name
            # Native extensions cannot be analysed any further, so they are
            # shipped as they are instead of going through the analyzer
            if origin and origin.endswith('.so'):
                excluded = (
                    origin in exclude_modules
                    or os.path.basename(origin) in exclude_modules
                )
                if not excluded:
                    mod_paths.add(origin)
            else:
                self._modulemgr.add(module_name)

        return mod_paths | self._modulemgr.get_and_clear_paths()

    def _explicit_module_paths(self, include_modules: Iterable[str]) -> Set[str]:
        """
        Resolves the paths of the modules the user asked for, given either as
        a file path or as an importable module name
        """
        preinstalled_names = self._preinstalled_names()
        mod_paths = set()

        logger.debug(f"Include Modules: {', '.join(include_modules)}")

        for module_name in include_modules:
            if module_name.endswith(('.so', '.py')):
                pathname = os.path.abspath(module_name)
                if os.path.isfile(pathname):
                    logger.debug(f"Module '{module_name}' found in {pathname}")
                    mod_paths.add(pathname)
                else:
                    logger.debug(
                        f"Could not find module '{module_name}', skipping"
                    )
                continue

            module_root = module_name.split('.')[0]
            if module_root in preinstalled_names:
                logger.debug(
                    f"Module '{module_name}' is already installed "
                    "in the runtime, skipping"
                )
                continue

            try:
                _, pathname, _ = imp.find_module(module_root)
                logger.debug(f"Module '{module_name}' found in {pathname}")
                mod_paths.add(pathname)
            except ImportError:
                logger.debug(
                    f"Could not find module '{module_name}', skipping"
                )

        return mod_paths

    def module_paths(
        self,
        list_of_objs: List,
        include_modules: Optional[Iterable[str]],
        exclude_modules: Iterable[str]
    ) -> Set[str]:
        """
        Collects the paths of the modules that have to travel with the job:
        either the ones explicitly included, or the ones its code references
        """
        if include_modules is None:
            logger.debug('Module manager disabled. Modules to transmit: None')
            return set()

        if include_modules:
            mod_paths = self._explicit_module_paths(include_modules)
        else:
            mod_paths = self._referenced_module_paths(
                list_of_objs, exclude_modules
            )

        logger.debug(f"Modules to transmit: {_joined_or_none(mod_paths)}")

        return mod_paths

    def __call__(
        self,
        list_of_objs: List,
        include_modules: Optional[Iterable[str]],
        exclude_modules: Iterable[str]
    ) -> Tuple[List[bytes], Set[str]]:
        """
        Serializes the objects independently and returns them together with
        the paths of the modules they depend on
        """
        return (
            self.dumps(list_of_objs),
            self.module_paths(list_of_objs, include_modules, exclude_modules),
        )

    def _entry_points(self, obj: Any) -> Tuple[List, Set[str]]:
        """
        Returns the user functions to inspect for the given job function, plus
        the modules that can only be read off the object itself
        """
        if _is_user_function(obj):
            return [obj], set()

        if type(obj).__name__ == 'cython_function_or_method':
            return [], {
                value['__file__']
                for name, value in linspect.getmembers_static(obj)
                if name == '__globals__'
            }

        if isinstance(obj, dict):
            worklist = []
            for param in obj.values():
                if _is_user_function(param):
                    worklist.append(param)
                    continue
                if getattr(type(param), '__module__', None) in _BUILTIN_MODULES:
                    continue
                worklist.extend(
                    value for _, value in linspect.getmembers_static(param)
                    if _is_user_function(value)
                )
            return worklist, set()

        if isinstance(obj, partial):
            return [obj.func], set()

        worklist = []
        found_methods = []
        for name, value in linspect.getmembers_static(obj):
            if _is_user_function(value):
                found_methods.append(name)
                worklist.append(value)
        if "__call__" not in found_methods:
            raise ValueError(
                "The class you passed as the function to "
                'run must contain the "__call__" method'
            )
        return worklist, set()

    def _module_inspect(self, obj: Any) -> Set[str]:
        """
        Inspects an object for the modules it depends on, following every
        function and code object it references in turn
        """
        worklist, mods = self._entry_points(obj)
        seen = set()

        # Both worklists are appended to while being iterated on purpose:
        # that is how the references are followed to the end
        for fn in worklist:
            mods.add(fn.__module__)
            codeworklist = [fn]

            cvs = inspect.getclosurevars(fn)
            closure_vars = (
                list(cvs.nonlocals.values()) + list(cvs.globals.values())
            )

            for value in closure_vars:
                if inspect.ismodule(value):
                    mods.add(value.__name__)
                elif inspect.isfunction(value) and id(value) not in seen:
                    seen.add(id(value))
                    mods.add(value.__module__)
                    worklist.append(value)
                elif hasattr(value, "__module__"):
                    mods.add(value.__module__)

            for block in codeworklist:
                for kind, value in (
                    self._inner_module_inspect(inst) for inst in Bytecode(block)
                ):
                    if kind is None:
                        continue
                    if kind == "modules":
                        mods.update(
                            mod.__name__ for mod in value
                            if hasattr(mod, "__name__")
                        )
                    elif kind == "code" and id(value) not in seen:
                        seen.add(id(value))
                        if hasattr(value, "__module__"):
                            mods.add(value.__module__)

                    if inspect.isfunction(value):
                        worklist.append(value)
                    elif inspect.iscode(value):
                        codeworklist.append(value)

        # Dynamically built functions and code objects can have a
        # __module__ of None, which names no module to ship
        return {mod_name.split(".")[0] for mod_name in mods if mod_name}

    def _inner_module_inspect(self, inst: Any) -> Tuple[Optional[str], Any]:
        """
        Reads the module or the code object that a single bytecode
        instruction refers to
        """
        if inst.opname == "IMPORT_NAME":
            try:
                path = inst.argval.split(".")
                path[0] = [import_module(path[0])]
                result = reduce(lambda x, a: x + [getattr(x[-1], a)], path)
                return ("modules", result)
            except Exception:
                return (None, None)
        if inst.opname == "LOAD_GLOBAL":
            value = globals().get(inst.argval)
            if isinstance(value, (CodeType, FunctionType)):
                return ("code", value)
            if isinstance(value, ModuleType):
                return ("modules", [value])
            return (None, None)
        if "LOAD_" in inst.opname and isinstance(
            inst.argval, (CodeType, FunctionType)
        ):
            return ("code", inst.argval)
        return (None, None)


def create_module_data(mod_paths: Iterable[str]) -> Dict[str, str]:
    """
    Reads the modules at the given paths and encodes them, keyed by the path
    they have to be written to relative to their package root
    """
    module_data = {}

    for mod_path in mod_paths:
        pkg_root = os.path.abspath(os.path.dirname(mod_path))
        if os.path.isdir(mod_path):
            files = glob.glob(
                os.path.join(mod_path, "**/*.py"), recursive=True
            )
        else:
            files = [mod_path]

        for filename in files:
            filename = os.path.abspath(filename)
            with open(filename, 'rb') as fid:
                mod_str = fid.read()
            dest_filename = Path(filename[len(pkg_root) + 1:]).as_posix()
            module_data[dest_filename] = bytes_to_b64str(mod_str)

    return module_data
