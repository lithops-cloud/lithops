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
import pika
import time
import logging
import random
from threading import Thread
from types import SimpleNamespace
from multiprocessing import Process, Queue, Value
from concurrent.futures import ThreadPoolExecutor
from lithops.compute import Compute
from lithops.version import __version__
from lithops.future import ResponseFuture
from lithops.config import extract_storage_config, extract_compute_config
from lithops.utils import version_str, is_lithops_function, is_unix_system


logger = logging.getLogger(__name__)

REMOTE_INVOKER_MEMORY = 2048
INVOKER_PROCESSES = 2


class FunctionInvoker:
    """
    Module responsible to perform the invocations against the compute backend
    """

    def __init__(self, config, executor_id, internal_storage):
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.config = config
        self.executor_id = executor_id
        self.storage_config = extract_storage_config(self.config)
        self.internal_storage = internal_storage
        self.compute_config = extract_compute_config(self.config)
        self.is_lithops_function = is_lithops_function()
        self.invokers = []

        self.remote_invoker = self.config['lithops'].get('remote_invoker', False)
        self.workers = self.config['lithops'].get('workers')
        logger.debug('ExecutorID {} - Total available workers: {}'
                     .format(self.executor_id, self.workers))

        self.compute_handlers = []
        cb = self.compute_config['backend']
        regions = self.compute_config[cb].get('region')
        if regions and type(regions) == list:
            for region in regions:
                compute_config = self.compute_config.copy()
                compute_config[cb]['region'] = region
                compute_handler = Compute(compute_config, self.storage_config)
                self.compute_handlers.append(compute_handler)
        else:
            compute_handler = Compute(self.compute_config, self.storage_config)
            self.compute_handlers.append(compute_handler)

        logger.debug('ExecutorID {} - Creating function invoker'.format(self.executor_id))

        self.token_bucket_q = Queue()
        self.pending_calls_q = Queue()
        self.running_flag = Value('i', 0)
        self.ongoing_activations = 0

        self.job_monitor = JobMonitor(self.config, self.internal_storage, self.token_bucket_q)

    def dismantle(self):
        for compute_handler in self.compute_handlers:
            compute_handler.dismantle()

    def select_runtime(self, job_id, runtime_memory):
        """
        Auxiliary method that selects the runtime to use. To do so it gets the
        runtime metadata from the storage. This metadata contains the preinstalled
        python modules needed to serialize the local function. If the .metadata
        file does not exists in the storage, this means that the runtime is not
        installed, so this method will proceed to install it.
        """
        runtime_name = self.config['lithops']['runtime']
        if runtime_memory is None:
            runtime_memory = self.config['lithops']['runtime_memory']

        if runtime_memory:
            runtime_memory = int(runtime_memory)
            log_msg = ('ExecutorID {} | JobID {} - Selected Runtime: {} - {}MB'
                       .format(self.executor_id, job_id, runtime_name, runtime_memory))
        else:
            log_msg = ('ExecutorID {} | JobID {} - Selected Runtime: {}'
                       .format(self.executor_id, job_id, runtime_name))
        logger.info(log_msg)
        if not self.log_active:
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
                if not self.log_active and not installing:
                    installing = True
                    print('(Installing runtime {}...)'.format(runtime_key))

                timeout = self.config['lithops']['runtime_timeout']
                logger.debug('Creating runtime: {}, memory: {}MB'.format(runtime_name, runtime_memory))
                runtime_meta = compute_handler.create_runtime(runtime_name, runtime_memory, timeout=timeout)
                self.internal_storage.put_runtime_meta(runtime_key, runtime_meta)

            py_local_version = version_str(sys.version_info)
            py_remote_version = runtime_meta['python_ver']

            if py_local_version != py_remote_version:
                raise Exception(("The indicated runtime '{}' is running Python {} and it "
                                 "is not compatible with the local Python version {}")
                                .format(runtime_name, py_remote_version, py_local_version))

        if not self.log_active and runtime_deployed:
            print()

        return runtime_meta

    def _start_invoker_process(self):
        """
        Starts the invoker process responsible to spawn pending calls in background
        """
        if self.is_lithops_function or not is_unix_system():
            for inv_id in range(INVOKER_PROCESSES):
                p = Thread(target=self._run_invoker_process, args=(inv_id, ))
                self.invokers.append(p)
                p.daemon = True
                p.start()
        else:
            for inv_id in range(INVOKER_PROCESSES):
                p = Process(target=self._run_invoker_process, args=(inv_id, ))
                self.invokers.append(p)
                p.daemon = True
                p.start()

    def _run_invoker_process(self, inv_id):
        """
        Run process that implements token bucket scheduling approach
        """
        logger.debug('ExecutorID {} - Invoker process {} started'.format(self.executor_id, inv_id))

        with ThreadPoolExecutor(max_workers=250) as executor:
            while True:
                try:
                    self.token_bucket_q.get()
                    job, call_id = self.pending_calls_q.get()
                except KeyboardInterrupt:
                    break
                if self.running_flag.value:
                    executor.submit(self._invoke, job, call_id)
                else:
                    break

        logger.debug('ExecutorID {} - Invoker process {} finished'.format(self.executor_id, inv_id))

    def stop(self):
        """
        Stop the invoker process
        """
        if self.invokers:
            logger.debug('ExecutorID {} - Stopping invoker'.format(self.executor_id))
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

    def _invoke(self, job, call_id):
        """
        Method used to perform the actual invocation against the Compute Backend
        """
        payload = {'config': self.config,
                   'log_level': logging.getLevelName(logger.getEffectiveLevel()),
                   'func_key': job.func_key,
                   'data_key': job.data_key,
                   'extra_env': job.extra_env,
                   'execution_timeout': job.execution_timeout,
                   'data_byte_range': job.data_ranges[int(call_id)],
                   'executor_id': job.executor_id,
                   'job_id': job.job_id,
                   'call_id': call_id,
                   'host_submit_tstamp': time.time(),
                   'lithops_version': __version__,
                   'runtime_name': job.runtime_name,
                   'runtime_memory': job.runtime_memory}

        # do the invocation
        start = time.time()
        compute_handler = random.choice(self.compute_handlers)
        activation_id = compute_handler.invoke(job.runtime_name, job.runtime_memory, payload)
        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        if not activation_id:
            # reached quota limit
            time.sleep(random.randint(0, 5))
            self.pending_calls_q.put((job, call_id))
            self.token_bucket_q.put('#')
            return

        logger.info('ExecutorID {} | JobID {} - Function call {} done! ({}s) - Activation'
                    ' ID: {}'.format(job.executor_id, job.job_id, call_id, resp_time, activation_id))

        return call_id

    def _invoke_remote(self, job_description):
        """
        Method used to send a job_description to the remote invoker
        """
        start = time.time()
        compute_handler = random.choice(self.compute_handlers)
        job = SimpleNamespace(**job_description)

        payload = {'config': self.config,
                   'log_level': logging.getLevelName(logger.getEffectiveLevel()),
                   'executor_id': job.executor_id,
                   'job_id': job.job_id,
                   'job_description': job_description,
                   'remote_invoker': True,
                   'invokers': 4,
                   'lithops_version': __version__}

        activation_id = compute_handler.invoke(job.runtime_name, REMOTE_INVOKER_MEMORY, payload)
        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        if activation_id:
            logger.info('ExecutorID {} | JobID {} - Remote invoker call done! ({}s) - Activation'
                        ' ID: {}'.format(job.executor_id, job.job_id, resp_time, activation_id))
        else:
            raise Exception('Unable to spawn remote invoker')

    def run(self, job_description):
        """
        Run a job described in job_description
        """
        job = SimpleNamespace(**job_description)

        try:
            while True:
                self.token_bucket_q.get_nowait()
                self.ongoing_activations -= 1
        except Exception:
            pass

        if self.remote_invoker:
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            self.select_runtime(job.job_id, REMOTE_INVOKER_MEMORY)
            sys.stdout = old_stdout
            log_msg = ('ExecutorID {} | JobID {} - Starting remote function invocation: {}() '
                       '- Total: {} activations'.format(job.executor_id, job.job_id,
                                                        job.function_name, job.total_calls))
            logger.info(log_msg)
            if not self.log_active:
                print(log_msg)

            th = Thread(target=self._invoke_remote, args=(job_description,))
            th.daemon = True
            th.start()
            time.sleep(0.1)

        else:
            try:
                if self.running_flag.value == 0:
                    self.ongoing_activations = 0
                    self.running_flag.value = 1
                    self._start_invoker_process()

                log_msg = ('ExecutorID {} | JobID {} - Starting function invocation: {}()  - Total: {} '
                           'activations'.format(job.executor_id, job.job_id, job.function_name, job.total_calls))
                logger.info(log_msg)
                if not self.log_active:
                    print(log_msg)

                if self.ongoing_activations < self.workers:
                    callids = range(job.total_calls)
                    total_direct = self.workers-self.ongoing_activations
                    callids_to_invoke_direct = callids[:total_direct]
                    callids_to_invoke_nondirect = callids[total_direct:]

                    self.ongoing_activations += len(callids_to_invoke_direct)

                    logger.debug('ExecutorID {} | JobID {} - Free workers: {} - Going to invoke {} function activations'
                                 .format(job.executor_id,  job.job_id, total_direct, len(callids_to_invoke_direct)))

                    call_futures = []

                    executor = ThreadPoolExecutor(max_workers=job.invoke_pool_threads)
                    for i in callids_to_invoke_direct:
                        call_id = "{:05d}".format(i)
                        future = executor.submit(self._invoke, job, call_id)
                        call_futures.append(future)
                    time.sleep(0.1)

                    # Put into the queue the rest of the callids to invoke within the process
                    if callids_to_invoke_nondirect:
                        logger.debug('ExecutorID {} | JobID {} - Putting remaining {} function invocations into pending queue'
                                     .format(job.executor_id, job.job_id, len(callids_to_invoke_nondirect)))
                        for i in callids_to_invoke_nondirect:
                            call_id = "{:05d}".format(i)
                            self.pending_calls_q.put((job, call_id))
                else:
                    logger.debug('ExecutorID {} | JobID {} - Ongoing activations reached {} workers, '
                                 'putting {} function invocations into pending queue'
                                 .format(job.executor_id, job.job_id, self.workers, job.total_calls))
                    for i in range(job.total_calls):
                        call_id = "{:05d}".format(i)
                        self.pending_calls_q.put((job, call_id))

                self.job_monitor.start_job_monitoring(job)

            except (KeyboardInterrupt, Exception) as e:
                self.stop()
                raise e

        # Create all futures
        futures = []
        for i in range(job.total_calls):
            call_id = "{:05d}".format(i)
            fut = ResponseFuture(call_id, job_description, job.metadata.copy(), self.storage_config)
            fut._set_state(ResponseFuture.State.Invoked)
            futures.append(fut)

        return futures

    def cleanup(self, activation_id):
        compute_handler = random.choice(self.compute_handlers)
        compute_handler.cleanup(activation_id)

