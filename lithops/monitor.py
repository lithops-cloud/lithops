#
# Copyright Cloudlab URV 2021
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

import json
import pika
import logging
import time
import lithops
import pickle
import sys
import queue
import threading
import concurrent.futures as cf
from tblib import pickling_support


pickling_support.install()

logger = logging.getLogger(__name__)


class Monitor(threading.Thread):
    """
    Monitor base class
    """
    def __init__(self, job, internal_storage, token_bucket_q, generate_tokens, config):
        super().__init__()
        self.job = job
        self.internal_storage = internal_storage
        self.should_run = True
        self.token_bucket_q = token_bucket_q
        self.generate_tokens = generate_tokens
        self.config = config
        self.daemon = True

        # vars for _generate_tokens
        self.workers = {}
        self.workers_done = []
        self.callids_done_worker = {}

    def _all_ready(self):
        """
        Checks if all futures are ready, success or done
        """
        return all([f.ready or f.success or f.done for f in self.job.futures])

    def _check_new_futures(self, call_status, f):
        """Checks if a functions returned new futures to track"""
        if 'new_futures' not in call_status:
            return False

        f._set_futures(call_status)
        self.job.futures.extend(f._new_futures)
        logger.debug('ExecutorID {} | JobID {} - Got {} new futures to track'
                     .format(self.job.executor_id, self.job.job_id, len(f._new_futures)))

        return True

    def _future_timeout_checker(self, futures):
        """
        Checks if running futures exceeded the timeout
        """
        current_time = time.time()
        futures_running = [f for f in futures if f.running]
        for fut in futures_running:
            try:
                start_tstamp = fut._call_status['worker_start_tstamp']
                fut_timeout = start_tstamp + fut.execution_timeout + 5
                if current_time > fut_timeout:
                    msg = 'The function did not run as expected.'
                    raise TimeoutError('HANDLER', msg)
            except TimeoutError:
                # generate fake TimeoutError call status
                pickled_exception = str(pickle.dumps(sys.exc_info()))
                call_status = {'type': '__end__',
                               'exception': True,
                               'exc_info': pickled_exception,
                               'executor_id': fut.executor_id,
                               'job_id': fut.job_id,
                               'call_id': fut.call_id,
                               'activation_id': fut.activation_id}
                fut._set_ready(call_status)

    def _print_status_log(self):
        """prints a debug log showing the status of the job"""
        callids_pending = len([f for f in self.job.futures if f.invoked])
        callids_running = len([f for f in self.job.futures if f.running])
        callids_done = len([f for f in self.job.futures if f.ready or f.success or f.done])
        logger.debug('ExecutorID {} | JobID {} - Pending: {} - Running: {} - Done: {}'
                     .format(self.job.executor_id, self.job.job_id,
                             callids_pending, callids_running, callids_done))


