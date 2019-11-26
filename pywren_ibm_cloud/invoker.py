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
import time
import logging
import random
from types import SimpleNamespace
from threading import Thread
from multiprocessing import Process, Queue
from pywren_ibm_cloud.compute import Compute
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.version import __version__
from concurrent.futures import ThreadPoolExecutor
from pywren_ibm_cloud.config import extract_storage_config, extract_compute_config
from pywren_ibm_cloud.future import ResponseFuture
from pywren_ibm_cloud.storage.utils import create_output_key, create_status_key


logger = logging.getLogger(__name__)
MAX_DIRECT_INVOCATIONS = 1200


class FunctionInvoker:
    """
    Module responsible to perform the invocations against the compute backend
    """

    def __init__(self, pywren_config, executor_id, internal_storage):
        self.log_level = os.getenv('PYWREN_LOGLEVEL')
        self.pywren_config = pywren_config
        self.executor_id = executor_id
        self.storage_config = extract_storage_config(self.pywren_config)
        self.internal_storage = internal_storage
        self.compute_config = extract_compute_config(self.pywren_config)
        self.invoked = False

        self.compute_handlers = []
        cb = self.compute_config['backend']
        regions = self.compute_config[cb].get('region')
        if regions and type(regions) == list:
            for region in regions:
                compute_config = self.compute_config.copy()
                compute_config[cb]['region'] = region
                self.compute_handlers.append(Compute(compute_config))
        else:
            self.compute_handlers.append(Compute(self.compute_config))

        logger.debug('ExecutorID {} - Creating invoker process'.format(self.executor_id))

        self.token_bucket_queue = Queue()
        self.failed_calls_queue = Queue()
        self.invoker_process = Process(target=self.run_process, args=())
        self.invoker_process.daemon = True
        self.invoker_process.start()

    def select_runtime(self, job_id, runtime_memory):
        """
        Auxiliary method that selects the runtime to use. To do so it gets the
        runtime metadata from the storage. This metadata contains the preinstalled
        python modules needed to serialize the local function. If the .metadata
        file does not exists in the storage, this means that the runtime is not
        installed, so this method will proceed to install it.
        """
        log_level = os.getenv('PYWREN_LOGLEVEL')
        runtime_name = self.pywren_config['pywren']['runtime']
        if runtime_memory is None:
            runtime_memory = self.pywren_config['pywren']['runtime_memory']
        runtime_memory = int(runtime_memory)

        log_msg = ('ExecutorID {} | JobID {} - Selected Runtime: {} - {}MB'
                   .format(self.executor_id, job_id, runtime_name, runtime_memory))
        logger.info(log_msg)
        if not log_level:
            print(log_msg, end=' ')
        installing = False

        for compute_handler in self.compute_handlers:
            runtime_key = compute_handler.get_runtime_key(runtime_name, runtime_memory)
            runtime_deployed = True
            try:
                runtime_meta = self.internal_storage.get_runtime_meta(runtime_key)
            except Exception:
                runtime_deployed = False

            if not runtime_deployed:
                logger.debug('ExecutorID {} | JobID {} - Runtime {} with {}MB is not yet '
                             'installed'.format(self.executor_id, job_id, runtime_name, runtime_memory))
                if not log_level and not installing:
                    installing = True
                    print('(Installing...)')

                timeout = self.pywren_config['pywren']['runtime_timeout']
                logger.debug('Creating runtime: {}, memory: {}MB'.format(runtime_name, runtime_memory))
                runtime_meta = compute_handler.create_runtime(runtime_name, runtime_memory, timeout=timeout)
                self.internal_storage.put_runtime_meta(runtime_key, runtime_meta)

            py_local_version = version_str(sys.version_info)
            py_remote_version = runtime_meta['python_ver']

            if py_local_version != py_remote_version:
                raise Exception(("The indicated runtime '{}' is running Python {} and it "
                                 "is not compatible with the local Python version {}")
                                .format(runtime_name, py_remote_version, py_local_version))

        if not log_level and runtime_deployed:
            print()

        return runtime_meta

    def _invoke(self, job, call_id):
        """
        Method used to perform the actual invocation against the Compute Backend
        """
        storage_prefix = self.storage_config['prefix']
        output_key = create_output_key(storage_prefix, job.executor_id, job.job_id, call_id)
        status_key = create_status_key(storage_prefix, job.executor_id, job.job_id, call_id)

        payload = {'config': self.pywren_config,
                   'log_level': self.log_level,
                   'func_key': job.func_key,
                   'data_key': job.data_key,
                   'output_key': output_key,
                   'status_key': status_key,
                   'extra_env': job.extra_env,
                   'execution_timeout': job.execution_timeout,
                   'data_byte_range': job.data_ranges[int(call_id)],
                   'executor_id': job.executor_id,
                   'job_id': job.job_id,
                   'call_id': call_id,
                   'host_submit_time': time.time(),
                   'pywren_version': __version__}

        # do the invocation
        compute_handler = random.choice(self.compute_handlers)
        activation_id = compute_handler.invoke(job.runtime_name, job.runtime_memory, payload)

        if not activation_id:
            self.failed_calls_queue.put((job, call_id))
            return

        return call_id

    def run(self, job_description):
        """
        Run a job described in job_description
        """
        job = SimpleNamespace(**job_description)

        if job.remote_invocation:
            log_msg = ('ExecutorID {} | JobID {} - Starting {} remote invocation function: Spawning {}() '
                       '- Total: {} activations'.format(self.executor_id, job.job_id, job.total_calls,
                                                        job.func_name, job.original_total_calls))
        else:
            log_msg = ('ExecutorID {} | JobID {} - Starting function invocation: {}()  - Total: {} '
                       'activations'.format(self.executor_id, job.job_id, job.func_name, job.total_calls))
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

        if not self.invoked:
            # Only invoke MAX_DIRECT_INVOCATIONS
            callids = range(job.total_calls)
            callids_to_invoke_direct = callids[:MAX_DIRECT_INVOCATIONS]
            callids_to_invoke_nondirect = callids[MAX_DIRECT_INVOCATIONS:]

            call_futures = []
            with ThreadPoolExecutor(max_workers=job.invoke_pool_threads) as executor:
                for i in callids_to_invoke_direct:
                    call_id = "{:05d}".format(i)
                    future = executor.submit(self._invoke, job, call_id)
                    call_futures.append(future)

            # Block until all direct invocations have finished
            callids_invoked = [ft.result() for ft in call_futures]

            # Put into the queue the rest of the callids to invoke within the process
            for i in callids_to_invoke_nondirect:
                call_id = "{:05d}".format(i)
                self.failed_calls_queue.put((job, call_id))

            if self.failed_calls_queue.qsize() > 0:
                self.start_job_status_checker(job)
            self.invoked = True
        else:
            # Second and subsequent jobs will go all directly to the InvokerProcess
            for i in range(job.total_calls):
                call_id = "{:05d}".format(i)
                self.failed_calls_queue.put((job, call_id))
            self.start_job_status_checker(job)

        # Create all futures an return them
        futures = []
        for i in range(job.total_calls):
            call_id = "{:05d}".format(i)
            fut = ResponseFuture(self.executor_id, job.job_id, call_id, self.storage_config, job.metadata)
            fut._set_state(ResponseFuture.State.Invoked)
            futures.append(fut)

        return futures

    def start_job_status_checker(self, job):
        th = Thread(target=self._job_status_checker_worker, args=(job,))
        th.daemon = True
        th.start()

    def _job_status_checker_worker(self, job):
        logger.debug('ExecutorID {} | JobID {} - Starting job status checker worker'.format(self.executor_id, job.job_id))
        total_callids_done_in_job = 0

        while total_callids_done_in_job < job.total_calls:
            callids_done_in_job = set(self.internal_storage.get_job_status(self.executor_id, job.job_id))
            total_new_tokens = len(callids_done_in_job) - total_callids_done_in_job
            total_callids_done_in_job = total_callids_done_in_job + total_new_tokens
            for i in range(total_new_tokens):
                self.token_bucket_queue.put('#')
            time.sleep(0.1)

    def run_process(self):
        """
        Run process that implements token bucket scheduling approach
        """
        logger.debug('ExecutorID {} - Invoker process started'.format(self.executor_id))

        executor = ThreadPoolExecutor(max_workers=500)

        while True:
            try:
                token = self.token_bucket_queue.get(timeout=0.5)
            except Exception:
                pass
            job, call_id = self.failed_calls_queue.get()
            executor.submit(self._invoke, job, call_id)
