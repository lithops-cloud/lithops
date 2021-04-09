#
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
import logging
import multiprocessing as mp
from threading import Thread
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

from lithops.future import ResponseFuture
from lithops.config import extract_storage_config
from lithops.version import __version__ as lithops_version
from lithops.utils import version_str, is_lithops_worker, is_unix_system, iterchunks
from lithops.constants import LOGGER_LEVEL, LITHOPS_TEMP_DIR, LOGS_DIR, SERVERLESS
from lithops.util.metrics import PrometheusExporter

logger = logging.getLogger(__name__)


def create_invoker(config, executor_id, internal_storage,
                   compute_handler, job_monitor):
    """
    Creates the appropriate invoker based on the backend type
    """
    if compute_handler.get_backend_type() == 'batch':
        return BatchInvoker(config, executor_id, internal_storage,
                            compute_handler, job_monitor)
    else:
        if config[SERVERLESS].get('customized_runtime'):
            return CustomRuntimeFaaSInvoker(config, executor_id, internal_storage,
                                            compute_handler, job_monitor)
        else:
            return FaaSInvoker(config, executor_id, internal_storage,
                               compute_handler, job_monitor)


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

        self.workers = self.config['lithops'].get('workers')
        if self.workers:
            logger.debug('ExecutorID {} - Total available workers: {}'
                         .format(self.executor_id, self.workers))

        prom_enabled = self.config['lithops'].get('monitoring', False)
        prom_config = self.config.get('prometheus', {})
        self.prometheus = PrometheusExporter(prom_enabled, prom_config)

        self.mode = self.config['lithops']['mode']
        self.runtime_name = self.config[self.mode]['runtime']

    def select_runtime(self, job_id, runtime_memory):
        """
        Return the runtime metadata
        """
        runtime_memory = runtime_memory or self.config[self.mode].get('runtime_memory')
        runtime_timeout = self.config[self.mode].get('runtime_timeout')

        msg = ('ExecutorID {} | JobID {} - Selected Runtime: {} '
               .format(self.executor_id, job_id, self.runtime_name))
        msg = msg+'- {}MB'.format(runtime_memory) if runtime_memory else msg
        logger.info(msg)

        runtime_key = self.compute_handler.get_runtime_key(self.runtime_name, runtime_memory)
        runtime_meta = self.internal_storage.get_runtime_meta(runtime_key)

        if not runtime_meta:
            msg = 'Runtime {}'.format(self.runtime_name)
            msg = msg+' with {}MB' if runtime_memory else msg
            logger.info(msg+' is not yet installed')
            runtime_meta = self.compute_handler.create_runtime(self.runtime_name, runtime_memory, runtime_timeout)
            runtime_meta['runtime_timeout'] = runtime_timeout
            self.internal_storage.put_runtime_meta(runtime_key, runtime_meta)

        # Verify python version and lithops version
        if lithops_version != runtime_meta['lithops_version']:
            raise Exception("Lithops version mismatch. Host version: {} - Runtime version: {}"
                            .format(lithops_version, runtime_meta['lithops_version']))

        py_local_version = version_str(sys.version_info)
        py_remote_version = runtime_meta['python_version']
        if py_local_version != py_remote_version:
            raise Exception(("The indicated runtime '{}' is running Python {} and it "
                             "is not compatible with the local Python version {}")
                            .format(self.runtime_name, py_remote_version, py_local_version))

        return runtime_meta

    def _create_payload(self, job):
        """
        Creates the default pyload dictionary
        """
        payload = {'config': self.config,
                   'chunksize': job.chunksize,
                   'log_level': self.log_level,
                   'func_key': job.func_key,
                   'data_key': job.data_key,
                   'extra_env': job.extra_env,
                   'total_calls': job.total_calls,
                   'execution_timeout': job.execution_timeout,
                   'data_byte_ranges': job.data_byte_ranges,
                   'executor_id': job.executor_id,
                   'job_id': job.job_id,
                   'job_key': job.job_key,
                   'call_ids': None,
                   'monitoring': job.monitoring,
                   'host_submit_tstamp': time.time(),
                   'lithops_version': lithops_version,
                   'runtime_name': job.runtime_name,
                   'runtime_memory': job.runtime_memory,
                   'worker_processes': job.worker_processes}

        return payload

    def run_job(self, job):
        """
        Run a job
        """
        logger.info('ExecutorID {} | JobID {} - Starting function '
                    'invocation: {}() - Total: {} activations'
                    .format(job.executor_id, job.job_id,
                            job.function_name, job.total_calls))

        logger.debug('ExecutorID {} | JobID {} - Chunksize:'
                     ' {} - Worker processes: {}'
                     .format(job.executor_id, job.job_id,
                             job.chunksize, job.worker_processes))

        self.prometheus.send_metric(name='job_total_calls',
                                    value=job.total_calls,
                                    labels=(
                                        ('executor_id', job.executor_id),
                                        ('job_id', job.job_id),
                                        ('function_name', job.function_name)
                                    ))

        try:
            job.runtime_name = self.runtime_name
            self._invoke_job(job)
        except (KeyboardInterrupt, Exception) as e:
            self.stop()
            raise e

        log_file = os.path.join(LOGS_DIR, job.job_key+'.log')
        logger.info("ExecutorID {} | JobID {} - View execution logs at {}"
                    .format(job.executor_id, job.job_id, log_file))

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
    Module responsible to perform the invocations against the Standalone backend
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

        logger.debug('ExecutorID {} | JobID {} - Job invoked ({}s) - Activation ID: {}'
                     .format(job.executor_id, job.job_id, resp_time, activation_id or job.job_key))

    def run_job(self, job):
        """
        Run a job
        """
        futures = Invoker.run_job(self, job)
        self.job_monitor.start_job_monitoring(job, self.internal_storage)
        return futures