class RabbitmqMonitor(Monitor):

    def __init__(self, job, internal_storage, token_bucket_q, generate_tokens, config):
        super().__init__(job, internal_storage, token_bucket_q, generate_tokens, config)

        self.rabbit_amqp_url = config.get('amqp_url')
        self.queue = 'lithops-{}'.format(self.job.job_key)
        self._create_resources()

    def _create_resources(self):
        """
        Creates RabbitMQ queues and exchanges of a given job
        """
        logger.debug('ExecutorID {} | JobID {} - Creating RabbitMQ resources'
                     .format(self.job.executor_id, self.job.job_id))

        self.pikaparams = pika.URLParameters(self.rabbit_amqp_url)
        self.connection = pika.BlockingConnection(self.pikaparams)
        channel = self.connection.channel()
        channel.queue_declare(queue=self.queue, auto_delete=True)
        channel.close()

    def _delete_resources(self):
        """
        Deletes RabbitMQ queues and exchanges of a given job.
        """
        connection = pika.BlockingConnection(self.pikaparams)
        channel = connection.channel()
        channel.queue_delete(queue=self.queue)
        channel.close()
        connection.close()

    def stop(self):
        """
        Stops the monitor thread
        """
        self.should_run = False
        self._delete_resources()

    def _tag_future_as_running(self, call_status):
        """
        Assigns a call_status to its future
        """
        not_running_futures = [f for f in self.job.futures if not (f.running or f.ready or f.success or f.done)]
        for f in not_running_futures:
            calljob_id = (call_status['executor_id'], call_status['job_id'], call_status['call_id'])
            if (f.executor_id, f.job_id, f.call_id) == calljob_id:
                f._set_running(call_status)

    def _tag_future_as_ready(self, call_status):
        """
        tags a future as ready based on call_status
        """
        not_ready_futures = [f for f in self.job.futures if not (f.ready or f.success or f.done)]
        for f in not_ready_futures:
            calljob_id = (call_status['executor_id'], call_status['job_id'], call_status['call_id'])
            if (f.executor_id, f.job_id, f.call_id) == calljob_id:
                if not self._check_new_futures(call_status, f):
                    f._set_ready(call_status)

    def _generate_tokens(self, call_status):
        """
        generates a new token for the invoker
        """
        if not self.generate_tokens or not self.should_run:
            return

        call_id = (call_status['executor_id'], call_status['job_id'], call_status['call_id'])
        worker_id = call_status['activation_id']
        if worker_id not in self.callids_done_worker:
            self.callids_done_worker[worker_id] = []
        self.callids_done_worker[worker_id].append(call_id)

        if worker_id not in self.workers_done and \
           len(self.callids_done_worker[worker_id]) == self.job.chunksize:
            self.workers_done.append(worker_id)
            if self.should_run:
                self.token_bucket_q.put('#')

    def run(self):
        logger.debug('ExecutorID {} | JobID {} - Starting RabbitMQ job monitor'
                     .format(self.job.executor_id, self.job.job_id))
        channel = self.connection.channel()

        def callback(ch, method, properties, body):
            call_status = json.loads(body.decode("utf-8"))

            if call_status['type'] == '__init__':
                self._tag_future_as_running(call_status)

            elif call_status['type'] == '__end__':
                self._generate_tokens(call_status)
                self._tag_future_as_ready(call_status)

            if self._all_ready() or not self.should_run:
                ch.stop_consuming()
                ch.close()
                self._print_status_log()
                logger.debug('ExecutorID {} | JobID {} - RabbitMQ job monitor finished'
                             .format(self.job.executor_id, self.job.job_id))

        channel.basic_consume(self.queue, callback, auto_ack=True)
        threading.Thread(target=channel.start_consuming, daemon=True).start()

        while not self._all_ready() and self.should_run:
            # Format call_ids running, pending and done
            self._print_status_log()
            self._future_timeout_checker(self.job.futures)
            time.sleep(2)


