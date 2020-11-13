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
import json
import pika
import time
import random
import queue
import logging
import multiprocessing as mp
from threading import Thread
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from lithops.version import __version__
from lithops.future import ResponseFuture
from lithops.config import extract_storage_config
from lithops.utils import version_str, is_lithops_worker, is_unix_system
from lithops.storage.utils import create_job_key
from lithops.constants import LOGGER_LEVEL

logger = logging.getLogger(__name__)


class Invoker:
    """
    Abstract invoker class
    """
    def __init__(self, config, executor_id, internal_storage, compute_handler):

        log_level = logger.getEffectiveLevel()
        self.log_active = log_level != logging.WARNING
        self.log_level = LOGGER_LEVEL if not self.log_active else log_level

        self.config = config
        self.executor_id = executor_id
        self.storage_config = extract_storage_config(self.config)
        self.internal_storage = internal_storage
        self.compute_handler = compute_handler
        self.is_lithops_worker = is_lithops_worker()

        self.workers = self.config['lithops'].get('workers')
        logger.debug('ExecutorID {} - Total available workers: {}'
                     .format(self.executor_id, self.workers))

        mode = self.config['lithops']['mode']
        self.runtime_name = self.config[mode]['runtime']

    def select_runtime(self, job_id, runtime_memory):
        """
        Create a runtime and return metadata
        """
        raise NotImplementedError

    def run(self, job):
        """
        Run a job
        """
        raise NotImplementedError

    def stop(self):
        """
        Stop invoker-related processes
        """
        pass


class StandaloneInvoker(Invoker):
    """
    Module responsible to perform the invocations against the Standalone backend
    """
    def __init__(self, config, executor_id, internal_storage, compute_handler):
        super().__init__(config, executor_id, internal_storage, compute_handler)

    def select_runtime(self, job_id, runtime_memory):
        """
        Return the runtime metadata
        """
        log_msg = ('ExecutorID {} | JobID {} - Selected Runtime: {} '
                   .format(self.executor_id, job_id, self.runtime_name))
        logger.info(log_msg)
        if not self.log_active:
            print(log_msg, end='')

        runtime_key = self.compute_handler.get_runtime_key(self.runtime_name)
        runtime_meta = self.internal_storage.get_runtime_meta(runtime_key)
        if not runtime_meta:
            logger.debug('Runtime {} is not yet installed'.format(self.runtime_name))
            if not self.log_active:
                print('(Installing...)')
            runtime_meta = self.compute_handler.create_runtime(self.runtime_name)
            self.internal_storage.put_runtime_meta(runtime_key, runtime_meta)
        else:
            if not self.log_active:
                print()

        py_local_version = version_str(sys.version_info)
        py_remote_version = runtime_meta['python_ver']

        if py_local_version != py_remote_version:
            raise Exception(("The indicated runtime '{}' is running Python {} and it "
                             "is not compatible with the local Python version {}")
                            .format(self.runtime_name, py_remote_version, py_local_version))

        return runtime_meta

    def run(self, job):
        """
        Run a job
        """
        job.runtime_name = self.runtime_name

        payload = {'config': self.config,
                   'log_level': self.log_level,
                   'executor_id': job.executor_id,
                   'job_id': job.job_id,
                   'job_description': job.__dict__,
                   'lithops_version': __version__}

        self.compute_handler.run_job(payload)

        log_msg = ('ExecutorID {} | JobID {} - {}() Invocation done - Total: {} activations'
                   .format(job.executor_id, job.job_id, job.function_name, job.total_calls))
        logger.info(log_msg)
        if not self.log_active:
            print(log_msg)

        futures = []
        for i in range(job.total_calls):
            call_id = "{:05d}".format(i)
            fut = ResponseFuture(call_id, job,
                                 job.metadata.copy(),
                                 self.storage_config)
            fut._set_state(ResponseFuture.State.Invoked)
            futures.append(fut)

        return futures


