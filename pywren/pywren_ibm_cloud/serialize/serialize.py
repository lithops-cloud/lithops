#
# Copyright 2018 PyWren Team
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the
#    distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
# OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
# AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY
# WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

import logging
import pickle
from io import BytesIO as StringIO
from pywren_ibm_cloud.libs.cloudpickle import CloudPickler
from pywren_ibm_cloud.serialize.module_dependency import ModuleDependencyAnalyzer
from pywren_ibm_cloud.serialize.util import create_mod_data

logger = logging.getLogger(__name__)


class SerializeIndependent:

    def __init__(self, preinstalls):
        self.preinstalled_modules = preinstalls
        self.preinstalled_modules.append(['pywren_ibm_cloud', True])

        self.dumped_func_modules = None
        self.func_modules_size_bytes = 0

        self.dumped_args = None
        self.data_size_bytes = 0

    def create_module_manager(self, list_of_cloudpickles, ignore_module_manager=False, ):
        modulemgr = ModuleDependencyAnalyzer()
        preinstalled_modules = [name for name, _ in self.preinstalled_modules]
        modulemgr.ignore(preinstalled_modules)

        if not ignore_module_manager:
            # Add modules
            for cp in list_of_cloudpickles:
                for module in cp.modules:
                    modulemgr.add(module.__name__)

        return modulemgr

    def make_cloudpickles_list(self, list_of_objs):
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

        return strs, cps

    def make_mod_data(self, module_manager, exclude_modules=None):
        mod_paths = module_manager.get_and_clear_paths()
        logger.debug("Modules to transmit: {}".format(None if not mod_paths else mod_paths))

        if exclude_modules:
            for module in exclude_modules:
                for mod_path in list(mod_paths):
                    if module in mod_path and mod_path in mod_paths:
                        mod_paths.remove(mod_path)

        logger.debug("Modules to transmit: {}".format(None if not mod_paths else mod_paths))
        return create_mod_data(mod_paths)


    def __call__(self, list_of_objs, **kwargs):
        """
        Serialize f, args, kwargs independently
        """

        strs, cps = self.make_cloudpickles_list(list_of_objs)

        if '_ignore_module_dependencies' in kwargs:
            ignore_modulemgr = kwargs['_ignore_module_dependencies']
            del kwargs['_ignore_module_dependencies']
        else:
            ignore_modulemgr = False
        modulemgr = self.create_module_manager(cps, ignore_modulemgr)

        if 'exclude_modules' in kwargs:
            exclude_modules = kwargs['exclude_modules']
            del kwargs['exclude_modules']
        else:
            exclude_modules = None
        module_data = self.make_mod_data(modulemgr, exclude_modules)

        dumped_func = strs[0]
        self.dumped_func_modules = pickle.dumps({'func': dumped_func, 'module_data': module_data}, -1)
        self.func_modules_size_bytes = len(self.dumped_func_modules)

        dumped_data_list = strs[1:]
        self.dumped_args = dumped_data_list
        self.data_size_bytes = sum(len(x) for x in dumped_data_list)

        if 'data_all_as_one' in kwargs:
            if kwargs['data_all_as_one']:
                self.args_ranges = list()
                pos = 0
                for datum in dumped_data_list:
                    l = len(datum)
                    self.args_ranges.append((pos, pos+l-1))
                    pos += l
                self.dumped_args = b"".join(dumped_data_list)

        return self.dumped_func_modules, self.dumped_args
