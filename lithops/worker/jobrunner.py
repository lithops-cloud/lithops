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
import ast
import pika
import time
import pickle
import logging
import inspect
import requests
import traceback
from pydoc import locate
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional, Tuple

from lithops.worker.utils import peak_memory

# Importing numpy here makes numpy types pickle-compatible in the worker.
try:
    import numpy as np
    np.__version__
except ModuleNotFoundError:
    pass

from lithops.storage import Storage
from lithops.wait import wait
from lithops.future import ResponseFuture
from lithops.utils import (
    WrappedStreamingBody, sizeof_fmt, is_object_processing_function,
    FuturesList, verify_args, WrappedStreamingBodyPartition
)
from lithops.util.metrics import PrometheusExporter
from lithops.storage.utils import create_output_key

logger = logging.getLogger(__name__)

# Results below this size are written to the stats file, which travels back
# with the call status, instead of being uploaded to storage on their own
_MAX_INLINE_RESULT_SIZE = 8 * 1024


def _prepost(func):
    """Runs the PRE_RUN / POST_RUN callables from the environment around func"""
    def call(env_var):
        if env_var in os.environ:
            method = locate(os.environ[env_var])
            method()

    def wrapper_decorator(*args, **kwargs):
        call('PRE_RUN')
        value = func(*args, **kwargs)
        call('POST_RUN')
        return value
    return wrapper_decorator


class JobStats:
    """
    Line based stats file, written as the task progresses and read back by
    the handler once the JobRunner is done
    """

    def __init__(self, stats_filename: str):
        self.stats_filename = stats_filename
        self.stats_fid = open(stats_filename, 'w')

    def write(self, key: str, value: Any) -> None:
        """Appends one stat, flushed so that it survives a killed worker"""
        self.stats_fid.write(f"{key} {value}\n")
        self.stats_fid.flush()

    def close(self) -> None:
        """Closes the stats file, unless it is closed already"""
        if getattr(self, 'stats_fid', None) and not self.stats_fid.closed:
            self.stats_fid.close()

    def __del__(self):
        self.close()


def _get_function_name(func: Callable) -> str:
    """Returns the name of a function, or of the class of a callable object"""
    if inspect.isfunction(func) or inspect.ismethod(func):
        return func.__name__
    return type(func).__name__


def _returns_futures(result: Any) -> bool:
    """
    Tells whether the function returned futures to chain, instead of data.
    A list is only inspected by its first element, as the client does
    """
    if isinstance(result, (ResponseFuture, FuturesList)):
        return True
    return (
        isinstance(result, list)
        and len(result) > 0
        and isinstance(result[0], ResponseFuture)
    )


