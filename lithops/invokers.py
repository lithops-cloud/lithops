# (C) Copyright IBM Corp. 2020
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
import sys
import time
import random
import queue
import shutil
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from lithops.future import ResponseFuture
from lithops.config import extract_storage_config
from lithops.version import __version__
from lithops.utils import (
    verify_runtime_name,
    version_str,
    is_lithops_worker,
    iterchunks,
    BackendType
)
from lithops.constants import (
    LOGGER_LEVEL,
    LOGS_DIR,
    SERVERLESS,
    SA_INSTALL_DIR,
    STANDALONE_BACKENDS
)
from lithops.util.metrics import PrometheusExporter

logger = logging.getLogger(__name__)


def create_invoker(config, executor_id, internal_storage,
                   compute_handler, job_monitor):
    """
    Creates the appropriate invoker based on the backend type
    """
    if compute_handler.get_backend_type() == BackendType.BATCH.value:
        return BatchInvoker(
            config,
            executor_id,
            internal_storage,
            compute_handler,
            job_monitor
        )

    elif compute_handler.get_backend_type() == BackendType.FAAS.value:
        return FaaSInvoker(
            config,
            executor_id,
            internal_storage,
            compute_handler,
            job_monitor
        )


class Invoker:
    """
    Abstract invoker class
    """

    def __init__(self, config, executor_id, internal_storage, compute_handler, job_monitor):
        log_level = logger.getEffectiveLevel()
        self.log_active = log_level != logging.WARNING
        self.log_level = LOGGER_LEVEL if not self.log_active else log_level

        self.config = config
        self.executor_id = executor_id
        self.storage_config = extract_storage_config(self.config)
        self.internal_storage = internal_storage
        self.compute_handler = compute_handler
        self.is_lithops_worker = is_lithops_worker()
        self.job_monitor = job_monitor

        prom_enabled = self.config['lithops'].get('telemetry', False)
        prom_config = self.config.get('prometheus', {})
        self.prometheus = PrometheusExporter(prom_enabled, prom_config)

        self.mode = self.config['lithops']['mode']
        self.backend = self.config['lithops']['backend']
        self.include_function = self.config[self.backend].get('runtime_include_function', False)

        self.runtime_info = self.compute_handler.get_runtime_info()
        self.runtime_name = self.runtime_info['runtime_name']
        self.max_workers = self.runtime_info['max_workers']

        verify_runtime_name(self.runtime_name)

        logger.debug(f'ExecutorID {self.executor_id} - Invoker initialized.'
                     f' Max workers: {self.max_workers}')

    def select_runtime(self, job_id, runtime_memory):
        """
        Return the runtime metadata
        """
        runtime_memory = runtime_memory or self.runtime_info['runtime_memory'] \
            if self.mode == SERVERLESS else self.runtime_info['runtime_memory']
        runtime_timeout = self.runtime_info['runtime_timeout']

        msg = ('ExecutorID {} | JobID {} - Selected Runtime: {} '
               .format(self.executor_id, job_id, self.runtime_name))
        msg = msg + f'- {runtime_memory}MB' if runtime_memory else msg
        logger.info(msg)

        runtime_key = self.compute_handler.get_runtime_key(self.runtime_name, runtime_memory, __version__)
        runtime_meta = self.internal_storage.get_runtime_meta(runtime_key)

        if not runtime_meta:
            msg = f'Runtime {self.runtime_name}'
            msg = msg + f' with {runtime_memory}MB' if runtime_memory else msg
            logger.info(msg + ' is not yet deployed')
            runtime_meta = self.compute_handler.deploy_runtime(self.runtime_name, runtime_memory, runtime_timeout)
            runtime_meta['runtime_timeout'] = runtime_timeout
            self.internal_storage.put_runtime_meta(runtime_key, runtime_meta)

        # Verify python version and lithops version
        if __version__ != runtime_meta['lithops_version']:
            raise Exception("Lithops version mismatch. Host version: {} - Runtime version: {}"
                            .format(__version__, runtime_meta['lithops_version']))

        py_local_version = version_str(sys.version_info)
        py_remote_version = runtime_meta['python_version']
        if py_local_version != py_remote_version:
            raise Exception(("The indicated runtime '{}' is running Python {} and it "
                             "is not compatible with the local Python version {}")
                            .format(self.runtime_name, py_remote_version, py_local_version))

        return runtime_meta

    def _create_payload(self, job):
        """
        Creates the default payload dictionary
        """
        payload = {
            'config': self.config,
            'chunksize': job.chunksize,
            'log_level': self.log_level,
            'func_name': job.function_name,
            'func_key': job.func_key,
            'data_key': job.data_key,
            'extra_env': job.extra_env,
            'total_calls': job.total_calls,
            'execution_timeout': job.execution_timeout,
            'data_byte_ranges': job.data_byte_ranges,
            'executor_id': job.executor_id,
            'job_id': job.job_id,
            'job_key': job.job_key,
            'max_workers': self.max_workers,
            'call_ids': None,
            'host_submit_tstamp': time.time(),
            'lithops_version': __version__,
            'runtime_name': job.runtime_name,
            'runtime_memory': job.runtime_memory,
            'worker_processes': job.worker_processes
        }

        return payload

    def _run_job(self, job):
        """
        Run a job
        """
        if self.include_function:
            logger.debug('ExecutorID {} | JobID {} - Runtime include function feature '
                         ' is activated' .format(job.executor_id, job.job_id))
            job.runtime_name = self.runtime_name
            extend_runtime(job, self.compute_handler, self.internal_storage)
            self.runtime_name = job.runtime_name

        logger.info(
            f'ExecutorID {job.executor_id} | JobID {job.job_id} - Starting function '
            f'invocation: {job.function_name}() - Total: {job.total_calls} activations'
        )

        self.prometheus.send_metric(
            name='job_total_calls',
            value=job.total_calls,
            type='counter',
            labels=(
                ('job_id', job.job_key),
                ('function_name', job.function_name)
            )
        )

        self.prometheus.send_metric(
            name='job_runtime_memory',
            value=job.runtime_memory or 0,
            type='counter',
            labels=(
                ('job_id', job.job_key),
                ('function_name', job.function_name)
            )
        )

        if self.backend not in STANDALONE_BACKENDS:
            logger.debug(
                f'ExecutorID {job.executor_id} | JobID {job.job_id} - Worker processes: '
                f'{job.worker_processes} - Chunksize: {job.chunksize}'
            )

        try:
            job.runtime_name = self.runtime_name
            self._invoke_job(job)
        except (KeyboardInterrupt, Exception) as e:
            self.stop()
            raise e

        log_file = os.path.join(LOGS_DIR, job.job_key + '.log')
        logger.info(
            f'ExecutorID {job.executor_id} | JobID {job.job_id} - View execution logs at {log_file}'
        )

        # Create all futures
        futures = []
        for i in range(job.total_calls):
            call_id = "{:05d}".format(i)
            fut = ResponseFuture(call_id, job,
                                 job.metadata.copy(),
                                 self.storage_config)
            fut._set_state(ResponseFuture.State.Invoked)
            futures.append(fut)

        job.futures = futures

        return futures

    def stop(self):
        """
        Stop invoker-related processes
        """
        pass


