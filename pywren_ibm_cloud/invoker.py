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
import time
import logging
import random
from types import SimpleNamespace
from multiprocessing import Process, Queue
from threading import Thread
from pywren_ibm_cloud.compute import Compute
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.version import __version__
from concurrent.futures import ThreadPoolExecutor
from pywren_ibm_cloud.config import extract_storage_config, extract_compute_config
from pywren_ibm_cloud.future import ResponseFuture, CallState
from pywren_ibm_cloud.storage.utils import create_output_key, create_status_key

logger = logging.getLogger(__name__)


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

        self.compute_handlers = []
        cb = self.compute_config['backend']
        regions = self.compute_config[cb].get('region')
        if type(regions) == list:
            for region in regions:
                compute_config = self.compute_config.copy()
                compute_config[cb]['region'] = region
                self.compute_handlers.append(Compute(compute_config))
        else:
            self.compute_handlers.append(Compute(self.compute_config))

        self.jobs_queue = Queue()
        self.futures_queue = Queue()
        self.invoker_process = InvokerProcess(pywren_config, executor_id, self.jobs_queue, self.futures_queue)
        self.invoker_process.daemon = True
        self.invoker_process.start()

        self.jobs = {}
        self.fut_getter_thread = Thread(target=fut_getter_thread, args=(self.jobs, self.futures_queue))
        self.fut_getter_thread.daemon = True
        self.fut_getter_thread.start()

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

    def submit_job(self, job_description):
        # generate and return futures
        job = SimpleNamespace(**job_description)
        self.jobs[job.job_id] = {}
        futures = []
        for i in range(job.total_calls):
            call_id = "{:05d}".format(i)
            fut = ResponseFuture(call_id, job.job_id, self.executor_id, self.storage_config)
            fut._set_state(CallState.new)
            futures.append(fut)
            self.jobs[job.job_id][call_id] = fut

        self.jobs_queue.put(job_description)

        return futures


def fut_getter_thread(jobs, futures_queue):
    while True:
        job_id, call_id, fut = futures_queue.get()
        jobs[job_id][call_id].invoke_status = fut.invoke_status
        jobs[job_id][call_id].activation_id = fut.activation_id
        jobs[job_id][call_id]._set_state(CallState.invoked)


class InvokerProcess(Process):
    def __init__(self, pywren_config, executor_id, jobs_queue, futures_queue):
        super().__init__()
        self.log_level = os.getenv('PYWREN_LOGLEVEL')
        self.pywren_config = pywren_config
        self.executor_id = executor_id
        self.jobs_queue = jobs_queue
        self.futures_queue = futures_queue
        self.storage_config = extract_storage_config(self.pywren_config)
        self.compute_config = extract_compute_config(self.pywren_config)

        self.compute_handlers = []
        cb = self.compute_config['backend']
        regions = self.compute_config[cb].get('region')
        if type(regions) == list:
            for region in regions:
                compute_config = self.compute_config.copy()
                compute_config[cb]['region'] = region
                self.compute_handlers.append(Compute(compute_config))
        else:
            self.compute_handlers.append(Compute(self.compute_config))

        logger.debug('ExecutorID {} - Invoker process created'.format(self.executor_id))

    def run(self):
        """
        Run a job described in job_description
        """
        logger.debug('ExecutorID {} - Invoker process started'.format(self.executor_id))
        while True:
            job_description = self.jobs_queue.get()
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

            ########################

            def invoke(executor_id, job_id, call_id, func_key, invoke_metadata, data_key, data_byte_range):

                output_key = create_output_key(self.storage_config['prefix'], executor_id, job_id, call_id)
                status_key = create_status_key(self.storage_config['prefix'], executor_id, job_id, call_id)

                payload = {
                    'config': self.pywren_config,
                    'log_level': self.log_level,
                    'func_key': func_key,
                    'data_key': data_key,
                    'output_key': output_key,
                    'status_key': status_key,
                    'execution_timeout': job.execution_timeout,
                    'data_byte_range': data_byte_range,
                    'executor_id': executor_id,
                    'job_id': job_id,
                    'call_id': call_id,
                    'pywren_version': __version__}

                if job.extra_env is not None:
                    logger.debug("Extra environment vars {}".format(job.extra_env))
                    payload['extra_env'] = job.extra_env

                host_submit_time = time.time()
                payload['host_submit_time'] = host_submit_time
                # do the invocation
                compute_handler = random.choice(self.compute_handlers)
                activation_id = compute_handler.invoke(job.runtime_name, job.runtime_memory, payload)

                if not activation_id:
                    raise Exception("ExecutorID {} | JobID {} - Retrying mechanism finished with no success. "
                                    "Failed to invoke the job".format(executor_id, job_id))

                invoke_metadata['activation_id'] = activation_id
                invoke_metadata['invoke_time'] = time.time() - host_submit_time

                invoke_metadata.update(payload)
                del invoke_metadata['config']

                fut = ResponseFuture(call_id, job_id, executor_id, self.storage_config, activation_id, invoke_metadata)
                fut._set_state(CallState.invoked)
                self.futures_queue.put((job_id, call_id, fut))
                #return fut

            ########################

            call_futures = []
            with ThreadPoolExecutor(max_workers=job.invoke_pool_threads) as executor:
                for i in range(job.total_calls):
                    call_id = "{:05d}".format(i)
                    data_byte_range = job.data_ranges[i]
                    future = executor.submit(invoke, self.executor_id,
                                             job.job_id, call_id, job.func_key,
                                             job.host_job_meta.copy(),
                                             job.data_key, data_byte_range)
                    call_futures.append(future)

            #res = [ft.result() for ft in call_futures]

            #return res
