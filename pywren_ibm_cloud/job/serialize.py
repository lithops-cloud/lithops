#
# Copyright 2018 PyWren Team
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
import logging
from pathlib import Path
from io import BytesIO as StringIO
from pywren_ibm_cloud.utils import bytes_to_b64str
from pywren_ibm_cloud.libs.cloudpipe.cloudpickle import CloudPickler
from pywren_ibm_cloud.libs.cloudpipe.module_dependency import ModuleDependencyAnalyzer

try:
    import glob2
except Exception:
    from pywren_ibm_cloud.libs import glob2


logger = logging.getLogger(__name__)


class SerializeIndependent:

    def __init__(self, preinstalls):
        self.preinstalled_modules = preinstalls
        self.preinstalled_modules.append(['pywren_ibm_cloud', True])
        self._modulemgr = None

    def __call__(self, list_of_objs, **kwargs):
        """
        Serialize f, args, kwargs independently
        """
        self._modulemgr = ModuleDependencyAnalyzer()
        preinstalled_modules = [name for name, _ in self.preinstalled_modules]
        self._modulemgr.ignore(preinstalled_modules)

        cps = []
        strs = []
        for obj in list_of_objs:
            file = StringIO()
            try:
                cp = CloudPickler(file)
                cp.dump(obj)
                cps.append(cp)
                strs.append(file.getvalue())
            finally:
                file.close()

        if '_ignore_module_dependencies' in kwargs:
            ignore_modulemgr = kwargs['_ignore_module_dependencies']
            del kwargs['_ignore_module_dependencies']
        else:
            ignore_modulemgr = False

        if not ignore_modulemgr:
            # Add modules
            for cp in cps:
                for module in cp.modules:
                    self._modulemgr.add(module.__name__)

        mod_paths = self._modulemgr.get_and_clear_paths()
        logger.debug("Modules to transmit: {}".format(None if not mod_paths else mod_paths))

        return (strs, mod_paths)


def create_module_data(mod_paths):

    module_data = {}
    # load mod paths
    for m in mod_paths:
        if os.path.isdir(m):
            files = glob2.glob(os.path.join(m, "**/*.py"))
            pkg_root = os.path.abspath(os.path.dirname(m))
        else:
            pkg_root = os.path.abspath(os.path.dirname(m))
            files = [m]
        for f in files:
            f = os.path.abspath(f)
            with open(f, 'rb') as file:
                mod_str = file.read()
            dest_filename = Path(f[len(pkg_root)+1:]).as_posix()
            module_data[dest_filename] = bytes_to_b64str(mod_str)

    return module_data