class StorageMonitor(Monitor):

    THREADPOOL_SIZE = 64
    WAIT_DUR_SEC = 2  # Check interval

    def __init__(self, job, internal_storage, token_bucket_q, generate_tokens, config):
        super().__init__(job, internal_storage, token_bucket_q, generate_tokens, config)

        # vars for _generate_tokens
        self.callids_running_worker = {}
        self.callids_running_processed = set()
        self.callids_done_processed = set()

        # vars for _mark_status_as_running
        self.callids_running_processed_timeout = set()

        # vars for _mark_status_as_ready
        self.callids_done_processed_status = set()

    def stop(self):
        """
        Stops the monitor thread
        """
        self.should_run = False

    def _tag_future_as_running(self, callids_running):
        """
        Mark which futures are in running status based on callids_running
        """
        current_time = time.time()
        not_running_futures = [f for f in self.job.futures if not (f.running or f.ready or f.success or f.done)]
        callids_running_to_process = callids_running - self.callids_running_processed_timeout
        for f in not_running_futures:
            for call in callids_running_to_process:
                if f.invoked and (f.executor_id, f.job_id, f.call_id) == call[0]:
                    call_status = {'type': '__init__',
                                   'activation_id': call[1],
                                   'worker_start_tstamp': current_time}
                    f._set_running(call_status)

        self.callids_running_processed_timeout.update(callids_running_to_process)
        self._future_timeout_checker(self.job.futures)

    def _tag_future_as_ready(self, callids_done):
        """
        Mark which futures has a call_status ready to be downloaded
        """
        not_ready_futures = [f for f in self.job.futures if not (f.ready or f.success or f.done)]
        callids_done_to_process = callids_done - self.callids_done_processed_status
        fs_to_query = []

        ten_percent = int(len(self.job.futures) * (10 / 100))
        if len(self.job.futures) - len(callids_done) <= max(10, ten_percent):
            fs_to_query = not_ready_futures
        else:
            for f in not_ready_futures:
                if (f.executor_id, f.job_id, f.call_id) in callids_done_to_process:
                    fs_to_query.append(f)

        if not fs_to_query:
            return

        def get_status(f):
            cs = self.internal_storage.get_call_status(f.executor_id, f.job_id, f.call_id)
            if cs:
                if not self._check_new_futures(cs, f):
                    f._set_ready(cs)
                return (f.executor_id, f.job_id, f.call_id)
            else:
                return None

        pool = cf.ThreadPoolExecutor(max_workers=self.THREADPOOL_SIZE)
        call_ids_processed = set(pool.map(get_status, fs_to_query))
        pool.shutdown()

        try:
            call_ids_processed.remove(None)
        except Exception:
            pass

        self.callids_done_processed_status.update(call_ids_processed)

    def _generate_tokens(self, callids_running, callids_done):
        """
        Method that generates new tokens
        """
        if not self.generate_tokens or not self.should_run:
            return

        callids_running_to_process = callids_running - self.callids_running_processed
        callids_done_to_process = callids_done - self.callids_done_processed

        for call_id, worker_id in callids_running_to_process:
            if worker_id not in self.workers:
                self.workers[worker_id] = set()
            self.workers[worker_id].add(call_id)
            self.callids_running_worker[call_id] = worker_id

        for callid_done in callids_done_to_process:
            if callid_done in self.callids_running_worker:
                worker_id = self.callids_running_worker[callid_done]
                if worker_id not in self.callids_done_worker:
                    self.callids_done_worker[worker_id] = []
                self.callids_done_worker[worker_id].append(callid_done)

        for worker_id in self.callids_done_worker:
            if worker_id not in self.workers_done and \
               len(self.callids_done_worker[worker_id]) == self.job.chunksize:
                self.workers_done.append(worker_id)
                if self.should_run:
                    self.token_bucket_q.put('#')
                else:
                    break

        self.callids_running_processed.update(callids_running_to_process)
        self.callids_done_processed.update(callids_done_to_process)

    def run(self):
        """
        Run method
        """
        logger.debug('ExecutorID {} | JobID {} - Starting Storage job monitor'
                     .format(self.job.executor_id, self.job.job_id))

        while self.should_run and not self._all_ready():
            if not self.should_run:
                break
            callids_running, callids_done = \
                self.internal_storage.get_job_status(self.job.executor_id, self.job.job_id)

            # verify if there are new callids_done and reduce the sleep
            new_callids_done = callids_done - self.callids_done_processed_status
            if len(new_callids_done) > 0:
                self.WAIT_DUR_SEC = 0.5

            # generate tokens and mark futures as runiing/done
            self._generate_tokens(callids_running, callids_done)
            self._tag_future_as_running(callids_running)
            self._tag_future_as_ready(callids_done)
            self._print_status_log()

            if not self._all_ready():
                time.sleep(self.WAIT_DUR_SEC)
                self.WAIT_DUR_SEC = 2

        logger.debug('ExecutorID {} | JobID {} - Storage job monitor finished'
                     .format(self.job.executor_id, self.job.job_id))


class JobMonitor:

    def __init__(self, backend, config=None):
        self.backend = backend
        self.config = config
        self.monitors = {}
        self.token_bucket_q = queue.Queue()

    def stop(self, job_keys=None):
        """
        Stops job monitors
        """
        if job_keys:
            for job_key in job_keys:
                if job_key in self.monitors:
                    if self.monitors[job_key].is_alive():
                        self.monitors[job_key].stop()
                    del self.monitors[job_key]
        else:
            # Stop all
            for job_key in self.monitors:
                if self.monitors[job_key].is_alive():
                    self.monitors[job_key].stop()
            self.monitors = {}

    def is_alive(self, job_key):
        """
        Checks if a job monitor is alive
        """
        if job_key not in self.monitors:
            return False
        return self.monitors[job_key].is_alive()

    def get_active_jobs(self):
        """
        Returns a list of active job monitors
        """
        active_jobs = 0
        for job_monitor in self.monitors:
            if job_monitor.is_alive():
                active_jobs += 1
        return active_jobs

    def create(self, job, internal_storage, generate_tokens=False):
        """
        Creates a new monitor for a given job
        """
        Monitor = getattr(lithops.monitor, '{}Monitor'.format(self.backend.capitalize()))
        jm = Monitor(job=job, internal_storage=internal_storage,
                     token_bucket_q=self.token_bucket_q,
                     generate_tokens=generate_tokens, config=self.config)
        self.monitors[job.job_key] = jm
        return jm
