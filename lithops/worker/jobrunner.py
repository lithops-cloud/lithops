#
# (C) Copyright IBM Corp. 2020
# (C) Copyright Cloudlab URV 2021
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
import io
import sys
import pika
import time
import pickle
import logging
import inspect
import requests
import traceback
from pydoc import locate
from distutils.util import strtobool

try:
    import numpy as np
except ModuleNotFoundError:
    pass

from lithops.storage import Storage
from lithops.wait import wait
from lithops.future import ResponseFuture
from lithops.utils import sizeof_fmt, is_object_processing_function, FuturesList,\
    verify_args
from lithops.utils import WrappedStreamingBodyPartition
from lithops.util.metrics import PrometheusExporter
from lithops.storage.utils import create_output_key

logger = logging.getLogger(__name__)


class JobStats:

    def __init__(self, stats_filename):
        self.stats_filename = stats_filename
        self.stats_fid = open(stats_filename, 'w')

    def write(self, key, value):
        self.stats_fid.write("{} {}\n".format(key, value))
        self.stats_fid.flush()

    def __del__(self):
        self.stats_fid.close()


class JobRunner:

    def __init__(self, job, jobrunner_conn, internal_storage):
        self.job = job
        self.jobrunner_conn = jobrunner_conn
        self.internal_storage = internal_storage
        self.lithops_config = job.config

        self.output_key = create_output_key(job.executor_id, job.job_id, job.call_id)

        # Setup stats class
        self.stats = JobStats(self.job.stats_file)

        # Setup prometheus for live metrics
        prom_enabled = self.lithops_config['lithops'].get('telemetry')
        prom_config = self.lithops_config.get('prometheus', {})
        self.prometheus = PrometheusExporter(prom_enabled, prom_config)

    def _fill_optional_args(self, function, data):
        """
        Fills in those reserved, optional parameters that might be write to the function signature
        """
        func_sig = inspect.signature(function)

        if len(data) == 1 and 'future' in data:
            # Function chaining feature
            out = [data.pop('future').result(internal_storage=self.internal_storage)]
            data.update(verify_args(function, out, None)[0])

        if 'ibm_cos' in func_sig.parameters:
            if 'ibm_cos' in self.lithops_config:
                if self.internal_storage.backend == 'ibm_cos':
                    ibm_boto3_client = self.internal_storage.get_client()
                else:
                    ibm_boto3_client = Storage(config=self.lithops_config, backend='ibm_cos').get_client()
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
            data['id'] = int(self.job.call_id)

    def _wait_futures(self, data):
        logger.info('Reduce function: waiting for map results')
        fut_list = data['results']
        wait(fut_list, self.internal_storage, download_results=True)
        results = [f.result() for f in fut_list if f.done and not f.futures]
        fut_list.clear()
        data['results'] = results

    def _load_object(self, data):
        """
        Loads the object in /tmp in case of object processing
        """
        extra_get_args = {}

        obj = data['obj']

        if hasattr(obj, 'bucket') and not hasattr(obj, 'path'):
            logger.info('Getting dataset from {}://{}/{}'.format(obj.backend, obj.bucket, obj.key))

            if obj.backend == self.internal_storage.backend:
                storage = self.internal_storage.storage
            else:
                storage = Storage(config=self.lithops_config, backend=obj.backend)

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

        elif hasattr(obj, 'url'):
            logger.info('Getting dataset from {}'.format(obj.url))
            if obj.data_byte_range is not None:
                range_str = 'bytes={}-{}'.format(*obj.data_byte_range)
                extra_get_args['Range'] = range_str
                logger.info('Chunk: {} - Range: {}'.format(obj.part, extra_get_args['Range']))
            resp = requests.get(obj.url, headers=extra_get_args, stream=True)
            obj.data_stream = resp.raw

        elif hasattr(obj, 'path'):
            logger.info('Getting dataset from {}'.format(obj.path))
            with open(obj.path, "rb") as f:
                if obj.data_byte_range is not None:
                    extra_get_args['Range'] = 'bytes={}-{}'.format(*obj.data_byte_range)
                    logger.info('Chunk: {} - Range: {}'.format(obj.part, extra_get_args['Range']))
                    first_byte, last_byte = obj.data_byte_range
                    f.seek(first_byte)
                    buffer = io.BytesIO(f.read(last_byte-first_byte+1))
                    sb = WrappedStreamingBodyPartition(buffer, obj.chunk_size, obj.data_byte_range)
                else:
                    sb = io.BytesIO(f.read())
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
        logger.debug("Process started")
        result = None
        exception = False
        fn_name = None

        try:
            func = pickle.loads(self.job.func)
            data = pickle.loads(self.job.data)

            if strtobool(os.environ.get('__LITHOPS_REDUCE_JOB', 'False')):
                self._wait_futures(data)
            elif is_object_processing_function(func):
                self._load_object(data)

            self._fill_optional_args(func, data)

            fn_name = func.__name__ if inspect.isfunction(func) \
                or inspect.ismethod(func) else type(func).__name__

            self.prometheus.send_metric(
                name='function_start',
                value=time.time(),
                type='gauge',
                labels=(
                    ('job_id', self.job.job_key),
                    ('call_id', '-'.join([self.job.job_key, self.job.call_id])),
                    ('function_name', fn_name or 'undefined')
                )
            )

            logger.info("Going to execute '{}()'".format(str(fn_name)))
            print('---------------------- FUNCTION LOG ----------------------')
            function_start_tstamp = time.time()
            result = func(**data)
            function_end_tstamp = time.time()
            print('----------------------------------------------------------')
            logger.info("Success function execution")

            self.stats.write('worker_func_start_tstamp', function_start_tstamp)
            self.stats.write('worker_func_end_tstamp', function_end_tstamp)
            self.stats.write('worker_func_exec_time', round(function_end_tstamp-function_start_tstamp, 8))

            # Check for new futures
            if result is not None:
                if isinstance(result, ResponseFuture) or isinstance(result, FuturesList) \
                   or (type(result) == list and len(result) > 0 and isinstance(result[0], ResponseFuture)):
                    self.stats.write('new_futures', pickle.dumps(result))
                    result = None
                else:
                    self.stats.write("result", True)
                    logger.debug("Pickling result")
                    output_dict = {'result': result}
                    pickled_output = pickle.dumps(output_dict)
                    self.stats.write('func_result_size', len(pickled_output))

            if result is None:
                logger.debug("No result to store")
                self.stats.write("result", False)
                self.stats.write('func_result_size', 0)

            # self.stats.write('worker_jobrunner_end_tstamp', time.time())

        except Exception:
            exception = True
            self.stats.write("exception", True)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print('----------------------- EXCEPTION !-----------------------')
            traceback.print_exc(file=sys.stdout)
            print('----------------------------------------------------------')

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
            self.prometheus.send_metric(
                name='function_end',
                value=time.time(),
                type='gauge',
                labels=(
                    ('job_id', self.job.job_key),
                    ('call_id', '-'.join([self.job.job_key, self.job.call_id])),
                    ('function_name', fn_name or 'undefined')
                )
            )

            store_result = strtobool(os.environ.get('STORE_RESULT', 'True'))
            if result is not None and store_result and not exception:
                output_upload_start_tstamp = time.time()
                logger.info("Storing function result - Size: {}".format(sizeof_fmt(len(pickled_output))))
                self.internal_storage.put_data(self.output_key, pickled_output)
                output_upload_end_tstamp = time.time()
                self.stats.write("worker_result_upload_time", round(output_upload_end_tstamp - output_upload_start_tstamp, 8))
            self.jobrunner_conn.send("Finished")
            logger.info("Process finished")