class JobRunner:
    """
    Runs the user function of a single task, isolated from the handler, and
    reports the result and the stats through the task stats file
    """

    def __init__(self, job: SimpleNamespace, jobrunner_conn, internal_storage):
        self.job = job
        self.jobrunner_conn = jobrunner_conn
        self.internal_storage = internal_storage
        self.lithops_config = job.config

        self.output_key = create_output_key(
            job.executor_id, job.job_id, job.call_id
        )
        self.stats = JobStats(self.job.stats_file)

        prom_enabled = self.lithops_config['lithops'].get('telemetry')
        prom_config = self.lithops_config.get('prometheus', {})
        self.prometheus = PrometheusExporter(prom_enabled, prom_config)

    def _prom_labels(
        self, fn_name: Optional[str]
    ) -> Tuple[Tuple[str, str], ...]:
        return (
            ('job_id', self.job.job_key),
            ('call_id', '-'.join([self.job.job_key, self.job.call_id])),
            ('function_name', fn_name or 'undefined')
        )

    def _create_ibm_cos_client(self):
        """Creates the boto3 client injected as the ibm_cos parameter"""
        if 'ibm_cos' not in self.lithops_config:
            raise Exception(
                'Cannot create the ibm_cos client: missing configuration'
            )

        if self.internal_storage.backend == 'ibm_cos':
            return self.internal_storage.get_client()

        return Storage(
            config=self.lithops_config, backend='ibm_cos'
        ).get_client()

    def _create_rabbitmq_connection(self):
        """Creates the connection injected as the rabbitmq parameter"""
        if 'rabbitmq' not in self.lithops_config:
            raise Exception(
                'Cannot create the rabbitmq client: missing configuration'
            )

        rabbit_amqp_url = self.lithops_config['rabbitmq'].get('amqp_url')
        return pika.BlockingConnection(pika.URLParameters(rabbit_amqp_url))

    def _fill_optional_args(
        self, function: Callable, data: Dict[str, Any]
    ) -> None:
        """
        Fills in those reserved, optional parameters that might be written to
        the function signature
        """
        func_sig = inspect.signature(function)

        if len(data) == 1 and 'future' in data:
            # Function chaining feature
            out = [
                data.pop('future').result(
                    internal_storage=self.internal_storage
                )
            ]
            data.update(verify_args(function, out, None)[0])

        if 'ibm_cos' in func_sig.parameters:
            data['ibm_cos'] = self._create_ibm_cos_client()

        if 'storage' in func_sig.parameters:
            data['storage'] = self.internal_storage.storage

        if 'rabbitmq' in func_sig.parameters:
            data['rabbitmq'] = self._create_rabbitmq_connection()

        if 'id' in func_sig.parameters:
            data['id'] = int(self.job.call_id)

    def _wait_futures(self, data: Dict[str, Any]) -> None:
        """
        Replaces the futures a reduce function receives by their results,
        blocking until every one of them is done
        """
        logger.info('Reduce function: waiting for map results')
        key = next(iter(data))
        fut_list = data[key]
        wait(fut_list, self.internal_storage, download_results=True)
        results = [f.result() for f in fut_list if f.done and not f.futures]
        fut_list.clear()
        data[key] = results

    def _open_object_stream(self, obj: Any, extra_get_args: Dict[str, Any]):
        """Opens the object to process, wherever it lives"""
        if hasattr(obj, 'bucket') and not hasattr(obj, 'path'):
            logger.info(
                f'Getting dataset from {obj.backend}://{obj.bucket}/{obj.key}'
            )
            if obj.backend == self.internal_storage.backend:
                storage = self.internal_storage.storage
            else:
                storage = Storage(
                    config=self.lithops_config, backend=obj.backend
                )
            return storage.get_object(
                obj.bucket, obj.key, stream=True, extra_get_args=extra_get_args
            )

        if hasattr(obj, 'url'):
            logger.info(f'Getting dataset from {obj.url}')
            return requests.get(
                obj.url, headers=extra_get_args, stream=True
            ).raw

        logger.info(f'Getting dataset from {obj.path}')
        with open(obj.path, "rb") as f:
            if obj.data_byte_range is None:
                return io.BytesIO(f.read())
            first_byte, last_byte = obj.data_byte_range
            f.seek(first_byte)
            return io.BytesIO(f.read(last_byte - first_byte + 1))

    def _load_object(self, data: Dict[str, Any]) -> None:
        """
        Opens the object to process as a stream, and narrows its byte range
        down to the chunk that this task is responsible for
        """
        obj = data['obj']
        extra_get_args = {}
        if obj.data_byte_range is not None:
            first_byte, last_byte = obj.data_byte_range
            extra_get_args['Range'] = f'bytes={first_byte}-{last_byte}'

        stream = self._open_object_stream(obj, extra_get_args)

        if obj.data_byte_range is None:
            obj.data_stream = stream
            first_byte = 0
            last_byte = obj.chunk_size - 1
            obj.data_byte_range = (first_byte, last_byte)
        else:
            if obj.newline is None:
                obj.data_stream = WrappedStreamingBody(stream, obj.chunk_size)
            else:
                obj.data_stream = WrappedStreamingBodyPartition(
                    stream, obj.chunk_size, obj.data_byte_range, obj.newline
                )
            if last_byte - first_byte > obj.chunk_size:
                last_byte = first_byte + obj.chunk_size - 1
                obj.data_byte_range = (first_byte, last_byte)

        logger.info(
            f'Chunk: {obj.part}/{obj.total_parts} - Size: {obj.chunk_size} - '
            f'Range: {first_byte}-{last_byte}'
        )

    def _write_function_stats(
        self, start_tstamp: float, end_tstamp: float
    ) -> None:
        """
        Reports how long the user function took, with a result size that
        _write_result overwrites if the function returned anything
        """
        self.stats.write('worker_func_start_tstamp', start_tstamp)
        self.stats.write('worker_func_end_tstamp', end_tstamp)
        self.stats.write(
            'worker_func_exec_time', round(end_tstamp - start_tstamp, 8)
        )
        self.stats.write('func_result_size', 0)

    def _write_result(self, result: Any) -> Optional[bytes]:
        """
        Reports the result of the function, and returns the pickled result
        back when it is too big to travel with the call status
        """
        if result is None:
            return None

        if _returns_futures(result):
            self.stats.write('new_futures', pickle.dumps(result))
            return None

        logger.debug("Pickling result")
        pickled_output = pickle.dumps(result)
        self.stats.write('func_result_size', len(pickled_output))

        if len(pickled_output) >= _MAX_INLINE_RESULT_SIZE:
            return pickled_output

        self.stats.write('result', pickled_output)
        self.stats.write("worker_result_upload_time", 0)
        return None

    def _write_exception(self) -> None:
        """
        Prints the traceback to the task log and reports the exception, so
        that the client can re-raise it. Only valid while handling one
        """
        self.stats.write("exception", True)
        exc_type, exc_value, exc_traceback = sys.exc_info()
        print('----------------------- EXCEPTION !-----------------------')
        traceback.print_exc(file=sys.stdout)
        print('----------------------------------------------------------')

        try:
            logger.debug("Pickling exception")
            pickled_exc = pickle.dumps((exc_type, exc_value, exc_traceback))
            pickle.loads(pickled_exc)

        except Exception as pickle_exception:
            # Shockingly often, modules like subprocess don't properly call
            # the base Exception.__init__, which results in them being
            # unpickleable. Report the pieces that do pickle instead of
            # losing the exception altogether
            self.stats.write("exc_pickle_fail", True)
            pickled_exc = pickle.dumps({
                'exc_type': str(exc_type),
                'exc_value': str(exc_value),
                'exc_traceback': exc_traceback,
                'pickle_exception': pickle_exception,
            })
            pickle.loads(pickled_exc)

        self.stats.write("exc_info", str(pickled_exc))

    def _upload_result(self, pickled_output: bytes) -> None:
        """
        Uploads a result too big to travel with the call status, and reports
        how long the upload took
        """
        upload_start_tstamp = time.time()
        logger.info(
            f"Storing function result - "
            f"Size: {sizeof_fmt(len(pickled_output))}"
        )
        self.internal_storage.put_data(self.output_key, pickled_output)
        upload_end_tstamp = time.time()
        self.stats.write(
            "worker_result_upload_time",
            round(upload_end_tstamp - upload_start_tstamp, 8)
        )

    @_prepost
    def run(self) -> None:
        """
        Runs the user function and reports everything the client needs: its
        result or its exception, its stats and its peak memory
        """
        self.stats.write('worker_peak_memory_start', peak_memory())
        logger.debug("Process started")
        fn_name = None
        pending_output = None

        try:
            func = pickle.loads(self.job.func)
            data = pickle.loads(self.job.data)

            if ast.literal_eval(os.environ.get('__LITHOPS_REDUCE_JOB', 'False')):
                self._wait_futures(data)
            elif is_object_processing_function(func):
                self._load_object(data)

            self._fill_optional_args(func, data)

            fn_name = _get_function_name(func)
            self.prometheus.send_metric(
                name='function_start',
                value=time.time(),
                type='gauge',
                labels=self._prom_labels(fn_name)
            )

            logger.info(f"Going to execute '{fn_name}()'")
            print('---------------------- FUNCTION LOG ----------------------')
            function_start_tstamp = time.time()
            args, kwargs = _prepare_args(func, data)
            result = func(*args, **kwargs)
            function_end_tstamp = time.time()
            print('----------------------------------------------------------')
            logger.info("Success function execution")

            self._write_function_stats(
                function_start_tstamp, function_end_tstamp
            )
            pending_output = self._write_result(result)

        except Exception:
            self._write_exception()

        finally:
            self.stats.write('worker_peak_memory_end', peak_memory())
            self.prometheus.send_metric(
                name='function_end',
                value=time.time(),
                type='gauge',
                labels=self._prom_labels(fn_name)
            )

            if pending_output is not None:
                self._upload_result(pending_output)

            self.jobrunner_conn.send("Finished")
            logger.info("Process finished")
            self.stats.close()


def _prepare_args(
    func: Callable, data: Dict[str, Any]
) -> Tuple[Any, Dict[str, Any]]:
    """
    Converts the data envelope into normal args and kwargs, respecting the
    actual var-length parameter names of func
    """
    func_sig = inspect.signature(func)
    var_pos_name = None
    var_kw_name = None

    for name, param in func_sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            var_pos_name = name
        elif param.kind == inspect.Parameter.VAR_KEYWORD:
            var_kw_name = name

    payload = dict(data)

    if var_pos_name is not None and var_pos_name in payload:
        args = payload.pop(var_pos_name)
        if args is None:
            args = ()
    else:
        args = ()

    if var_kw_name is not None and var_kw_name in payload:
        kwargs = payload.pop(var_kw_name)
        if kwargs is None:
            kwargs = {}
    else:
        kwargs = {}

    kwargs.update(payload)

    return args, kwargs
