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
import glob
import importlib
import logging
import inspect
import cloudpickle
from pathlib import Path
from dis import Bytecode
from functools import reduce
from importlib import import_module
from types import CodeType, FunctionType, ModuleType

from lithops.libs import imp
from lithops.libs import inspect as linspect
from lithops.utils import bytes_to_b64str
from lithops.libs.multyvac.module_dependency import ModuleDependencyAnalyzer

logger = logging.getLogger(__name__)


class SerializeIndependent:

    def __init__(self, preinstalls):
        self.preinstalled_modules = preinstalls
        self.preinstalled_modules.append(['lithops', True])
        self._modulemgr = None

    def __call__(self, list_of_objs, include_modules, exclude_modules):
        """
        Serialize f, args, kwargs independently
        """
        preinstalled_modules = [name for name, _ in self.preinstalled_modules]

        strs = []
        mod_paths = set()

        for obj in list_of_objs:
            strs.append(cloudpickle.dumps(obj))

        if include_modules is None:
            # If include_modules is explicitly set to None, no module is included
            logger.debug('Module manager disabled. Modules to transmit: None')
            return (strs, mod_paths)

        if len(include_modules) == 0:
            # If include_modules is not provided (empty list by default),
            # inspect the objects looking for referenced modules
            self._modulemgr = ModuleDependencyAnalyzer()
            self._modulemgr.ignore(preinstalled_modules)
            self._modulemgr.ignore(exclude_modules)

            ref_modules = set()

            for obj in list_of_objs:
                ref_modules.update(self._module_inspect(obj))

            logger.debug("Referenced Modules: {}".format(None if not
                         ref_modules else ", ".join(ref_modules)))

            for module_name in ref_modules:
                if module_name in ['__main__', None]:
                    continue
                try:
                    mod_spec = importlib.util.find_spec(module_name)
                except Exception:
                    mod_spec = None

                origin = mod_spec.origin if mod_spec else module_name
                if origin and origin.endswith('.so'):
                    if origin not in exclude_modules and \
                       os.path.basename(origin) not in exclude_modules:
                        mod_paths.add(origin)
                else:
                    self._modulemgr.add(module_name)

            tent_mod_paths = self._modulemgr.get_and_clear_paths()
            mod_paths = mod_paths.union(tent_mod_paths)

        else:
            # If include_modules is provided, include only the provided list
            logger.debug("Include Modules: {}".format(", ".join(include_modules)))
            for module_name in include_modules:
                if module_name.endswith('.so') or module_name.endswith('.py'):
                    pathname = os.path.abspath(module_name)
                    if os.path.isfile(pathname):
                        logger.debug(f"Module '{module_name}' found in {pathname}")
                        mod_paths.add(pathname)
                    else:
                        logger.debug(f"Could not find module '{module_name}', skipping")
                    continue
                module_root = module_name.split('.')[0]
                if module_root in preinstalled_modules:
                    logger.debug(f"Module '{module_name}' is already installed in the runtime, skipping")
                    continue
                try:
                    fp, pathname, description = imp.find_module(module_root)
                    logger.debug(f"Module '{module_name}' found in {pathname}")
                    mod_paths.add(pathname)
                except ImportError:
                    logger.debug(f"Could not find module '{module_name}', skipping")

        logger.debug("Modules to transmit: {}".format(None if not mod_paths else ", ".join(mod_paths)))

        return (strs, mod_paths)

    def _module_inspect(self, obj):
        """
        inspect objects for module dependencies
        """
        worklist = []
        seen = set()
        mods = set()

        if inspect.isfunction(obj) or (inspect.ismethod(obj) and inspect.isfunction(obj.__func__)):
            # The obj is the user's function
            worklist.append(obj)

        elif type(obj).__name__ == 'cython_function_or_method':
            for k, v in linspect.getmembers_static(obj):
                if k == '__globals__':
                    mods.add(v['__file__'])

        elif type(obj) is dict:
            # the obj is the user's iterdata
            for param in obj.values():
                if type(param).__module__ == "__builtin__":
                    continue
                elif inspect.isfunction(param):
                    # it is a user defined function
                    worklist.append(param)
                else:
                    # it is a user defined class
                    for k, v in linspect.getmembers_static(param):
                        if inspect.isfunction(v) or (inspect.ismethod(v) and inspect.isfunction(v.__func__)):
                            worklist.append(v)
        else:
            # The obj is the user's function but in form of a class
            found_methods = []
            for k, v in linspect.getmembers_static(obj):
                if inspect.isfunction(v) or (inspect.ismethod(v) and inspect.isfunction(v.__func__)):
                    found_methods.append(k)
                    worklist.append(v)
            if "__call__" not in found_methods:
                raise Exception('The class you passed as the function to '
                                'run must contain the "__call__" method')

        # The worklist is only used for analyzing functions
        for fn in worklist:
            mods.add(fn.__module__)
            codeworklist = [fn]

            cvs = inspect.getclosurevars(fn)
            modules = list(cvs.nonlocals.items())
            modules.extend(list(cvs.globals.items()))

            for k, v in modules:
                if inspect.ismodule(v):
                    mods.add(v.__name__)
                elif inspect.isfunction(v) and id(v) not in seen:
                    seen.add(id(v))
                    mods.add(v.__module__)
                    worklist.append(v)
                elif hasattr(v, "__module__"):
                    mods.add(v.__module__)

            for block in codeworklist:
                for (k, v) in [self._inner_module_inspect(inst)
                               for inst in Bytecode(block)]:
                    if k is None:
                        continue
                    if k == "modules":
                        newmods = [mod.__name__ for mod in v if hasattr(mod, "__name__")]
                        mods.update(set(newmods))
                    elif k == "code" and id(v) not in seen:
                        seen.add(id(v))
                        if hasattr(v, "__module__"):
                            mods.add(v.__module__)

                    if inspect.isfunction(v):
                        worklist.append(v)
                    elif inspect.iscode(v):
                        codeworklist.append(v)

        return set([mod_name.split('.')[0] for mod_name in mods])

    def _inner_module_inspect(self, inst):
        """
        get interesting modules refernced within an object
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
            if inst.argval in globals() and type(globals()[inst.argval]) in [CodeType, FunctionType]:
                return ("code", globals()[inst.argval])
            if inst.argval in globals() and type(globals()[inst.argval]) == ModuleType:
                return ("modules", [globals()[inst.argval]])
            else:
                return (None, None)
        if "LOAD_" in inst.opname and type(inst.argval) in [CodeType, FunctionType]:
            return ("code", inst.argval)
        return (None, None)


def create_module_data(mod_paths):

    module_data = {}
    # load mod paths
    for m in mod_paths:
        if os.path.isdir(m):
            files = glob.glob(os.path.join(m, "**/*.py"), recursive=True)
            pkg_root = os.path.abspath(os.path.dirname(m))
        else:
            pkg_root = os.path.abspath(os.path.dirname(m))
            files = [m]
        for f in files:
            f = os.path.abspath(f)
            with open(f, 'rb') as file:
                mod_str = file.read()
            dest_filename = Path(f[len(pkg_root) + 1:]).as_posix()
            module_data[dest_filename] = bytes_to_b64str(mod_str)

    return module_data
