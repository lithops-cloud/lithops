#
# (C) Copyright PyWren Team
# Copyright IBM Corp. 2019
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
import logging
import inspect
import requests
import traceback
import numpy as np
from pydoc import locate
from distutils.util import strtobool

from lithops.storage import Storage
from lithops.wait import wait_storage
from lithops.future import ResponseFuture
from lithops.utils import sizeof_fmt, b64str_to_bytes, is_object_processing_function
from lithops.utils import WrappedStreamingBodyPartition
from lithops.constants import TEMP


logger = logging.getLogger(__name__)


PYTHON_MODULE_PATH = os.path.join(TEMP, "lithops.modules")


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

        self.lithops_config = self.jr_config['lithops_config']
        self.call_id = self.jr_config['call_id']
        self.job_id = self.jr_config['job_id']
        self.executor_id = self.jr_config['executor_id']
        self.func_key = self.jr_config['func_key']
        self.data_key = self.jr_config['data_key']
        self.data_byte_range = self.jr_config['data_byte_range']
        self.output_key = self.jr_config['output_key']

        self.stats = stats(self.jr_config['stats_filename'])

    def _get_function_and_modules(self):
        """
        Gets and unpickles function and modules from storage
        """
        logger.debug("Getting function and modules")
        func_download_start_tstamp = time.time()
        func_obj = self.internal_storage.get_func(self.func_key)
        loaded_func_all = pickle.loads(func_obj)
        func_download_end_tstamp = time.time()
        self.stats.write('worker_func_download_time', round(func_download_end_tstamp-func_download_start_tstamp, 8))
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
        data_download_start_tstamp = time.time()
        data_obj = self.internal_storage.get_data(self.data_key, extra_get_args=extra_get_args)
        logger.debug("Finished getting Function data")
        logger.debug("Unpickle Function data")
        loaded_data = pickle.loads(data_obj)
        logger.debug("Finished unpickle Function data")
        data_download_end_tstamp = time.time()
        self.stats.write('worker_data_download_time', round(data_download_end_tstamp-data_download_start_tstamp, 8))

        return loaded_data

    def _fill_optional_args(self, function, data):
        """
        Fills in those reserved, optional parameters that might be write to the function signature
        """
        func_sig = inspect.signature(function)

        if 'ibm_cos' in func_sig.parameters:
            if 'ibm_cos' in self.lithops_config:
                if self.internal_storage.backend == 'ibm_cos':
                    ibm_boto3_client = self.internal_storage.get_client()
                else:
                    ibm_boto3_client = Storage(lithops_config=self.lithops_config, storage_backend='ibm_cos').get_client()
                data['ibm_cos'] = ibm_boto3_client
            else:
                raise Exception('Cannot create the ibm_cos client: missing configuration')

        if 'storage' in func_sig.parameters:
            data['storage'] = self.internal_storage.storage

        if 'rabbitmq' in func_sig.parameters:
            if 'rabbitmq' in self.lithops_config:
                rabbit_amqp_url = self.lithops_config['rabbitmq'].get('amqp_url')
                params = pika.URLParameters(rabbit_amqp_url)
                connection = pika.BlockingConnection(params)
                data['rabbitmq'] = connection
            else:
                raise Exception('Cannot create the rabbitmq client: missing configuration')

        if 'id' in func_sig.parameters:
            data['id'] = int(self.call_id)

    def _wait_futures(self, data):
        logger.info('Reduce function: waiting for map results')
        fut_list = data['results']
        wait_storage(fut_list, self.internal_storage, download_results=True)
        results = [f.result() for f in fut_list if f.done and not f.futures]
        fut_list.clear()
        data['results'] = results

    def _load_object(self, data):
        """
        Loads the object in /tmp in case of object processing
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
            logger.info('Getting dataset from {}://{}/{}'.format(obj.backend, obj.bucket, obj.key))

            if obj.backend == self.internal_storage.backend:
                storage = self.internal_storage.storage
            else:
                storage = Storage(lithops_config=self.lithops_config, storage_backend=obj.backend)

            if obj.data_byte_range is not None:
                extra_get_args['Range'] = 'bytes={}-{}'.format(*obj.data_byte_range)
                logger.info('Chunk: {} - Range: {}'.format(obj.part, extra_get_args['Range']))
                sb = storage.get_object(obj.bucket, obj.key, stream=True,
                                        extra_get_args=extra_get_args)
                wsb = WrappedStreamingBodyPartition(sb, obj.chunk_size, obj.data_byte_range)
                obj.data_stream = wsb
            else:
                sb = storage.get_object(obj.bucket, obj.key, stream=True,
                                        extra_get_args=extra_get_args)
                obj.data_stream = sb

    # Decorator to execute pre-run and post-run functions provided via environment variables
    def prepost(func):
        def call(envVar):
            if envVar in os.environ:
                method = locate(os.environ[envVar])
                method()

        def wrapper_decorator(*args, **kwargs):
            call('PRE_RUN')
            value = func(*args, **kwargs)
            call('POST_RUN')
            return value
        return wrapper_decorator

    @prepost
    def run(self):
        """
        Runs the function
        """
        # self.stats.write('worker_jobrunner_start_tstamp', time.time())
        logger.info("Process started")
        result = None
        exception = False
        try:
            loaded_func_all = self._get_function_and_modules()
            self._save_modules(loaded_func_all['module_data'])
            function = self._unpickle_function(loaded_func_all['func'])
            data = self._load_data()

            if strtobool(os.environ.get('__PW_REDUCE_JOB', 'False')):
                self._wait_futures(data)
            elif is_object_processing_function(function):
                self._load_object(data)

            self._fill_optional_args(function, data)

            logger.info("Going to execute '{}()'".format(str(function.__name__)))
            print('---------------------- FUNCTION LOG ----------------------', flush=True)
            function_start_tstamp = time.time()
            result = function(**data)
            function_end_tstamp = time.time()
            print('----------------------------------------------------------', flush=True)
            logger.info("Success function execution")

            self.stats.write('worker_func_start_tstamp', function_start_tstamp)
            self.stats.write('worker_func_end_tstamp', function_end_tstamp)
            self.stats.write('worker_func_exec_time', round(function_end_tstamp-function_start_tstamp, 8))

            # Check for new futures
            if result is not None:
                self.stats.write("result", True)
                if isinstance(result, ResponseFuture) or \
                   (type(result) == list and len(result) > 0 and isinstance(result[0], ResponseFuture)):
                    self.stats.write('new_futures', True)

                logger.debug("Pickling result")
                output_dict = {'result': result}
                pickled_output = pickle.dumps(output_dict)

            else:
                logger.debug("No result to store")
                self.stats.write("result", False)

            # self.stats.write('worker_jobrunner_end_tstamp', time.time())

        except Exception:
            exception = True
            self.stats.write("exception", True)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print('----------------------- EXCEPTION !-----------------------', flush=True)
            traceback.print_exc(file=sys.stdout)
            print('----------------------------------------------------------', flush=True)

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
                pickle.loads(pickled_exc)  # this is just to make sure it can be unpickled
                self.stats.write("exc_info", str(pickled_exc))
        finally:
            store_result = strtobool(os.environ.get('STORE_RESULT', 'True'))
            if result is not None and store_result and not exception:
                output_upload_start_tstamp = time.time()
                logger.info("Storing function result - Size: {}".format(sizeof_fmt(len(pickled_output))))
                self.internal_storage.put_data(self.output_key, pickled_output)
                output_upload_end_tstamp = time.time()
                self.stats.write("worker_result_upload_time", round(output_upload_end_tstamp - output_upload_start_tstamp, 8))
            self.jobrunner_conn.send("Finished")
            logger.info("Process finished")
