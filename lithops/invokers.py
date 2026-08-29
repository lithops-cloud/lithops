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
from math import ceil
from concurrent.futures import ThreadPoolExecutor

from lithops.future import ResponseFuture
from lithops.config import extract_storage_config
from lithops.version import __version__
from lithops.utils import (
    verify_runtime_name,
    version_str,
    is_lithops_worker,
    iterchunks,
    monitoring_queues,
    BackendType,
    log_prefix,
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


def create_invoker(
    config,
    executor_id,
    internal_storage,
    compute_handler,
    job_monitor,
):
    """
    Creates the appropriate invoker based on the backend type
    """
    invoker_cls = {
        BackendType.BATCH.value: BatchInvoker,
        BackendType.FAAS.value: FaaSInvoker,
    }.get(compute_handler.get_backend_type())
    if invoker_cls is None:
        return None
    return invoker_cls(
        config,
        executor_id,
        internal_storage,
        compute_handler,
        job_monitor,
    )


def _format_call_id(index: int) -> str:
    """
    Formats a call index as the fixed width call id the workers expect
    """
    return f'{index:05d}'


def _timed_invoke(compute_handler, payload):
    """
    Invokes the payload and returns the activation id together with how long
    the backend took to accept it, already formatted for the log
    """
    start = time.time()
    activation_id = compute_handler.invoke(payload)
    return activation_id, f'{round(time.time() - start, 3):.3f}'


def _raise_invoke_error(invoke_future) -> None:
    """
    Done callback of an invocation nobody waits for. Re-raising here makes
    concurrent.futures log the failure instead of dropping it silently
    """
    invoke_future.result()


def _verify_runtime_meta(runtime_meta, runtime_name):
    """
    Ensures the runtime runs the same Lithops and Python versions as this
    client, as it has to unpickle the function this client serializes
    """
    if __version__ != runtime_meta['lithops_version']:
        raise Exception(
            f"Lithops version mismatch. Host version: {__version__} - "
            f"Runtime version: {runtime_meta['lithops_version']}"
        )

    py_local_version = version_str(sys.version_info)
    py_remote_version = runtime_meta['python_version']
    if py_local_version != py_remote_version:
        raise Exception(
            f"The indicated runtime '{runtime_name}' is running Python "
            f"{py_remote_version} and it is not compatible with the local "
            f"Python version {py_local_version}"
        )


class Invoker:
    """
    Abstract invoker class
    """

    def __init__(
        self,
        config,
        executor_id,
        internal_storage,
        compute_handler,
        job_monitor,
    ):
        log_level = logger.getEffectiveLevel()
        self.log_active = log_level != logging.WARNING
        self.log_level = (
            LOGGER_LEVEL if not self.log_active else log_level
        )

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
        self.include_function = self.config[self.backend].get(
            'runtime_include_function', False
        )

        self.runtime_info = self.compute_handler.get_runtime_info()
        self.runtime_name = self.runtime_info['runtime_name']
        self.max_workers = self.runtime_info['max_workers']

        verify_runtime_name(self.runtime_name)

        logger.debug(
            f'{log_prefix(self.executor_id)} - Invoker initialized. Max workers: {self.max_workers}'
        )

    def _deploy_runtime(self, runtime_key, runtime_memory):
        """
        Deploys the selected runtime and caches its metadata, so that the
        next job that selects it finds it already deployed
        """
        msg = f'Runtime {self.runtime_name}'
        if runtime_memory:
            msg += f' with {runtime_memory}MB'
        logger.info(f'{msg} is not yet deployed')

        runtime_timeout = self.runtime_info['runtime_timeout']
        runtime_meta = self.compute_handler.deploy_runtime(
            self.runtime_name,
            runtime_memory,
            runtime_timeout,
        )
        runtime_meta['runtime_timeout'] = runtime_timeout
        self.internal_storage.put_runtime_meta(runtime_key, runtime_meta)
        return runtime_meta

    def select_runtime(self, job_id, runtime_memory):
        """
        Return the runtime metadata
        """
        default_memory = self.runtime_info['runtime_memory']
        runtime_memory = (
            runtime_memory or default_memory
            if self.mode == SERVERLESS
            else default_memory
        )

        msg = (
            f'{log_prefix(self.executor_id, job_id)} - '
            f'Selected Runtime: {self.runtime_name} '
        )
        if runtime_memory:
            msg += f'- {runtime_memory}MB'
        logger.info(msg)

        runtime_key = self.compute_handler.get_runtime_key(
            self.runtime_name, runtime_memory, __version__
        )
        runtime_meta = self.internal_storage.get_runtime_meta(
            runtime_key
        )

        if not runtime_meta:
            runtime_meta = self._deploy_runtime(runtime_key, runtime_memory)

        _verify_runtime_meta(runtime_meta, self.runtime_name)
        return runtime_meta

    def _create_payload(self, job):
        """
        Creates the default payload dictionary
        """
        return {
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
            'monitoring_queues': monitoring_queues(job.executor_id),
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

    def _send_job_metrics(self, job):
        """
        Reports the size of the job to Prometheus, if telemetry is enabled
        """
        labels = (
            ('job_id', job.job_key),
            ('function_name', job.function_name),
        )
        self.prometheus.send_metric(
            name='job_total_calls',
            value=job.total_calls,
            type='counter',
            labels=labels,
        )
        self.prometheus.send_metric(
            name='job_runtime_memory',
            value=job.runtime_memory or 0,
            type='counter',
            labels=labels,
        )

    def _build_futures(self, job):
        """
        Creates one future per call of the job, already marked as invoked
        """
        futures = []
        for i in range(job.total_calls):
            fut = ResponseFuture(
                _format_call_id(i),
                job,
                job.metadata.copy(),
                self.storage_config,
            )
            fut._set_state(ResponseFuture.State.Invoked)
            futures.append(fut)
        job.futures = futures
        return futures

    def _run_job(self, job):
        """
        Invokes a job through the backend specific _invoke_job() and returns
        its futures. Stops the invoker if the invocation fails halfway
        """
        prefix = log_prefix(job.executor_id, job.job_id)
        if self.include_function:
            logger.debug(
                f'{prefix} - Runtime include function feature is activated'
            )
            job.runtime_name = self.runtime_name
            extend_runtime(
                job, self.compute_handler, self.internal_storage
            )
            self.runtime_name = job.runtime_name

        logger.info(
            f'{prefix} - Starting function invocation: {job.function_name}() - Total: '
            f'{job.total_calls} activations'
        )

        self._send_job_metrics(job)

        if self.backend not in STANDALONE_BACKENDS:
            logger.debug(
                f'{prefix} - Worker processes: '
                f'{job.worker_processes} - Chunksize: {job.chunksize}'
            )

        try:
            job.runtime_name = self.runtime_name
            self._invoke_job(job)
        except (KeyboardInterrupt, Exception):
            self.stop()
            raise

        log_file = os.path.join(LOGS_DIR, job.job_key + '.log')
        logger.info(f'{prefix} - View execution logs at {log_file}')
        return self._build_futures(job)

    def stop(self, wait: bool = False):
        """
        Stop invoker-related processes
        """
        pass


class BatchInvoker(Invoker):
    """
    Module responsible to perform the invocations against a
    batch backend
    """

    def __init__(
        self,
        config,
        executor_id,
        internal_storage,
        compute_handler,
        job_monitor,
    ):
        super().__init__(
            config,
            executor_id,
            internal_storage,
            compute_handler,
            job_monitor,
        )
        self.compute_handler.init()

    def _invoke_job(self, job):
        """
        Invokes every call of the job in a single request, as a batch backend
        schedules the calls itself
        """
        payload = self._create_payload(job)
        payload['call_ids'] = [
            _format_call_id(i) for i in range(job.total_calls)
        ]

        activation_id, resp_time = _timed_invoke(
            self.compute_handler, payload
        )
        logger.debug(
            f'{log_prefix(job.executor_id, job.job_id)} - Job invoked '
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
    Module responsible to perform the invocations against a
    FaaS backend
    """
    ASYNC_INVOKERS = 2
    # Upper bound for the wait of stop(wait=True) on each async invoker
    STOP_TIMEOUT = 10

    def __init__(
        self,
        config,
        executor_id,
        internal_storage,
        compute_handler,
        job_monitor,
    ):
        super().__init__(
            config,
            executor_id,
            internal_storage,
            compute_handler,
            job_monitor,
        )

        remote_invoker = self.config[self.backend].get(
            'remote_invoker', False
        )
        self.remote_invoker = (
            remote_invoker if not is_lithops_worker() else False
        )

        self.invokers = []
        self.pending_calls_q = queue.Queue()
        self.should_run = False
        self.running_workers = 0
        self.sync = is_lithops_worker()

        self.invoke_pool_threads = self.config[self.backend][
            'invoke_pool_threads'
        ]
        self.executor = ThreadPoolExecutor(self.invoke_pool_threads)

        logger.debug(
            f'{log_prefix(self.executor_id)} - Serverless invoker created'
        )

    def _async_invoker_loop(self, inv_id):
        """
        Token bucket scheduling loop: spends one token, which the monitor
        puts for every worker that becomes free, on the next pending chunk
        of calls. Runs in a background thread until stop() is called
        """
        logger.debug(
            f'{log_prefix(self.executor_id)} - Async invoker {inv_id} started'
        )
        workers = min(64, self.invoke_pool_threads // 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while self.should_run:
                try:
                    self.job_monitor.token_bucket_q.get()
                    job, call_ids_range = self.pending_calls_q.get()
                except KeyboardInterrupt:
                    break
                if not self.should_run:
                    break
                pool.submit(self._invoke_task, job, call_ids_range)

        logger.debug(
            f'{log_prefix(self.executor_id)} - Async invoker {inv_id} finished'
        )

    def _start_async_invokers(self):
        """Starts the invoker process responsible to spawn
        pending calls in background.
        """
        for inv_id in range(self.ASYNC_INVOKERS):
            self.job_monitor.token_bucket_q.put('#')
            invoker = threading.Thread(
                target=self._async_invoker_loop, args=(inv_id,)
            )
            self.invokers.append(invoker)
            invoker.daemon = True
            invoker.start()

    def stop(self, wait: bool = False):
        """
        Stop async invokers. With wait, also waits for the threads to exit,
        which they only do once the invocations already in flight are done
        """
        if self.invokers:
            logger.debug(
                f'{log_prefix(self.executor_id)} - Stopping async invokers'
            )
            self.should_run = False

            while not self.pending_calls_q.empty():
                try:
                    self.pending_calls_q.get(block=False)
                except queue.Empty:
                    break

            # One sentinel per invoker, each one preceded by the token it
            # blocks on, so that every loop wakes up and sees should_run
            for _ in self.invokers:
                self.job_monitor.token_bucket_q.put('$')
                self.pending_calls_q.put((None, None))

            invokers, self.invokers = self.invokers, []

            if wait:
                # The loops leave their thread pool behind, and it only drains
                # the invocations already in flight once they exit, so callers
                # that cannot outlive that have to wait for it
                current_thread = threading.current_thread()
                for invoker in invokers:
                    if invoker is not current_thread:
                        invoker.join(timeout=self.STOP_TIMEOUT)

    def _invoke_task(self, job, call_ids_range):
        """
        Invokes one chunk of calls against the compute backend. A backend
        that refuses the invocation returns no activation id, in which case
        the chunk goes back to the pending queue with its token
        """
        payload = self._create_payload(job)
        call_ids = [_format_call_id(i) for i in call_ids_range]
        payload['call_ids'] = call_ids

        if job.data_key:
            payload['data_byte_ranges'] = [
                job.data_byte_ranges[int(call_id)]
                for call_id in call_ids
            ]
        else:
            del payload['data_byte_ranges']
            payload['data_byte_strs'] = [
                job.data_byte_strs[int(call_id)]
                for call_id in call_ids
            ]

        activation_id, resp_time = _timed_invoke(
            self.compute_handler, payload
        )

        if not activation_id:
            time.sleep(random.randint(0, 5))
            self.pending_calls_q.put((job, call_ids_range))
            self.job_monitor.token_bucket_q.put('#')
            return

        logger.debug(
            f'{log_prefix(job.executor_id, job.job_id)} - Calls {", ".join(call_ids)} '
            f'invoked ({resp_time}s) - Activation ID: {activation_id}'
        )

    def _invoke_job_remote(self, job):
        """
        Logic for invoking a job using a remote function
        """
        payload = {
            'config': self.config,
            'log_level': self.log_level,
            'runtime_name': job.runtime_name,
            'runtime_memory': job.runtime_memory,
            'remote_invoker': True,
            'job': job.__dict__,
        }
        activation_id, resp_time = _timed_invoke(
            self.compute_handler, payload
        )

        if activation_id:
            logger.debug(
                f'{log_prefix(job.executor_id, job.job_id)} - Remote invoker '
                f'call done ({resp_time}s) - Activation ID: {activation_id}'
            )
            return
        raise Exception('Unable to spawn remote invoker')

    def _drain_token_bucket(self):
        """
        Takes back the tokens left over by previous jobs, one per worker that
        already finished, so that this job can reuse those workers
        """
        if self.running_workers <= 0:
            return

        while not self.job_monitor.token_bucket_q.empty():
            try:
                self.job_monitor.token_bucket_q.get(block=False)
            except queue.Empty:
                break
            self.running_workers -= 1
            if self.running_workers == 0:
                break

    def _queue_call_ranges(self, job, call_ids):
        """
        Leaves the calls in the pending queue, in chunks of one worker each,
        for the async invokers to pick up as tokens become available
        """
        for call_ids_range in iterchunks(call_ids, job.chunksize):
            self.pending_calls_q.put((job, call_ids_range))

    def _invoke_direct(self, job, call_ids):
        """
        Invokes the given calls right away, one worker per chunk. Inside a
        worker there is no async invoker, so it waits for them to be invoked
        """
        invoke_futures = []
        for call_ids_range in iterchunks(call_ids, job.chunksize):
            invoke_future = self.executor.submit(
                self._invoke_task, job, call_ids_range
            )
            invoke_future.add_done_callback(_raise_invoke_error)
            invoke_futures.append(invoke_future)

        if self.sync:
            for invoke_future in invoke_futures:
                invoke_future.result()

    def _invoke_job(self, job):
        """
        Normal Invocation
        Use local threads to perform all the function invocations
        """
        self.compute_handler.pre_invoke(job)

        if self.remote_invoker:
            return self._invoke_job_remote(job)

        prefix = log_prefix(job.executor_id, job.job_id)

        if not self.should_run:
            self.running_workers = 0
            self.should_run = True
            self._start_async_invokers()

        self._drain_token_bucket()

        if self.running_workers >= self.max_workers:
            logger.debug(
                f'{prefix} - Reached maximum '
                f'{self.max_workers} workers, queuing {job.total_calls} '
                f'function activations'
            )
            self._queue_call_ranges(job, range(job.total_calls))
            return

        free_workers = self.max_workers - self.running_workers
        call_ids = range(job.total_calls)
        direct = call_ids[:free_workers * job.chunksize]
        queued = call_ids[free_workers * job.chunksize:]

        # One worker runs one chunk of calls, and the last one may be partial
        consumed_workers = ceil(len(direct) / job.chunksize)
        self.running_workers += consumed_workers

        logger.debug(
            f'{prefix} - Free workers: '
            f'{free_workers} - Going to run {len(direct)} '
            f'activations in {consumed_workers} workers'
        )
        self._invoke_direct(job, direct)

        if queued:
            logger.debug(
                f'{prefix} - Putting remaining '
                f'{len(queued)} function activations into pending queue'
            )
            self._queue_call_ranges(job, queued)

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


def _build_extended_runtime(job, compute_handler, base_docker_image):
    """
    Builds an image that adds the function and its modules on top of the base
    one. The build runs from the temporary directory holding them, as its
    contents are the build context, and it is removed afterwards
    """
    ext_docker_file = '/'.join([job.local_tmp_dir, "Dockerfile"])
    with open(ext_docker_file, 'w') as df:
        df.write('\n'.join([
            f'FROM {base_docker_image}',
            f'ENV PYTHONPATH={SA_INSTALL_DIR}/modules:$PYTHONPATH',
            f'COPY . {SA_INSTALL_DIR}'
        ]))

    cwd = os.getcwd()
    os.chdir(job.local_tmp_dir)
    try:
        compute_handler.build_runtime(job.runtime_name, ext_docker_file)
    finally:
        os.chdir(cwd)
    shutil.rmtree(job.local_tmp_dir, ignore_errors=True)


def extend_runtime(job, compute_handler, internal_storage):
    """
    Points the job to a runtime that bundles its function, building and
    deploying it if it does not exist yet. Used when the
    runtime_include_function config option is active
    """
    base_docker_image = job.runtime_name
    job.runtime_name = (
        f'{base_docker_image.split(":")[0]}:{job.ext_runtime_uuid}'
    )

    runtime_key = compute_handler.get_runtime_key(
        job.runtime_name, job.runtime_memory, __version__
    )
    runtime_meta = internal_storage.get_runtime_meta(runtime_key)

    if not runtime_meta:
        _build_extended_runtime(job, compute_handler, base_docker_image)
        runtime_meta = compute_handler.deploy_runtime(
            job.runtime_name,
            job.runtime_memory,
            job.runtime_timeout,
        )
        runtime_meta['runtime_timeout'] = job.runtime_timeout
        internal_storage.put_runtime_meta(runtime_key, runtime_meta)

    _verify_runtime_meta(runtime_meta, job.runtime_name)
