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
import multiprocessing as mp
import concurrent.futures as cf

from lithops.utils import is_lithops_worker, is_unix_system

logger = logging.getLogger(__name__)


class RabbitMQMonitor(threading.Thread):

    def __init__(self, lithops_config, internal_storage, token_bucket_q, job):
        super().__init__()
        self.lithops_config = lithops_config
        self.internal_storage = internal_storage
        self.rabbit_amqp_url = self.lithops_config['rabbitmq'].get('amqp_url')
        self.should_run = True
        self.token_bucket_q = token_bucket_q
        self.job = job
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

    def __init__(self, lithops_config, internal_storage, token_bucket_q, job):
        super().__init__()
        self.lithops_config = lithops_config
        self.internal_storage = internal_storage
        self.should_run = True
        self.token_bucket_q = token_bucket_q
        self.job = job
        self.daemon = not is_lithops_worker()
        self.futures_ready = []

        self.pbar = None
        self.throw_except = False
        self.download_results = False
        self.wait_dur_sec = 2
        self.threadpool_size = 128
        self.pool = cf.ThreadPoolExecutor(max_workers=self.threadpool_size)

    def stop(self):
        self.pool.shutdown()
        self.should_run = False

    def update_params(self, pbar, throw_except, download_results,
                      wait_dur_sec, threadpool_size):
        """
        Method used to update the waiting parameters
        """
        self.pbar = pbar
        self.throw_except = throw_except
        self.download_results = download_results
        self.wait_dur_sec = wait_dur_sec
        self.threadpool_size = threadpool_size

    def all_done(self):
        """
        Checks if all futures are ready or done
        """
        if self.download_results:
            return all([f.done for f in self.job.futures])
        else:
            return all([f.ready or f.done for f in self.job.futures])

    def any_done(self):
        """
        Checks if all futures are ready or done
        """
        if self.download_results:
            return any([f.done for f in self.job.futures])
        else:
            return any([f.ready or f.done for f in self.job.futures])

    def _process_callids_running(self, callids_running):
        """
        Mark all futures in callids_running as running
        """
        pass

    def _process_callids_done(self, callids_done):
        """
        Download status from all callids_done
        """
        if self.download_results:
            not_done_futures = [f for f in self.job.futures if not f.done]
        else:
            not_done_futures = [f for f in self.job.futures if not (f.ready or f.done)]

        not_done_call_ids = set([(f.executor_id, f.job_id, f.call_id) for f in not_done_futures])
        done_call_ids = not_done_call_ids.intersection(callids_done)

        fs_to_wait_on = []
        for f in self.job.futures:
            if (f.executor_id, f.job_id, f.call_id) in done_call_ids:
                fs_to_wait_on.append(f)

        def get_result(f):
            if f.running:
                f._call_status = None
            f.result(throw_except=self.throw_except, internal_storage=self.internal_storage)

        def get_status(f):
            if f.running:
                f._call_status = None
            f.status(throw_except=self.throw_except, internal_storage=self.internal_storage)

        if self.download_results:
            list(self.pool.map(get_result, fs_to_wait_on))
        else:
            list(self.pool.map(get_status, fs_to_wait_on))

        if self.pbar:
            for f in fs_to_wait_on:
                if (self.download_results and f.done) or \
                   (not self.download_results and (f.ready or f.done)):
                    self.pbar.update(1)
            self.pbar.refresh()

        # Check for new futures
        new_futures = [f.result() for f in fs_to_wait_on if f.futures]
        for futures in new_futures:
            self.job.futures.extend(futures)
            if self.pbar:
                self.pbar.total = self.pbar.total + len(futures)
                self.pbar.refresh()

        self.futures_ready.append(fs_to_wait_on)

    def run(self):
        workers = {}
        workers_done = []
        callids_done_worker = {}
        callids_running_worker = {}
        callids_running_processed = set()
        callids_done_processed = set()

        while self.should_run and len(callids_done_processed) < self.job.total_calls:
            time.sleep(self.wait_dur_sec)
            if not self.should_run:
                break
            callids_running, callids_done = self.internal_storage.get_job_status(self.job.executor_id,
                                                                                 self.job.job_id)

            callids_running_to_process = callids_running - callids_running_processed
            callids_done_to_process = callids_done - callids_done_processed

            for call_id, worker_id in callids_running_to_process:
                if worker_id not in workers:
                    workers[worker_id] = set()
                workers[worker_id].add(call_id)
                callids_running_worker[call_id] = worker_id

            for callid_done in callids_done_to_process:
                if callid_done in callids_running_worker:
                    worker_id = callids_running_worker[callid_done]
                    if worker_id not in callids_done_worker:
                        callids_done_worker[worker_id] = []
                    callids_done_worker[worker_id].append(callid_done)

            for worker_id in callids_done_worker:
                if worker_id not in workers_done and \
                   len(callids_done_worker[worker_id]) == self.job.chunksize:
                    workers_done.append(worker_id)
                    if self.should_run:
                        self.token_bucket_q.put('#')
                    else:
                        break

            callids_done_processed.update(callids_done_to_process)

            self._process_callids_running(callids_running)
            self._process_callids_done(callids_done)

        logger.debug('ExecutorID {} | JobID {} - Storage job monitor finished'
                     .format(self.job.executor_id, self.job.job_id))


class JobMonitor:

    def __init__(self, lithops_config, internal_storage):
        self.lithops_config = lithops_config
        self.internal_storage = internal_storage
        self.monitors = {}

        self.backend = self.lithops_config['lithops'].get('monitoring', 'Storage')

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

    def start_job_monitoring(self, job):
        logger.debug('ExecutorID {} | JobID {} - Starting {} job monitor'
                     .format(job.executor_id, job.job_id, self.backend))
        Monitor = getattr(lithops.monitor, '{}Monitor'.format(self.backend))
        jm = Monitor(self.lithops_config, self.internal_storage,
                     self.token_bucket_q, job)
        jm.start()
        self.monitors[job.job_key] = jm