class FaaSInvoker(Invoker):
    """
    Module responsible to perform the invocations against the FaaS backends
    """

    REMOTE_INVOKER_MEMORY = 2048
    INVOKER_PROCESSES = 2

    def __init__(self, config, executor_id, internal_storage, compute_handler, job_monitor):
        super().__init__(config, executor_id, internal_storage, compute_handler, job_monitor)

        self.remote_invoker = self.config['serverless'].get('remote_invoker', False)
        self.use_threads = (self.is_lithops_worker
                            or not is_unix_system()
                            or mp.get_start_method() != 'fork')
        self.invokers = []
        self.ongoing_activations = 0

        if self.use_threads:
            self.pending_calls_q = queue.Queue()
            self.running_flag = SimpleNamespace(value=0)
            self.INVOKER = Thread
        else:
            self.pending_calls_q = mp.Queue()
            self.running_flag = mp.Value('i', 0)
            self.INVOKER = mp.Process

        self.token_bucket_q = self.job_monitor.token_bucket_q

        logger.debug('ExecutorID {} - Serverless invoker created'.format(self.executor_id))

    def _start_invoker_process(self):
        """Starts the invoker process responsible to spawn pending calls
        in background.
        """

        def invoker_process(inv_id):
            """Run process that implements token bucket scheduling approach"""
            logger.debug('ExecutorID {} - Invoker process {} started'
                         .format(self.executor_id, inv_id))

            with ThreadPoolExecutor(max_workers=250) as executor:
                while True:
                    try:
                        self.token_bucket_q.get()
                        job, call_id = self.pending_calls_q.get()
                    except KeyboardInterrupt:
                        break
                    if self.running_flag.value:
                        executor.submit(self._invoke_task, job, call_id)
                    else:
                        break

            logger.debug('ExecutorID {} - Invoker process {} finished'
                         .format(self.executor_id, inv_id))

        for inv_id in range(self.INVOKER_PROCESSES):
            p = self.INVOKER(target=invoker_process, args=(inv_id,))
            self.invokers.append(p)
            p.daemon = True
            p.start()

    def _invoke_task(self, job, call_ids_range):
        """Method used to perform the actual invocation against the
        compute backend.
        """
        # prepare payload
        call_ids = ["{:05d}".format(i) for i in call_ids_range]
        data_byte_ranges = [job.data_byte_ranges[int(call_id)] for call_id in call_ids]
        payload = self._create_payload(job)
        payload['call_ids'] = call_ids
        payload['data_byte_ranges'] = data_byte_ranges

        # do the invocation
        start = time.time()
        activation_id = self.compute_handler.invoke(payload)
        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        if not activation_id:
            # reached quota limit
            time.sleep(random.randint(0, 5))
            self.pending_calls_q.put((job, call_ids_range))
            self.token_bucket_q.put('#')
            return

        logger.debug('ExecutorID {} | JobID {} - Calls {} invoked ({}s) - Activation'
                     ' ID: {}'.format(job.executor_id, job.job_id, ', '.join(call_ids),
                                      resp_time, activation_id))

    def _invoke_job(self, job):
        """
        Normal Invocation
        Use local threads to perform all the function invocations
        """
        if self.running_flag.value == 0:
            self.running_workers = 0
            self.running_flag.value = 1
            self._start_invoker_process()

        if self.running_workers < self.workers:
            free_workers = self.workers - self.running_workers
            total_direct = free_workers * job.chunksize
            callids = range(job.total_calls)
            callids_to_invoke_direct = callids[:total_direct]
            callids_to_invoke_nondirect = callids[total_direct:]

            ci = len(callids_to_invoke_direct)
            cz = job.chunksize
            consumed_workers = ci // cz + (ci % cz > 0)
            self.running_workers += consumed_workers

            logger.debug('ExecutorID {} | JobID {} - Free workers:'
                         ' {} - Going to run {} activations in {} workers'
                         .format(job.executor_id, job.job_id, free_workers,
                                 len(callids_to_invoke_direct), consumed_workers))

            def _callback(future):
                future.result()

            executor = ThreadPoolExecutor(job.invoke_pool_threads)
            for call_ids_range in iterchunks(callids_to_invoke_direct, job.chunksize):
                future = executor.submit(self._invoke_task, job, call_ids_range)
                future.add_done_callback(_callback)

            # Put into the queue the rest of the callids to invoke within the process
            if callids_to_invoke_nondirect:
                logger.debug('ExecutorID {} | JobID {} - Putting remaining '
                             '{} function activations into pending queue'
                             .format(job.executor_id, job.job_id,
                                     len(callids_to_invoke_nondirect)))
                for call_ids_range in iterchunks(callids_to_invoke_nondirect, job.chunksize):
                    self.pending_calls_q.put((job, call_ids_range))
        else:
            logger.debug('ExecutorID {} | JobID {} - Reached maximun {} '
                         'workers, queuing {} function activations'
                         .format(job.executor_id, job.job_id,
                                 self.workers, job.total_calls))
            for call_ids_range in iterchunks(job.total_calls, job.chunksize):
                self.pending_calls_q.put((job, call_ids_range))

    def stop(self):
        """
        Stop the invoker process
        """
        if self.invokers:
            logger.debug('ExecutorID {} - Stopping invoker'
                         .format(self.executor_id))
            self.running_flag.value = 0

            for invoker in self.invokers:
                self.token_bucket_q.put('#')
                self.pending_calls_q.put((None, None))

            while not self.pending_calls_q.empty():
                try:
                    self.pending_calls_q.get(False)
                except Exception:
                    pass
            self.invokers = []

    def run_job(self, job):
        """
        Run a job
        """
        futures = Invoker.run_job(self, job)
        self.job_monitor.start_job_monitoring(job, self.internal_storage, generate_tokens=True)
        return futures