class BatchInvoker(Invoker):
    """
    Module responsible to perform the invocations against a batch backend
    """

    def __init__(self, config, executor_id, internal_storage, compute_handler, job_monitor):
        super().__init__(config, executor_id, internal_storage, compute_handler, job_monitor)
        self.compute_handler.init()

    def _invoke_job(self, job):
        """
        Run a job
        """
        payload = self._create_payload(job)
        payload['call_ids'] = ["{:05d}".format(i) for i in range(job.total_calls)]

        start = time.time()
        activation_id = self.compute_handler.invoke(payload)
        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        logger.debug(
            f'ExecutorID {job.executor_id} | JobID {job.job_id} - Job invoked '
            f'({resp_time}s) - Activation ID: {activation_id or job.job_key}'
        )

    def run_job(self, job):
        """
        Run a job
        """
        futures = self._run_job(job)
        self.job_monitor.start(futures)

        return futures


class FaaSInvoker(Invoker):
    """
    Module responsible to perform the invocations against a FaaS backend
    """
    ASYNC_INVOKERS = 2

    def __init__(self, config, executor_id, internal_storage, compute_handler, job_monitor):
        super().__init__(config, executor_id, internal_storage, compute_handler, job_monitor)

        remote_invoker = self.config[self.backend].get('remote_invoker', False)
        self.remote_invoker = remote_invoker if not is_lithops_worker() else False

        self.invokers = []
        self.ongoing_activations = 0
        self.pending_calls_q = queue.Queue()
        self.should_run = False
        self.sync = is_lithops_worker()

        self.invoke_pool_threads = self.config[self.backend]['invoke_pool_threads']
        self.executor = ThreadPoolExecutor(self.invoke_pool_threads)

        logger.debug(f'ExecutorID {self.executor_id} - Serverless invoker created')

    def _start_async_invokers(self):
        """Starts the invoker process responsible to spawn pending calls
        in background.
        """

        def invoker_process(inv_id):
            """Run process that implements token bucket scheduling approach"""
            logger.debug(f'ExecutorID {self.executor_id} - Async invoker {inv_id} started')

            with ThreadPoolExecutor(max_workers=min(64, self.invoke_pool_threads // 4)) as executor:
                while self.should_run:
                    try:
                        self.job_monitor.token_bucket_q.get()
                        job, call_ids_range = self.pending_calls_q.get()
                    except KeyboardInterrupt:
                        break
                    if self.should_run:
                        executor.submit(self._invoke_task, job, call_ids_range)
                    else:
                        break

            logger.debug(f'ExecutorID {self.executor_id} - Async invoker {inv_id} finished')

        for inv_id in range(self.ASYNC_INVOKERS):
            self.job_monitor.token_bucket_q.put('#')
            p = threading.Thread(target=invoker_process, args=(inv_id,))
            self.invokers.append(p)
            p.daemon = True
            p.start()

    def stop(self):
        """
        Stop async invokers
        """
        if self.invokers:
            logger.debug(f'ExecutorID {self.executor_id} - Stopping async invokers')
            self.should_run = False

            while not self.pending_calls_q.empty():
                try:
                    self.pending_calls_q.get(False)
                except Exception:
                    pass

            for invoker in self.invokers:
                self.job_monitor.token_bucket_q.put('$')
                self.pending_calls_q.put((None, None))

            self.invokers = []

    def _invoke_task(self, job, call_ids_range):
        """Method used to perform the actual invocation against the
        compute backend.
        """
        # prepare payload
        payload = self._create_payload(job)

        call_ids = ["{:05d}".format(i) for i in call_ids_range]
        payload['call_ids'] = call_ids

        if job.data_key:
            data_byte_ranges = [job.data_byte_ranges[int(call_id)] for call_id in call_ids]
            payload['data_byte_ranges'] = data_byte_ranges
        else:
            del payload['data_byte_ranges']
            payload['data_byte_strs'] = [job.data_byte_strs[int(call_id)] for call_id in call_ids]

        # do the invocation
        start = time.time()
        activation_id = self.compute_handler.invoke(payload)
        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        if not activation_id:
            # reached quota limit
            time.sleep(random.randint(0, 5))
            self.pending_calls_q.put((job, call_ids_range))
            self.job_monitor.token_bucket_q.put('#')
            return

        logger.debug(
            f'ExecutorID {job.executor_id} | JobID {job.job_id} - Calls {", ".join(call_ids)} '
            f'invoked ({resp_time}s) - Activation ID: {activation_id}'
        )

    def _invoke_job_remote(self, job):
        """
        Logic for invoking a job using a remote function
        """
        start = time.time()
        payload = {}
        payload['config'] = self.config
        payload['log_level'] = self.log_level
        payload['runtime_name'] = job.runtime_name
        payload['runtime_memory'] = job.runtime_memory
        payload['remote_invoker'] = True
        payload['job'] = job.__dict__

        activation_id = self.compute_handler.invoke(payload)
        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        if activation_id:
            logger.debug(
                f'ExecutorID {job.executor_id} | JobID {job.job_id} - Remote invoker '
                f'call done ({resp_time}s) - Activation ID: {activation_id}'
            )
        else:
            raise Exception('Unable to spawn remote invoker')

    def _invoke_job(self, job):
        """
        Normal Invocation
        Use local threads to perform all the function invocations
        """
        self.compute_handler.pre_invoke(job)

        if self.remote_invoker:
            return self._invoke_job_remote(job)

        if self.should_run is False:
            self.running_workers = 0
            self.should_run = True
            self._start_async_invokers()

        if self.running_workers > 0 and not self.job_monitor.token_bucket_q.empty():
            while not self.job_monitor.token_bucket_q.empty():
                try:
                    self.job_monitor.token_bucket_q.get(False)
                    self.running_workers -= 1
                    if self.running_workers == 0:
                        break
                except Exception:
                    pass

        if self.running_workers < self.max_workers:
            free_workers = self.max_workers - self.running_workers
            total_direct = free_workers * job.chunksize
            callids = range(job.total_calls)
            callids_to_invoke_direct = callids[:total_direct]
            callids_to_invoke_nondirect = callids[total_direct:]

            ci = len(callids_to_invoke_direct)
            cz = job.chunksize
            consumed_workers = ci // cz + (ci % cz > 0)
            self.running_workers += consumed_workers

            logger.debug(
                f'ExecutorID {job.executor_id} | JobID {job.job_id} - Free workers: '
                f'{free_workers} - Going to run {len(callids_to_invoke_direct)} activations '
                f'in {consumed_workers} workers'
            )

            def _callback(future):
                future.result()

            invoke_futures = []
            for call_ids_range in iterchunks(callids_to_invoke_direct, job.chunksize):
                future = self.executor.submit(self._invoke_task, job, call_ids_range)
                future.add_done_callback(_callback)
                invoke_futures.append(future)

            if self.sync:
                [f.result() for f in invoke_futures]

            # Put into the queue the rest of the callids to invoke within the process
            if callids_to_invoke_nondirect:
                logger.debug(
                    f'ExecutorID {job.executor_id} | JobID {job.job_id} - Putting remaining '
                    f'{len(callids_to_invoke_nondirect)} function activations into pending queue'
                )
                for call_ids_range in iterchunks(callids_to_invoke_nondirect, job.chunksize):
                    self.pending_calls_q.put((job, call_ids_range))
        else:
            logger.debug(
                f'ExecutorID {job.executor_id} | JobID {job.job_id} - Reached maximum {self.max_workers} '
                f'workers, queuing {job.total_calls} function activations'
            )
            for call_ids_range in iterchunks(range(job.total_calls), job.chunksize):
                self.pending_calls_q.put((job, call_ids_range))

    def run_job(self, job):
        """
        Run a job
        """
        futures = self._run_job(job)
        self.job_monitor.start(
            fs=futures,
            job_id=job.job_id,
            chunksize=job.chunksize,
            generate_tokens=True
        )

        return futures


def extend_runtime(job, compute_handler, internal_storage):
    """
    This method is used when runtime_include_function is active
    """

    base_docker_image = job.runtime_name
    uuid = job.ext_runtime_uuid
    ext_runtime_name = f'{base_docker_image.split(":")[0]}:{uuid}'

    # update job with new extended runtime name
    job.runtime_name = ext_runtime_name

    runtime_key = compute_handler.get_runtime_key(job.runtime_name, job.runtime_memory, __version__)
    runtime_meta = internal_storage.get_runtime_meta(runtime_key)

    if not runtime_meta:
        ext_docker_file = '/'.join([job.local_tmp_dir, "Dockerfile"])

        # Generate Dockerfile extended with function dependencies and function
        with open(ext_docker_file, 'w') as df:
            df.write('\n'.join([
                f'FROM {base_docker_image}',
                f'ENV PYTHONPATH={SA_INSTALL_DIR}/modules:$PYTHONPATH',
                f'COPY . {SA_INSTALL_DIR}'
            ]))

        # Build new extended runtime tagged by function hash
        cwd = os.getcwd()
        os.chdir(job.local_tmp_dir)
        compute_handler.build_runtime(ext_runtime_name, ext_docker_file)
        os.chdir(cwd)
        shutil.rmtree(job.local_tmp_dir, ignore_errors=True)

        runtime_meta = compute_handler.deploy_runtime(ext_runtime_name, job.runtime_memory, job.runtime_timeout)
        runtime_meta['runtime_timeout'] = job.runtime_timeout
        internal_storage.put_runtime_meta(runtime_key, runtime_meta)

    # Verify python version and lithops version
    if __version__ != runtime_meta['lithops_version']:
        raise Exception(
            f"Lithops version mismatch. Host version: {__version__} - "
            f"Runtime version: {runtime_meta['lithops_version']}"
        )

    py_local_version = version_str(sys.version_info)
    py_remote_version = runtime_meta['python_version']
    if py_local_version != py_remote_version:
        raise Exception(
            f"The runtime '{job.runtime_name}' uses Python {py_remote_version}, "
            f"which is incompatible with local Python {py_local_version}"
        )
