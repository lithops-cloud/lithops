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
import sys
import json
import time
import logging
import inspect
from pywren_ibm_cloud import wrenlogging
from pywren_ibm_cloud.storage import storage
from pywren_ibm_cloud.serialize import serialize
from pywren_ibm_cloud.libs.tblib import pickling_support
from pywren_ibm_cloud.wrenutil import get_current_memory_usage
from pywren_ibm_cloud.storage.backends.cos import COSBackend
from pywren_ibm_cloud.storage.backends.swift import SwiftBackend


pickling_support.install()
level = logging.DEBUG
logger = logging.getLogger('jobrunner')
logger.setLevel(level)
wrenlogging.ow_config(level)


def load_config(config_location):
    with open(config_location, 'r') as configf:
        jobrunner_config = json.load(configf)
    return jobrunner_config
    
    
class stats:
    
    def __init__(self, stats_filename):
        self.stats_filename = stats_filename
        self.stats_fid = open(stats_filename, 'w')
        
    def write(self, key, value):
        self.stats_fid.write("{} {:f}\n".format(key, value))
        self.stats_fid.flush()
    
    def __del__(self):
        self.stats_fid.close()


class jobrunner:

    def __init__(self):
        start_time =  time.time()
        self.config = load_config(sys.argv[1])
        self.stats = stats(self.config['stats_filename'])
        self.stats.write('jobrunner_start', start_time) 
        self.storage_config = json.loads(os.environ.get('STORAGE_CONFIG', ''))

        if 'SHOW_MEMORY_USAGE' in os.environ:
            self.show_memory = eval(os.environ['SHOW_MEMORY_USAGE'])
        else:
            self.show_memory = False
            
        self.func_key = self.config['func_key']
        self.data_key = self.config['data_key']
        self.data_byte_range = self.config['data_byte_range']
        self.output_key = self.config['output_key']

        self.unserializer = serialize.PywrenUnserializer()
        self.serializer = serialize.PywrenSerializer()

    def _get_function_and_modules(self):
        """
        Gets function and modules from storage
        """
        logger.info("Getting function and modules from storage")
        func_download_time_t1 = time.time()
        func_all_obj = self.internal_storage.get_func(self.func_key)
        func_download_time_t2 = time.time()
        self.stats.write('func_download_time', func_download_time_t2-func_download_time_t1)
        logger.info("Finished getting Function and modules from storage")
        
        return func_all_obj
    
    def _get_data(self):
        extra_get_args = {}
        if self.data_byte_range is not None:
            range_str = 'bytes={}-{}'.format(*self.data_byte_range)
            extra_get_args['Range'] = range_str

        logger.info("Getting function data from storage")
        data_download_time_t1 = time.time()
        data_obj = self.internal_storage.get_data(self.data_key, extra_get_args=extra_get_args)
        logger.info("Finished getting Function data from storage")
        data_download_time_t2 = time.time()
        self.stats.write('data_download_time',
                   data_download_time_t2-data_download_time_t1)
        
        return data_obj
    
    def _create_storage_clients(self, function, data):
        # Verify storage parameters - Create clients
        func_sig = inspect.signature(function)
    
        if 'storage' in func_sig.parameters:
            # 'storage' generic parameter used in map_reduce method
            if 'ibm_cos' in self.storage_config:
                mr_storage_client = COSBackend(self.storage_config['ibm_cos'])
            elif 'swift' in self.storage_config:
                mr_storage_client = SwiftBackend(self.storage_config['swift'])
    
            data['storage'] = mr_storage_client
    
        if 'ibm_cos' in func_sig.parameters:
            ibm_boto3_client = COSBackend(self.storage_config['ibm_cos']).get_client()
            data['ibm_cos'] = ibm_boto3_client
    
        if 'swift' in func_sig.parameters:
            swift_client = SwiftBackend(self.storage_config['swift'])
            data['swift'] = swift_client
    
        if 'internal_storage' in func_sig.parameters:
            data['internal_storage'] = self.internal_storage
        
        return data

    def run_function(self):
        """
        Runs the function
        """
        # initial output file in case job fails
        dumped_output = self.serializer.dump_output(None, success=False)

        try:
            self.internal_storage = storage.InternalStorage(self.storage_config)

            dumped_func_modules = self._get_function_and_modules()
            dumped_args = self._get_data()
            function, data = self.unserializer.load(dumped_func_modules, dumped_args, self.config['python_module_path'])
            data = self._create_storage_clients(function, data)

            if self.show_memory:
                logger.debug("Memory usage before call the function: {}".format(get_current_memory_usage()))

            logger.info("Function: Going to execute '{}()'".format(str(function.__name__)))
            print('------------------- FUNCTION LOG -------------------')
            func_exec_time_t1 = time.time()
            result = function(**data)
            func_exec_time_t2 = time.time()
            print('----------------------------------------------------')
            logger.info("Function: Success execution")

            if self.show_memory:
                logger.debug("Memory usage after call the function: {}".format(get_current_memory_usage()))

            self.stats.write('function_exec_time', func_exec_time_t2-func_exec_time_t1)
            dumped_output = self.serializer.dump_output(result, success=True)

            if self.show_memory:
                logger.debug("Memory usage after output serialization: {}".format(get_current_memory_usage()))
        
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            #traceback.print_tb(exc_traceback)
        
            # Shockingly often, modules like subprocess don't properly
            # call the base Exception.__init__, which results in them
            # being unserializable. As a result, we actually wrap this in a try/catch block
            # and more-carefully handle the exceptions if any part of this save / test-reload
            # fails
            logger.error("There was an exception: {}".format(str(e)))
            print('----------------------------------------------------')
            try:
                dumped_output = self.serializer.dump_output(e,
                                                            exc_type=exc_type,
                                                            exc_value=exc_value,
                                                            exc_traceback=exc_traceback,
                                                            sys_path=sys.path,
                                                            success=False)
        
                # this is just to make sure they can be unserialized
                self.unserializer.load_output(dumped_output)
        
            except Exception as serialization_exception:
                dumped_output = self.serializer.dump_output(str(e),
                                                            exc_type=str(exc_type),
                                                            exc_value=str(exc_value),
                                                            exc_traceback=exc_traceback,
                                                            exc_traceback_str=str(exc_traceback),
                                                            sys_path=sys.path,
                                                            serialization_fail=True,
                                                            serialization_exception=serialization_exception,
                                                            success=False)
        finally:
            store_result = True
            if 'STORE_RESULT' in os.environ:
                store_result = eval(os.environ['STORE_RESULT'])
        
            if store_result:
                output_upload_timestamp_t1 = time.time()
                self.internal_storage.put_data(self.output_key, dumped_output)
                output_upload_timestamp_t2 = time.time()
                self.stats.write("output_upload_time",
                           output_upload_timestamp_t2 - output_upload_timestamp_t1)

if __name__ == '__main__':
    logger.info("Jobrunner started")
    jr = jobrunner()
    jr.run_function()
    logger.info("Jobrunner finished")