class JobMonitor:

    def __init__(self, lithops_config, internal_storage, token_bucket_q):
        self.config = lithops_config
        self.internal_storage = internal_storage
        self.token_bucket_q = token_bucket_q
        self.is_lithops_function = is_lithops_function()
        self.monitors = []

        self.rabbitmq_monitor = self.config['lithops'].get('rabbitmq_monitor', False)
        if self.rabbitmq_monitor:
            self.rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')

    def get_active_jobs(self):
        active_jobs = 0
        for job_monitor_th in self.monitors:
            if job_monitor_th.is_alive():
                active_jobs += 1
        return active_jobs

    def start_job_monitoring(self, job):
        logger.debug('ExecutorID {} | JobID {} - Starting job monitoring'.format(job.executor_id, job.job_id))
        if self.rabbitmq_monitor:
            th = Thread(target=self._job_monitoring_rabbitmq, args=(job,))
        else:
            th = Thread(target=self._job_monitoring_os, args=(job,))
        if not self.is_lithops_function:
            th.daemon = True
        th.start()

        self.monitors.append(th)

    def _job_monitoring_os(self, job):
        total_callids_done_in_job = 0
        time.sleep(1)

        while total_callids_done_in_job < job.total_calls:
            callids_running_in_job, callids_done_in_job = self.internal_storage.get_job_status(job.executor_id, job.job_id)
            total_new_tokens = len(callids_done_in_job) - total_callids_done_in_job
            total_callids_done_in_job = total_callids_done_in_job + total_new_tokens
            for i in range(total_new_tokens):
                self.token_bucket_q.put('#')
            time.sleep(0.3)

    def _job_monitoring_rabbitmq(self, job):
        total_callids_done_in_job = 0

        exchange = 'lithops-{}-{}'.format(job.executor_id, job.job_id)
        queue_1 = '{}-1'.format(exchange)

        params = pika.URLParameters(self.rabbit_amqp_url)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()

        def callback(ch, method, properties, body):
            nonlocal total_callids_done_in_job
            call_status = json.loads(body.decode("utf-8"))
            if call_status['type'] == '__end__':
                self.token_bucket_q.put('#')
                total_callids_done_in_job += 1
            if total_callids_done_in_job == job.total_calls:
                ch.stop_consuming()

        channel.basic_consume(callback, queue=queue_1, no_ack=True)
        channel.start_consuming()
