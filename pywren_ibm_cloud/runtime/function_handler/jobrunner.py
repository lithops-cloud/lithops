#
# (C) Copyright PyWren Team
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
import pika
import time
import pickle
import tempfile
import logging
import inspect
import requests
import traceback
import numpy as np
from distutils.util import strtobool
from pywren_ibm_cloud.storage import Storage
from pywren_ibm_cloud.future import ResponseFuture
from pywren_ibm_cloud.libs.tblib import pickling_support
from pywren_ibm_cloud.utils import sizeof_fmt, b64str_to_bytes, is_object_processing_function
from pywren_ibm_cloud.utils import get_current_memory_usage, WrappedStreamingBodyPartition
from pywren_ibm_cloud.config import extract_storage_config, cloud_logging_config

pickling_support.install()
logger = logging.getLogger('JobRunner')

TEMP = tempfile.gettempdir()
PYTHON_MODULE_PATH = os.path.join(TEMP, "pywren.modules")


class stats:

    def __init__(self, stats_filename):
        self.stats_filename = stats_filename
        self.stats_fid = open(stats_filename, 'w')

    def write(self, key, value):
        self.stats_fid.write("{} {}\n".format(key, value))
        self.stats_fid.flush()

    def __del__(self):
        self.stats_fid.close()


