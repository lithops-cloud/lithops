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
import multiprocessing as mp


from lithops.utils import is_lithops_worker, is_unix_system

logger = logging.getLogger(__name__)


class RabbitMQMonitor(threading.Thread):

    def __init__(self, lithops_config, internal_storage, token_bucket_q,
                 job, generate_tokens, *args):
        super().__init__()
        self.lithops_config = lithops_config
        self.internal_storage = internal_storage
        self.rabbit_amqp_url = self.lithops_config['rabbitmq'].get('amqp_url')
        self.should_run = True
        self.token_bucket_q = token_bucket_q
        self.job = job
        self.generate_tokens = generate_tokens
        self.daemon = not is_lithops_worker()

        params = pika.URLParameters(self.rabbit_amqp_url)
        self.connection = pika.BlockingConnection(params)

        self._create_resources()

    def _create_resources(self):
        """
        Creates RabbitMQ queues and exchanges of a given job in a thread.
        Called when a job is created.
        """
        logger.debug('ExecutorID {} | JobID {} - Creating RabbitMQ resources'
                     .format(self.job.executor_id, self.job.job_id))

        exchange = 'lithops-{}'.format(self.job.job_key)
        queue_0 = '{}-0'.format(exchange)  # For local monitor
        queue_1 = '{}-1'.format(exchange)  # For remote monitor

        channel = self.connection.channel()
        channel.exchange_declare(exchange=exchange, exchange_type='fanout', auto_delete=True)
        channel.queue_declare(queue=queue_0, auto_delete=True)
        channel.queue_bind(exchange=exchange, queue=queue_0)
        channel.queue_declare(queue=queue_1, auto_delete=True)
        channel.queue_bind(exchange=exchange, queue=queue_1)

    def _delete_resources(self):
        """
        Deletes RabbitMQ queues and exchanges of a given job.
        Only called when an exception is produced, otherwise resources are
        automatically deleted.
        """
        exchange = 'lithops-{}'.format(self.job.job_key)
        queue_0 = '{}-0'.format(exchange)  # For local monitor
        queue_1 = '{}-1'.format(exchange)  # For remote monitor

        channel = self.connection.channel()
        channel.queue_delete(queue=queue_0)
        channel.queue_delete(queue=queue_1)
        channel.exchange_delete(exchange=exchange)

    def stop(self):
        self.should_run = False
        self._delete_resources()
        self.connection.close()

    def run(self):
        total_callids_done = 0
        exchange = 'lithops-{}'.format(self.job.job_key)
        queue_0 = '{}-0'.format(exchange)

        channel = self.connection.channel()

        def callback(ch, method, properties, body):
            nonlocal total_callids_done
            call_status = json.loads(body.decode("utf-8"))
            if call_status['type'] == '__end__':
                if self.should_run:
                    self.token_bucket_q.put('#')
                total_callids_done += 1
            if total_callids_done == self.job.total_calls or not self.should_run:
                ch.stop_consuming()
                logger.debug('ExecutorID {} | JobID {} - RabbitMQ job monitor finished'
                             .format(self.job.executor_id, self.job.job_id))

        channel.basic_consume(callback, queue=queue_0, no_ack=True)
        channel.start_consuming()


