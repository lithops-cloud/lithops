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
import queue
import threading
import copy
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

        # vars for calculating and generating new tokens for invoker
        self.workers = {}
        self.workers_done = []
        self.callids_done_worker = {}
        self.callids_running_worker = {}
        self.callids_running_processed = set()
        self.callids_done_processed = set()

    def stop(self):
        self.should_run = False

    def _all_ready(self):
        """
        Checks if all futures are ready or done
        """
        return all([f._call_status_ready for f in self.job.futures])

    def _timeout_checker(self, callids_running):
        """
        Mark all futures in callids_running as running
        """
        pass

    def _mark_status_as_ready(self, callids_done):
        """
        Mark which call_status are ready in the futures
        """
        not_ready_futures = [f for f in self.job.futures if not f._call_status_ready]
        for f in not_ready_futures:
            for call_data in callids_done:
                if (f.executor_id, f.job_id, f.call_id) == call_data:
                    f._call_status_ready = True

    def _generate_tokens(self, callids_running, callids_done):
        """
        Method that generates new tokens
        """
        if not self.generate_tokens:
            return

        self.callids_running_to_process = callids_running - self.callids_running_processed
        callids_done_to_process = callids_done - self.callids_done_processed

        for call_id, worker_id in self.callids_running_to_process:
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
            self._mark_status_as_ready(callids_done)
            self._timeout_checker(callids_running)

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