class JobRunner:

    def __init__(self, jr_config, jobrunner_conn, internal_storage):
        self.jr_config = jr_config
        self.jobrunner_conn = jobrunner_conn
        self.internal_storage = internal_storage

        log_level = self.jr_config['log_level']
        cloud_logging_config(log_level)
        self.pywren_config = self.jr_config['pywren_config']
        self.storage_config = extract_storage_config(self.pywren_config)

        self.call_id = self.jr_config['call_id']
        self.job_id = self.jr_config['job_id']
        self.executor_id = self.jr_config['executor_id']
        self.func_key = self.jr_config['func_key']
        self.data_key = self.jr_config['data_key']
        self.data_byte_range = self.jr_config['data_byte_range']
        self.output_key = self.jr_config['output_key']

        self.stats = stats(self.jr_config['stats_filename'])

        self.show_memory = strtobool(os.environ.get('SHOW_MEMORY_USAGE', 'False'))

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
        if module_data:
            logger.debug("Writing Function dependencies to local disk")
            module_path = os.path.join(PYTHON_MODULE_PATH, self.executor_id,
                                       self.job_id, self.call_id)
            # shutil.rmtree(PYTHON_MODULE_PATH, True)  # delete old modules
            os.makedirs(module_path, exist_ok=True)
            sys.path.append(module_path)

            for m_filename, m_data in module_data.items():
                m_path = os.path.dirname(m_filename)

                if len(m_path) > 0 and m_path[0] == "/":
                    m_path = m_path[1:]
                to_make = os.path.join(module_path, m_path)
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

            #logger.info("Finished writing {} module files".format(len(module_data)))
            #logger.debug(subprocess.check_output("find {}".format(module_path), shell=True))
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

    def _fill_optional_args(self, function, data):
        """
        Fills in those reserved, optional parameters that might be write to the function signature
        """
        func_sig = inspect.signature(function)

        if 'ibm_cos' in func_sig.parameters:
            if 'ibm_cos' in self.pywren_config:
                if self.internal_storage.backend == 'ibm_cos':
                    ibm_boto3_client = self.internal_storage.storage_handler.get_client()
                else:
                    ibm_boto3_client = Storage(self.pywren_config, 'ibm_cos').get_client()
                data['ibm_cos'] = ibm_boto3_client
            else:
                logger.error('Cannot create the ibm_cos connection: Configuration not provided')
                data['ibm_cos'] = None

        if 'internal_storage' in func_sig.parameters:
            data['internal_storage'] = self.internal_storage

        if 'rabbitmq' in func_sig.parameters:
            if 'rabbitmq' in self.pywren_config:
                try:
                    rabbit_amqp_url = self.pywren_config['rabbitmq'].get('amqp_url')
                    params = pika.URLParameters(rabbit_amqp_url)
                    connection = pika.BlockingConnection(params)
                    data['rabbitmq'] = connection
                except Exception as e:
                    logger.error('Cannot create the rabbitmq connection: {}', str(e))
                    data['rabbitmq'] = None
            else:
                logger.error('Cannot create the rabbitmq connection: Configuration not provided')
                data['rabbitmq'] = None

        if 'id' in func_sig.parameters:
            data['id'] = int(self.call_id)

    def _create_data_stream(self, data):
        """
        Creates the data stream in case of object processing
        """
        extra_get_args = {}

        if 'url' in data:
            url = data['url']
            logger.info('Getting dataset from {}'.format(url.path))
            if url.data_byte_range is not None:
                range_str = 'bytes={}-{}'.format(*url.data_byte_range)
                extra_get_args['Range'] = range_str
                logger.info('Chunk: {} - Range: {}'.format(url.part, extra_get_args['Range']))
            resp = requests.get(url.path, headers=extra_get_args, stream=True)
            url.data_stream = resp.raw

        if 'obj' in data:
            obj = data['obj']
            if obj.storage_backend == self.internal_storage.backend:
                storage_handler = self.internal_storage.storage_handler
            else:
                storage_handler = Storage(self.pywren_config, obj.storage_backend).get_storage_handler()
            logger.info('Getting dataset from {}://{}/{}'.format(obj.storage_backend, obj.bucket, obj.key))
            if obj.data_byte_range is not None:
                extra_get_args['Range'] = 'bytes={}-{}'.format(*obj.data_byte_range)
                logger.info('Chunk: {} - Range: {}'.format(obj.part, extra_get_args['Range']))
                sb = storage_handler.get_object(obj.bucket, obj.key, stream=True, extra_get_args=extra_get_args)
                obj.data_stream = WrappedStreamingBodyPartition(sb, obj.chunk_size, obj.data_byte_range)
            else:
                obj.data_stream = storage_handler.get_object(obj.bucket, obj.key, stream=True)

    def run(self):
        """
        Runs the function
        """
        # self.stats.write('jobrunner_start', time.time())
        logger.info("Started")
        result = None
        exception = False
        try:
            self.internal_storage.tmp_obj_prefix = self.output_key.rsplit('/', 1)[0]
            loaded_func_all = self._get_function_and_modules()
            self._save_modules(loaded_func_all['module_data'])
            function = self._unpickle_function(loaded_func_all['func'])
            data = self._load_data()

            if is_object_processing_function(function):
                self._create_data_stream(data)

            self._fill_optional_args(function, data)

            if self.show_memory:
                logger.debug("Memory usage before call the function: {}".format(get_current_memory_usage()))

            logger.info("Going to execute '{}()'".format(str(function.__name__)))
            print('---------------------- FUNCTION LOG ----------------------', flush=True)
            func_exec_time_t1 = time.time()
            result = function(**data)
            func_exec_time_t2 = time.time()
            print('----------------------------------------------------------', flush=True)
            logger.info("Success function execution")

            if self.show_memory:
                logger.debug("Memory usage after call the function: {}".format(get_current_memory_usage()))

            self.stats.write('function_exec_time', round(func_exec_time_t2-func_exec_time_t1, 8))

            # Check for new futures
            if result is not None:
                self.stats.write("result", True)
                if isinstance(result, ResponseFuture) or \
                   (type(result) == list and len(result) > 0 and isinstance(result[0], ResponseFuture)):
                    self.stats.write('new_futures', True)

                logger.debug("Pickling result")
                output_dict = {'result': result}
                pickled_output = pickle.dumps(output_dict)

                if self.show_memory:
                    logger.debug("Memory usage after output serialization: {}".format(get_current_memory_usage()))
            else:
                logger.debug("No result to store")
                self.stats.write("result", False)

        except Exception:
            exception = True
            self.stats.write("exception", True)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print('----------------------- EXCEPTION !-----------------------', flush=True)
            traceback.print_exc(file=sys.stdout)
            print('----------------------------------------------------------', flush=True)

            if self.show_memory:
                logger.debug("Memory usage after call the function: {}".format(get_current_memory_usage()))

            try:
                logger.debug("Pickling exception")
                pickled_exc = pickle.dumps((exc_type, exc_value, exc_traceback))
                pickle.loads(pickled_exc)  # this is just to make sure they can be unpickled
                self.stats.write("exc_info", str(pickled_exc))

            except Exception as pickle_exception:
                # Shockingly often, modules like subprocess don't properly
                # call the base Exception.__init__, which results in them
                # being unpickleable. As a result, we actually wrap this in a try/catch block
                # and more-carefully handle the exceptions if any part of this save / test-reload
                # fails
                self.stats.write("exc_pickle_fail", True)
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
                logger.info("Storing function result - Size: {}".format(sizeof_fmt(len(pickled_output))))
                self.internal_storage.put_data(self.output_key, pickled_output)
                output_upload_timestamp_t2 = time.time()
                self.stats.write("output_upload_time", round(output_upload_timestamp_t2 - output_upload_timestamp_t1, 8))
            self.jobrunner_conn.send("Finished")
            logger.info("Finished")