class ServerlessInvoker(Invoker):
    """
    Module responsible to perform the invocations against the serverless backend
    """

    REMOTE_INVOKER_MEMORY = 2048
    INVOKER_PROCESSES = 2

    def __init__(self, config, executor_id, internal_storage, compute_handler):
        super().__init__(config, executor_id, internal_storage, compute_handler)

        self.remote_invoker = self.config['serverless'].get('remote_invoker', False)
        self.use_threads = (self.is_lithops_worker
                            or not is_unix_system()
                            or mp.get_start_method() != 'fork')
        self.invokers = []
        self.ongoing_activations = 0

        if self.use_threads:
            self.token_bucket_q = queue.Queue()
            self.pending_calls_q = queue.Queue()
            self.running_flag = SimpleNamespace(value=0)
            self.INVOKER = Thread
        else:
            self.token_bucket_q = mp.Queue()
            self.pending_calls_q = mp.Queue()
            self.running_flag = mp.Value('i', 0)
            self.INVOKER = mp.Process

        self.job_monitor = JobMonitor(self.config, self.internal_storage, self.token_bucket_q)

        logger.debug('ExecutorID {} - Serverless invoker created'.format(self.executor_id))

    def select_runtime(self, job_id, runtime_memory):
        """
        Return the runtime metadata
        """
        if not runtime_memory:
            runtime_memory = self.config['serverless']['runtime_memory']
        timeout = self.config['serverless']['runtime_timeout']

        log_msg = ('ExecutorID {} | JobID {} - Selected Runtime: {} - {}MB '
                   .format(self.executor_id, job_id, self.runtime_name, runtime_memory))
        logger.info(log_msg)
        if not self.log_active:
            print(log_msg, end='')

        runtime_key = self.compute_handler.get_runtime_key(self.runtime_name, runtime_memory)
        runtime_meta = self.internal_storage.get_runtime_meta(runtime_key)
        if not runtime_meta:
            logger.debug('Runtime {} with {}MB is not yet installed'.format(self.runtime_name, runtime_memory))
            if not self.log_active:
                print('(Installing...)')
            runtime_meta = self.compute_handler.create_runtime(self.runtime_name, runtime_memory, timeout)
            self.internal_storage.put_runtime_meta(runtime_key, runtime_meta)
        else:
            if not self.log_active:
                print()

        py_local_version = version_str(sys.version_info)
        py_remote_version = runtime_meta['python_ver']

        if py_local_version != py_remote_version:
            raise Exception(("The indicated runtime '{}' is running Python {} and it "
                             "is not compatible with the local Python version {}")
                            .format(self.runtime_name, py_remote_version, py_local_version))

        return runtime_meta

    def _start_invoker_process(self):
        """Starts the invoker process responsible to spawn pending calls
        in background.
        """
        for inv_id in range(self.INVOKER_PROCESSES):
            p = self.INVOKER(target=self._run_invoker_process, args=(inv_id, ))
            self.invokers.append(p)
            p.daemon = True
            p.start()

    def _run_invoker_process(self, inv_id):
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
                    executor.submit(self._invoke, job, call_id)
                else:
                    break

        logger.debug('ExecutorID {} - Invoker process {} finished'
                     .format(self.executor_id, inv_id))

    def _invoke(self, job, call_id):
        """Method used to perform the actual invocation against the
        compute backend.
        """
        payload = {'config': self.config,
                   'log_level': self.log_level,
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
        activation_id = self.compute_handler.invoke(job.runtime_name, job.runtime_memory, payload)
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

    def _invoke_remote(self, job):
        """Method used to send a job_description to the remote invoker."""
        start = time.time()

        payload = {'config': self.config,
                   'log_level': self.log_level,
                   'executor_id': job.executor_id,
                   'job_id': job.job_id,
                   'job_description': job.__dict__,
                   'remote_invoker': True,
                   'invokers': 4,
                   'lithops_version': __version__}

        activation_id = self.compute_handler.invoke(job.runtime_name, self.REMOTE_INVOKER_MEMORY, payload)
        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        if activation_id:
            logger.info('ExecutorID {} | JobID {} - Remote invoker call done! ({}s) - Activation'
                        ' ID: {}'.format(job.executor_id, job.job_id, resp_time, activation_id))
        else:
            raise Exception('Unable to spawn remote invoker')

    def run(self, job):
        """
        Run a job described in job_description
        """

        job.runtime_name = self.runtime_name

        try:
            while True:
                self.token_bucket_q.get_nowait()
                self.ongoing_activations -= 1
        except Exception:
            pass

        if self.remote_invoker:
            """
            Remote Invocation
            Use a single cloud function to perform all the function invocations
            """
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            self.select_runtime(job.job_id, self.REMOTE_INVOKER_MEMORY)
            sys.stdout = old_stdout
            log_msg = ('ExecutorID {} | JobID {} - Starting remote function '
                       'invocation: {}() - Total: {} activations'
                       .format(job.executor_id, job.job_id,
                               job.function_name, job.total_calls))
            logger.info(log_msg)
            if not self.log_active:
                print(log_msg)

            th = Thread(target=self._invoke_remote, args=(job,), daemon=True)
            th.start()
            time.sleep(0.1)
        else:
            """
            Normal Invocation
            Use local threads to perform all the function invocations
            """
            try:
                if self.running_flag.value == 0:
                    self.ongoing_activations = 0
                    self.running_flag.value = 1
                    self._start_invoker_process()

                log_msg = ('ExecutorID {} | JobID {} - Starting function '
                           'invocation: {}() - Total: {} activations'
                           .format(job.executor_id, job.job_id,
                                   job.function_name, job.total_calls))
                logger.info(log_msg)
                if not self.log_active:
                    print(log_msg)

                if self.ongoing_activations < self.workers:
                    callids = range(job.total_calls)
                    total_direct = self.workers-self.ongoing_activations
                    callids_to_invoke_direct = callids[:total_direct]
                    callids_to_invoke_nondirect = callids[total_direct:]

                    self.ongoing_activations += len(callids_to_invoke_direct)

                    logger.debug('ExecutorID {} | JobID {} - Free workers: '
                                 '{} - Going to invoke {} function activations'
                                 .format(job.executor_id,  job.job_id, total_direct,
                                         len(callids_to_invoke_direct)))

                    def _callback(future):
                        future.result()

                    executor = ThreadPoolExecutor(job.invoke_pool_threads)
                    for i in callids_to_invoke_direct:
                        call_id = "{:05d}".format(i)
                        future = executor.submit(self._invoke, job, call_id)
                        future.add_done_callback(_callback)
                    time.sleep(0.1)

                    # Put into the queue the rest of the callids to invoke within the process
                    if callids_to_invoke_nondirect:
                        logger.debug('ExecutorID {} | JobID {} - Putting remaining '
                                     '{} function invocations into pending queue'
                                     .format(job.executor_id, job.job_id,
                                             len(callids_to_invoke_nondirect)))
                        for i in callids_to_invoke_nondirect:
                            call_id = "{:05d}".format(i)
                            self.pending_calls_q.put((job, call_id))
                else:
                    logger.debug('ExecutorID {} | JobID {} - Ongoing activations '
                                 'reached {} workers, queuing {} function invocations'
                                 .format(job.executor_id, job.job_id, self.workers,
                                         job.total_calls))
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
            fut = ResponseFuture(call_id, job,
                                 job.metadata.copy(),
                                 self.storage_config)
            fut._set_state(ResponseFuture.State.Invoked)
            futures.append(fut)

        return futures

    def stop(self):
        """
        Stop the invoker process and JobMonitor
        """

        self.job_monitor.stop()

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


class JobMonitor:

    def __init__(self, lithops_config, internal_storage, token_bucket_q):
        self.config = lithops_config
        self.internal_storage = internal_storage
        self.token_bucket_q = token_bucket_q
        self.is_lithops_worker = is_lithops_worker()
        self.monitors = {}

        self.rabbitmq_monitor = self.config['lithops'].get('rabbitmq_monitor', False)
        if self.rabbitmq_monitor:
            self.rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')

    def stop(self):
        for job_key in self.monitors:
            self.monitors[job_key]['should_run'] = False

    def get_active_jobs(self):
        active_jobs = 0
        for job_key in self.monitors:
            if self.monitors[job_key]['thread'].is_alive():
                active_jobs += 1
        return active_jobs

    def start_job_monitoring(self, job):
        logger.debug('ExecutorID {} | JobID {} - Starting job monitoring'
                     .format(job.executor_id, job.job_id))
        if self.rabbitmq_monitor:
            th = Thread(target=self._job_monitoring_rabbitmq, args=(job,))
        else:
            th = Thread(target=self._job_monitoring_os, args=(job,))

        if not self.is_lithops_worker:
            th.daemon = True

        job_key = create_job_key(job.executor_id, job.job_id)
        self.monitors[job_key] = {'thread': th, 'should_run': True}
        th.start()

    def _job_monitoring_os(self, job):
        total_callids_done = 0
        job_key = create_job_key(job.executor_id, job.job_id)

        while self.monitors[job_key]['should_run'] and total_callids_done < job.total_calls:
            time.sleep(1)
            callids_running, callids_done = self.internal_storage.get_job_status(job.executor_id, job.job_id)
            total_new_tokens = len(callids_done) - total_callids_done
            total_callids_done = total_callids_done + total_new_tokens
            for i in range(total_new_tokens):
                if self.monitors[job_key]['should_run']:
                    self.token_bucket_q.put('#')
                else:
                    break

        logger.debug('ExecutorID {} - | JobID {} -Job monitoring finished'
                     .format(job.executor_id,  job.job_id))

    def _job_monitoring_rabbitmq(self, job):
        total_callids_done = 0
        job_key = create_job_key(job.executor_id, job.job_id)

        exchange = 'lithops-{}'.format(job_key)
        queue_1 = '{}-1'.format(exchange)

        params = pika.URLParameters(self.rabbit_amqp_url)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()

        def callback(ch, method, properties, body):
            nonlocal total_callids_done
            call_status = json.loads(body.decode("utf-8"))
            if call_status['type'] == '__end__':
                if self.monitors[job_key]['should_run']:
                    self.token_bucket_q.put('#')
                total_callids_done += 1
            if total_callids_done == job.total_calls or \
               not self.monitors[job_key]['should_run']:
                ch.stop_consuming()

        channel.basic_consume(callback, queue=queue_1, no_ack=True)
        channel.start_consuming()