class StorageMonitor(threading.Thread):

    WAIT_DUR_SEC = 2  # Check interval

    def __init__(self, job, internal_storage, token_bucket_q, generate_tokens):
        super().__init__()
        self.internal_storage = internal_storage
        self.should_run = True
        self.token_bucket_q = token_bucket_q
        self.job = job
        self.generate_tokens = generate_tokens
        self.daemon = not is_lithops_worker()
        self.futures_ready = []

        # vars for _generate_tokens
        self.workers = {}
        self.workers_done = []
        self.callids_done_worker = {}
        self.callids_running_worker = {}
        self.callids_running_processed = set()
        self.callids_done_processed = set()

        # vars for _mark_status_as_running
        self.running_futures = set()
        self.callids_running_processed_timeout = set()

        # vars for _mark_status_as_ready
        self.callids_done_processed_status = set()

    def stop(self):
        self.should_run = False

    def _all_ready(self):
        """
        Checks if all futures are ready or done
        """
        return all([f._call_status_ready for f in self.job.futures])

    def _mark_status_as_running(self, callids_running):
        """
        Mark which futures are in running status based on callids_running
        """
        current_time = time.time()
        not_done_futures = [f for f in self.job.futures if not (f.ready or f.done)]
        callids_running_to_process = callids_running - self.callids_running_processed_timeout
        for f in not_done_futures:
            for call in callids_running_to_process:
                if (f.executor_id, f.job_id, f.call_id) == call[0]:
                    if f.invoked and f not in self.running_futures:
                        f.activation_id = call[1]
                        f._call_status = {'type': '__init__',
                                          'activation_id': call[1],
                                          'start_time': current_time}
                        f.status(internal_storage=self.internal_storage)
                        self.running_futures.add(f)
        self.callids_running_processed_timeout.update(callids_running_to_process)
        _future_timeout_checker(self.running_futures)

    def _mark_status_as_ready(self, callids_done):
        """
        Mark which futures has a call_status ready to be downloaded
        """
        not_ready_futures = [f for f in self.job.futures if not f._call_status_ready]
        callids_done_to_process = callids_done - self.callids_done_processed_status
        for f in not_ready_futures:
            for call_data in callids_done_to_process:
                if (f.executor_id, f.job_id, f.call_id) == call_data:
                    f._call_status_ready = True
        self.callids_done_processed_status.update(callids_done_to_process)

    def _generate_tokens(self, callids_running, callids_done):
        """
        Method that generates new tokens
        """
        if not self.generate_tokens:
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
        while self.should_run and not self._all_ready():
            time.sleep(self.WAIT_DUR_SEC)
            if not self.should_run:
                break
            callids_running, callids_done = \
                self.internal_storage.get_job_status(self.job.executor_id, self.job.job_id)
            self._generate_tokens(callids_running, callids_done)
            self._mark_status_as_running(callids_running)
            self._mark_status_as_ready(callids_done)

        logger.debug('ExecutorID {} | JobID {} - Storage job monitor finished'
                     .format(self.job.executor_id, self.job.job_id))


class JobMonitor:

    def __init__(self):
        self.monitors = {}
        self.use_threads = (is_lithops_worker()
                            or not is_unix_system()
                            or mp.get_start_method() != 'fork')

        if self.use_threads:
            self.token_bucket_q = queue.Queue()
        else:
            self.token_bucket_q = mp.Queue()

    def stop(self):
        for job_key in self.monitors:
            self.monitors[job_key].stop()

        self.monitors = {}

    def get_active_jobs(self):
        active_jobs = 0
        for job_monitor in self.monitors:
            if job_monitor.is_alive():
                active_jobs += 1
        return active_jobs

    def start_job_monitoring(self, job, internal_storage, generate_tokens=False):
        """
        Starts a monitor for a given job
        """
        logger.debug('ExecutorID {} | JobID {} - Starting {} job monitor'
                     .format(job.executor_id, job.job_id, job.monitoring))
        Monitor = getattr(lithops.monitor, '{}Monitor'.format(job.monitoring))
        jm = Monitor(job=job, internal_storage=internal_storage,
                     token_bucket_q=self.token_bucket_q,
                     generate_tokens=generate_tokens)
        jm.start()
        self.monitors[job.job_key] = jm


def _future_timeout_checker(running_futures):
    """
    Checks if running futures exceeded the timeout
    """
    current_time = time.time()
    for fut in running_futures:
        if fut.running and fut._call_status:
            try:
                fut_timeout = fut._call_status['start_time'] + fut.execution_timeout + 5
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
                fut._call_status = call_status
                fut._call_status_ready = True
