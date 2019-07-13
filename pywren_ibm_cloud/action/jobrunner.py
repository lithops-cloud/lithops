#
# (C) Copyright IBM Corp. 2019
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
import shutil
import pickle
import logging
import inspect
import numpy as np
from multiprocessing import Process
from distutils.util import strtobool
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.future import ResponseFuture
from pywren_ibm_cloud.libs.tblib import pickling_support
from pywren_ibm_cloud.utils import sizeof_fmt, b64str_to_bytes
from pywren_ibm_cloud.wrenconfig import extract_storage_config
from pywren_ibm_cloud.utils import get_current_memory_usage
from pywren_ibm_cloud.storage.backends.ibm_cos import IbmCosStorageBackend
from pywren_ibm_cloud.storage.backends.swift import SwiftStorageBackend
from pywren_ibm_cloud.logging_config import ibm_cf_logging_config

pickling_support.install()
logger = logging.getLogger('jobrunner')


class stats:

    def __init__(self, stats_filename):
        self.stats_filename = stats_filename
        self.stats_fid = open(stats_filename, 'w')

    def write(self, key, value):
        self.stats_fid.write("{} {}\n".format(key, value))
        self.stats_fid.flush()

    def __del__(self):
        self.stats_fid.close()


class jobrunner(Process):

    def __init__(self, jr_config, result_queue):
        super().__init__()
        start_time = time.time()
        self.config = jr_config
        log_level = self.config['log_level']
        self.result_queue = result_queue
        ibm_cf_logging_config(log_level)
        self.stats = stats(self.config['stats_filename'])
        self.stats.write('jobrunner_start', start_time)
        pw_config = json.loads(os.environ.get('PYWREN_CONFIG'))
        self.storage_config = extract_storage_config(pw_config)

        if 'SHOW_MEMORY_USAGE' in os.environ:
            self.show_memory = eval(os.environ['SHOW_MEMORY_USAGE'])
        else:
            self.show_memory = False

        self.func_key = self.config['func_key']
        self.data_key = self.config['data_key']
        self.data_byte_range = self.config['data_byte_range']
        self.output_key = self.config['output_key']

    def _get_function_and_modules(self):
        """
        Gets and unpickles function and modules from storage
        """
        logger.debug("Getting function and modules")
        func_download_time_t1 = time.time()
        func_obj = self.internal_storage.get_func(self.func_key)
        loaded_func_all = pickle.loads(func_obj)
        func_download_time_t2 = time.time()
        self.stats.write('func_download_time', round(func_download_time_t2-func_download_time_t1, 8))
        logger.debug("Finished getting Function and modules")

        return loaded_func_all

    def _save_modules(self, module_data):
        """
        Save modules, before we unpickle actual function
        """
        logger.debug("Writing Function dependencies to local disk")
        PYTHON_MODULE_PATH = self.config['python_module_path']
        shutil.rmtree(PYTHON_MODULE_PATH, True)  # delete old modules
        os.mkdir(PYTHON_MODULE_PATH)
        sys.path.append(PYTHON_MODULE_PATH)

        for m_filename, m_data in module_data.items():
            m_path = os.path.dirname(m_filename)

            if len(m_path) > 0 and m_path[0] == "/":
                m_path = m_path[1:]
            to_make = os.path.join(PYTHON_MODULE_PATH, m_path)
            try:
                os.makedirs(to_make)
            except OSError as e:
                if e.errno == 17:
                    pass
                else:
                    raise e
            full_filename = os.path.join(to_make, os.path.basename(m_filename))

            with open(full_filename, 'wb') as fid:
                fid.write(b64str_to_bytes(m_data))

        #logger.info("Finished writing {} module files".format(len(loaded_func_all['module_data'])))
        #logger.debug(subprocess.check_output("find {}".format(PYTHON_MODULE_PATH), shell=True))
        #logger.debug(subprocess.check_output("find {}".format(os.getcwd()), shell=True))
        logger.debug("Finished writing Function dependencies")

    def _unpickle_function(self, pickled_func):
        """
        Unpickle function; it will expect modules to be there
        """
        logger.debug("Unpickle Function")
        loaded_func = pickle.loads(pickled_func)
        logger.debug("Finished Function unpickle")

        return loaded_func

    def _load_data(self):
        extra_get_args = {}
        if self.data_byte_range is not None:
            range_str = 'bytes={}-{}'.format(*self.data_byte_range)
            extra_get_args['Range'] = range_str

        logger.debug("Getting function data")
        data_download_time_t1 = time.time()
        data_obj = self.internal_storage.get_data(self.data_key, extra_get_args=extra_get_args)
        logger.debug("Finished getting Function data")
        logger.debug("Unpickle Function data")
        loaded_data = pickle.loads(data_obj)
        logger.debug("Finished unpickle Function data")
        data_download_time_t2 = time.time()
        self.stats.write('data_download_time', round(data_download_time_t2-data_download_time_t1, 8))

        return loaded_data

    def _create_storage_clients(self, function, data):
        # Verify storage parameters - Create clients
        func_sig = inspect.signature(function)

        if 'ibm_cos' in func_sig.parameters:
            ibm_boto3_client = IbmCosStorageBackend(self.storage_config['ibm_cos']).get_client()
            data['ibm_cos'] = ibm_boto3_client

        if 'swift' in func_sig.parameters:
            swift_client = SwiftStorageBackend(self.storage_config['swift'])
            data['swift'] = swift_client

        if 'internal_storage' in func_sig.parameters:
            data['internal_storage'] = self.internal_storage

        return data

    def run(self):
        """
        Runs the function
        """
        logger.info("Started")
        # initial output file in case job fails
        result = None
        exception = False
        try:
            self.internal_storage = InternalStorage(self.storage_config)

            loaded_func_all = self._get_function_and_modules()
            self._save_modules(loaded_func_all['module_data'])
            function = self._unpickle_function(loaded_func_all['func'])
            data = self._load_data()
            data = self._create_storage_clients(function, data)

            if self.show_memory:
                logger.debug("Memory usage before call the function: {}".format(get_current_memory_usage()))

            logger.info("Function: Going to execute '{}()'".format(str(function.__name__)))
            print('---------------------- FUNCTION LOG ----------------------', flush=True)
            func_exec_time_t1 = time.time()
            result = function(**data)
            func_exec_time_t2 = time.time()
            print('----------------------------------------------------------', flush=True)
            logger.info("Function: Success execution")

            if self.show_memory:
                logger.debug("Memory usage after call the function: {}".format(get_current_memory_usage()))

            self.stats.write('function_exec_time', round(func_exec_time_t2-func_exec_time_t1, 8))

            # Check for new futures
            if result is not None:
                self.stats.write("result", True)
                if isinstance(result, ResponseFuture):
                    callgroup_id = result.callgroup_id
                    self.stats.write('new_futures', '{}/{}'.format(callgroup_id, 1))
                elif type(result) == list and len(result) > 0 and isinstance(result[0], ResponseFuture):
                    callgroup_id = result[0].callgroup_id
                    self.stats.write('new_futures', '{}/{}'.format(callgroup_id, len(result)))
                else:
                    self.stats.write('new_futures', '{}/{}'.format(None, 0))

                logger.debug("Pickling result")
                output_dict = {'result': result}
                pickled_output = pickle.dumps(output_dict)

                if self.show_memory:
                    logger.debug("Memory usage after output serialization: {}".format(get_current_memory_usage()))
            else:
                logger.debug("No result to store")
                self.stats.write("result", False)

        except Exception as e:
            exception = True
            self.stats.write("exception", True)
            print('----------------------- EXCEPTION !-----------------------')
            logger.error("There was an exception: {}".format(str(e)))
            print('----------------------------------------------------------', flush=True)

            if self.show_memory:
                logger.debug("Memory usage after call the function: {}".format(get_current_memory_usage()))

            try:
                logger.debug("Pickling exception")
                pickled_exc = pickle.dumps(sys.exc_info())
                pickle.loads(pickled_exc)  # this is just to make sure they can be unpickled
                self.stats.write("exc_info", str(pickled_exc))

            except Exception as pickle_exception:
                # Shockingly often, modules like subprocess don't properly
                # call the base Exception.__init__, which results in them
                # being unpickleable. As a result, we actually wrap this in a try/catch block
                # and more-carefully handle the exceptions if any part of this save / test-reload
                # fails
                logger.debug("Failed pickling exception: {}".format(str(pickle_exception)))
                self.stats.write("exc_pickle_fail", True)
                exc_type, exc_value, exc_traceback = sys.exc_info()
                pickled_exc = pickle.dumps({'exc_type': str(exc_type),
                                            'exc_value': str(exc_value),
                                            'exc_traceback': exc_traceback,
                                            'pickle_exception': pickle_exception})
                pickle.loads(pickled_exc)  # this is just to make sure they can be unpickled
                self.stats.write("exc_info", str(pickled_exc))
        finally:
            store_result = strtobool(os.environ.get('STORE_RESULT', 'True'))
            if result is not None and store_result and not exception:
                output_upload_timestamp_t1 = time.time()
                logger.info("Storing function result - output.pickle - Size: {}".format(sizeof_fmt(len(pickled_output))))
                self.internal_storage.put_data(self.output_key, pickled_output)
                output_upload_timestamp_t2 = time.time()
                self.stats.write("output_upload_time", round(output_upload_timestamp_t2 - output_upload_timestamp_t1, 8))
            self.result_queue.put("Finished")
            logger.info("Finished")
