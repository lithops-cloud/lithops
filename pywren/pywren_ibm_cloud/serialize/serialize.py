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
import shutil
import os
import sys
from pywren_ibm_cloud.serialize import util

logger = logging.getLogger(__name__)


class PywrenSerializer:

    def __init__(self, preinstalls=None):
        self.preinstalled_modules = preinstalls

    def _get_mod_paths(self, module_manager, exclude_modules=None):
        mod_paths = module_manager.get_and_clear_paths()
        logger.debug("Modules to transmit: {}".format(None if not mod_paths else mod_paths))

        if exclude_modules:
            for module in exclude_modules:
                for mod_path in list(mod_paths):
                    if module in mod_path and mod_path in mod_paths:
                        mod_paths.remove(mod_path)

        logger.debug("Modules to transmit: {}".format(None if not mod_paths else mod_paths))

        return mod_paths

    def dump(self, func, data, ignore_module_dependencies=False, exclude_modules=None, data_all_as_one=True):
        """
        :param func: a function object
        :param data: a list contains dicts of args
        :param ignore_module_dependencies: True for serialization without any dependent modules or False otherwise
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.
        :param data_all_as_one: upload the data as a single object. Default True
        :return: serialized function, args, and dependent modules if need and can to.
        """
        assert isinstance(data, list)
        assert callable(func)

        list_of_objs = [func] + data
        strs, cps = util.make_cloudpickles_list(list_of_objs)

        modulemgr = util.init_module_manager(cps, self.preinstalled_modules, ignore_module_dependencies)
        mod_paths = self._get_mod_paths(modulemgr, exclude_modules)
        module_data = util.create_mod_data(mod_paths)
        assert isinstance(module_data, dict)

        dumped_func = strs[0]
        dumped_func_modules = pickle.dumps({'func': dumped_func, 'module_data': module_data}, -1)
        dumped_args_list = strs[1:]

        args_ranges = None
        if data_all_as_one:
            args_ranges = list()
            pos = 0
            for datum in dumped_args_list:
                l = len(datum)
                args_ranges.append((pos, pos + l - 1))
                pos += l

        return dumped_func_modules, dumped_args_list, args_ranges

    def dump_output(self, output, **kwargs):
        output_dict = kwargs
        output_dict['result'] = output

        return pickle.dumps(output_dict)


class PywrenUnserializer:

    def _save_modules(self, module_data, python_module_path):
        """
        Save modules, before we unserialize actual function
        """
        logger.info("Writing Function dependencies to local disk")
        shutil.rmtree(python_module_path, True)  # delete old modules
        os.mkdir(python_module_path)
        sys.path.append(python_module_path)

        for m_filename, m_data in module_data.items():
            m_path = os.path.dirname(m_filename)

            if len(m_path) > 0 and m_path[0] == "/":
                m_path = m_path[1:]
            to_make = os.path.join(python_module_path, m_path)
            try:
                os.makedirs(to_make)
            except OSError as e:
                if e.errno == 17:
                    pass
                else:
                    raise e
            full_filename = os.path.join(to_make, os.path.basename(m_filename))

            with open(full_filename, 'wb') as fid:
                fid.write(util.b64str_to_bytes(m_data))

        # logger.info("Finished writing {} module files".format(len(module_data)))
        # logger.debug(subprocess.check_output("find {}".format(python_module_path), shell=True))
        # logger.debug(subprocess.check_output("find {}".format(os.getcwd()), shell=True))
        logger.info("Finished writing Function dependencies")

    def load(self, dumped_func_modules, dumped_args, python_module_path):
        """
        :param dumped_func_modules: serialized function object
        :param dumped_args: ranged serialized args dict
        :return: unserialized function, args and dependent modules which serialized before
        """
        func_modules = pickle.loads(dumped_func_modules)
        assert isinstance(func_modules, dict)
        modules = func_modules['module_data']
        dumped_func = func_modules['func']

        self._save_modules(modules, python_module_path)

        logger.info("Unpickle Function")
        func = pickle.loads(dumped_func)
        logger.info("Finished Function unpickle")

        logger.info("Unpickle Function data")
        data = pickle.loads(dumped_args)
        logger.info("Finished unpickle Function data")
        assert isinstance(data, dict)

        return func, data

    def load_output(self, dumped_output):
        info = pickle.loads(dumped_output)
        assert isinstance(info, dict)
        result = info.pop('result')
        return result, info