class CustomRuntimeFaaSInvoker(FaaSInvoker):
    """
    Module responsible to perform the invocations against the serverless
    backend in realtime environments.

    currently differs from ServerlessInvoker only by having one method that
    provides extension of specified environment with map function and modules
    to optimize performance in real time use cases by avoiding repeated data
    transfers from storage to  action containers on each execution
    """

    def run_job(self, job):
        """
        Extend runtime and run a job described in job_description
        """
        logger.warning("Warning, you are using customized runtime feature. "
                       "Please, notice that the map function code and dependencies "
                       "are stored and uploaded to docker registry. "
                       "To protect your privacy, use a private docker registry "
                       "instead of public docker hub.")
        self._extend_runtime(job)
        return FaaSInvoker.run_job(self, job)

    # If runtime not exists yet, build unique docker image and register runtime
    def _extend_runtime(self, job):
        runtime_memory = self.config['serverless']['runtime_memory']

        base_docker_image = self.runtime_name
        uuid = job.ext_runtime_uuid
        ext_runtime_name = "{}:{}".format(base_docker_image.split(":")[0], uuid)

        # update job with new extended runtime name
        self.runtime_name = ext_runtime_name

        runtime_key = self.compute_handler.get_runtime_key(self.runtime_name, runtime_memory)
        runtime_meta = self.internal_storage.get_runtime_meta(runtime_key)

        if not runtime_meta:
            runtime_timeout = self.config['serverless']['runtime_timeout']
            logger.debug('Creating runtime: {}, memory: {}MB'.format(ext_runtime_name, runtime_memory))

            runtime_temorary_directory = '/'.join([LITHOPS_TEMP_DIR, os.path.dirname(job.func_key)])
            modules_path = '/'.join([runtime_temorary_directory, 'modules'])

            ext_docker_file = '/'.join([runtime_temorary_directory, "Dockerfile"])

            # Generate Dockerfile extended with function dependencies and function
            with open(ext_docker_file, 'w') as df:
                df.write('\n'.join([
                    'FROM {}'.format(base_docker_image),
                    'ENV PYTHONPATH={}:${}'.format(modules_path, 'PYTHONPATH'),
                    # set python path to point to dependencies folder
                    'COPY . {}'.format(runtime_temorary_directory)
                ]))

            # Build new extended runtime tagged by function hash
            cwd = os.getcwd()
            os.chdir(runtime_temorary_directory)
            self.compute_handler.build_runtime(ext_runtime_name, ext_docker_file)
            os.chdir(cwd)

            runtime_meta = self.compute_handler.create_runtime(ext_runtime_name, runtime_memory, runtime_timeout)
            runtime_meta['runtime_timeout'] = runtime_timeout
            self.internal_storage.put_runtime_meta(runtime_key, runtime_meta)

        if lithops_version != runtime_meta['lithops_version']:
            raise Exception("Lithops version mismatch. Host version: {} - Runtime version: {}"
                            .format(lithops_version, runtime_meta['lithops_version']))

        py_local_version = version_str(sys.version_info)
        py_remote_version = runtime_meta['python_ver']

        if py_local_version != py_remote_version:
            raise Exception(("The indicated runtime '{}' is running Python {} and it "
                             "is not compatible with the local Python version {}")
                            .format(self.runtime_name, py_remote_version, py_local_version))

        return runtime_meta
