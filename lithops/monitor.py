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

from lithops.utils import _future_id, log_prefix, monitoring_queue_name

pickling_support.install()

logger = logging.getLogger(__name__)

LOG_INTERVAL = 30  # Print monitor debug every LOG_INTERVAL seconds


def _status_id(call_status):
    return (
        call_status['executor_id'],
        call_status['job_id'],
        call_status['call_id'],
    )


def _is_finished(fut):
    return fut.ready or fut.success or fut.done


def _is_started(fut):
    return fut.running or _is_finished(fut)


class Monitor(threading.Thread):
    """
    Base class of the background threads that follow the futures of an
    executor and move them along their states as their status arrives
    """

    def __init__(self, executor_id,
                 internal_storage,
                 token_bucket_q,
                 job_chunksize,
                 generate_tokens,
                 config):

        super().__init__()
        self.executor_id = executor_id
        self.futures = set()
        self.internal_storage = internal_storage
        self.should_run = True
        self.token_bucket_q = token_bucket_q
        self.job_chunksize = job_chunksize
        self.generate_tokens = generate_tokens
        self.config = config
        self.daemon = True

        # vars for _generate_tokens
        self.workers = {}
        self.workers_done = []
        self.callids_done_worker = {}
        self.present_jobs = set()

    def add_futures(self, fs):
        """
        Extends the current thread list of futures to track
        """
        self.futures.update(fs)
        self.present_jobs.update(future.job_id for future in fs)

    def remove_futures(self, fs):
        """
        Remove from the current thread a list of futures
        """
        self._print_status_log()
        self.futures.difference_update(fs)
        self.present_jobs = {future.job_id for future in self.futures}

    def _all_ready(self):
        """
        Checks if all futures are ready, success or done
        """
        try:
            return all(_is_finished(f) for f in self.futures)
        except Exception:
            # Other threads add futures to the set while this one iterates
            # it. A concurrent update means there is still work to wait for
            return False

    def _check_new_futures(self, call_status, f):
        """
        Checks if a function returned new futures to track
        """
        if 'new_futures' not in call_status:
            return False

        f._set_futures(call_status)
        self.futures.update(f._new_futures)
        logger.debug(
            f'{log_prefix(self.executor_id)} - Received {len(f._new_futures)} '
            'new function Futures to track'
        )

        return True

    def _future_timeout_checker(self, futures):
        """
        Checks if running futures exceeded the timeout
        """
        current_time = time.time()
        futures_running = [f for f in futures if f.running and f._call_status]
        for fut in futures_running:
            try:
                start_tstamp = fut._call_status['worker_start_tstamp']
                fut_timeout = start_tstamp + fut.execution_timeout + 5
                if current_time > fut_timeout:
                    msg = (
                        'The function exceeded the execution timeout '
                        f'of {fut.execution_timeout} seconds.'
                    )
                    raise TimeoutError('HANDLER', msg)
            except TimeoutError:
                # Raising and catching the error right away is what fills
                # sys.exc_info(), so that the client re-raises a real
                # traceback for a worker that never reported back
                pickled_exception = str(pickle.dumps(sys.exc_info()))
                call_status = {
                    'type': '__end__',
                    'exception': True,
                    'exc_info': pickled_exception,
                    'executor_id': fut.executor_id,
                    'job_id': fut.job_id,
                    'call_id': fut.call_id,
                    'activation_id': fut.activation_id,
                    'worker_start_tstamp': start_tstamp,
                    'worker_end_tstamp': time.time(),
                }
                fut._set_ready(call_status)

    def _print_status_log(self, previous_log=None, log_time=None):
        """
        Logs how many calls are pending, running and done, but only when the
        counts moved or the job has been silent for LOG_INTERVAL seconds
        """
        if not self.futures:
            return previous_log, log_time
        callids_pending = callids_running = callids_done = 0
        for fut in self.futures:
            if fut.invoked:
                callids_pending += 1
            if fut.running:
                callids_running += 1
            if _is_finished(fut):
                callids_done += 1
        counts = (callids_pending, callids_running, callids_done)
        still_working = not all(_is_finished(fut) for fut in self.futures)
        if counts != previous_log or (
            still_working
            and log_time is not None
            and log_time > LOG_INTERVAL
        ):
            logger.debug(
                f'{log_prefix(self.executor_id)} - Pending: '
                f'{callids_pending} - Running: {callids_running} - Done: {callids_done}'
            )
            log_time = 0
        return counts, log_time


class RabbitmqMonitor(Monitor):
    """
    Job monitor that learns the status of every call from the messages the
    workers publish to a RabbitMQ queue
    """

    SLEEP_TIME = 2

    def __init__(
            self,
            executor_id,
            internal_storage,
            token_bucket_q,
            job_chunksize,
            generate_tokens,
            config
    ):
        super().__init__(
            executor_id,
            internal_storage,
            token_bucket_q,
            job_chunksize,
            generate_tokens,
            config
        )

        self.rabbit_amqp_url = config.get('amqp_url')
        self.queue = monitoring_queue_name(self.executor_id)
        self.tag = None
        self._create_resources()

    def _create_resources(self):
        """
        Creates RabbitMQ queues and exchanges of a given job
        """
        logger.debug(
            f'{log_prefix(self.executor_id)} - Creating RabbitMQ queue {self.queue}'
        )

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
        if self.tag:
            channel.basic_cancel(self.tag)
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
        not_running_futures = [
            f for f in self.futures if not _is_started(f)
        ]
        for f in not_running_futures:
            if _future_id(f) == _status_id(call_status):
                f._set_running(call_status)

    def _tag_future_as_ready(self, call_status):
        """
        Tags a future as ready based on call_status
        """
        not_ready_futures = [
            f for f in self.futures if not _is_finished(f)
        ]
        for f in not_ready_futures:
            if _future_id(f) == _status_id(call_status):
                if not self._check_new_futures(call_status, f):
                    f._set_ready(call_status)

    def _generate_tokens(self, call_status):
        """
        Hands a token back to the invoker once a whole worker is free
        """
        if not self.generate_tokens or not self.should_run:
            return

        call_id = _status_id(call_status)
        worker_id = call_status['activation_id']
        done_for_worker = self.callids_done_worker.setdefault(worker_id, [])
        done_for_worker.append(call_id)

        if (
            worker_id not in self.workers_done
            and len(done_for_worker) == call_status['chunksize']
        ):
            self.workers_done.append(worker_id)
            if self.should_run:
                self.token_bucket_q.put('#')

    def _on_message(self, ch, method, properties, body):
        """
        Applies one status message to its future, and stops consuming once
        there is nothing left to wait for
        """
        call_status = json.loads(body.decode("utf-8"))

        if call_status['type'] == '__init__':
            self._tag_future_as_running(call_status)

        elif call_status['type'] == '__end__':
            self._generate_tokens(call_status)
            self._tag_future_as_ready(call_status)

        if self._all_ready() or not self.should_run:
            ch.stop_consuming()
            ch.close()

    def _watch_timeouts(self):
        """
        Logs the job status and expires overdue futures. Runs in its own
        thread, as the monitor thread stays blocked on the queue
        """
        previous_log = None
        log_time = 0
        while self.should_run and not self._all_ready():
            previous_log, log_time = self._print_status_log(
                previous_log=previous_log, log_time=log_time
            )
            self._future_timeout_checker(self.futures)
            time.sleep(self.SLEEP_TIME)
            log_time += self.SLEEP_TIME

    def run(self):
        """
        Consumes status messages from the queue until every future is done
        """
        logger.debug(
            f'{log_prefix(self.executor_id)} | Starting RabbitMQ job monitor'
        )

        channel = self.connection.channel()
        threading.Thread(target=self._watch_timeouts, daemon=True).start()

        self.tag = channel.basic_consume(
            self.queue, self._on_message, auto_ack=True
        )
        channel.start_consuming()
        self.tag = None
        self._print_status_log()
        logger.debug(
            f'{log_prefix(self.executor_id)} | RabbitMQ job monitor finished'
        )


class StorageMonitor(Monitor):
    """
    Job monitor that learns the status of every call by polling the storage
    backend, where the workers leave their status objects
    """

    THREADPOOL_SIZE = 64

    def __init__(
            self,
            executor_id,
            internal_storage,
            token_bucket_q,
            job_chunksize,
            generate_tokens,
            config
    ):
        super().__init__(
            executor_id,
            internal_storage,
            token_bucket_q,
            job_chunksize,
            generate_tokens,
            config
        )

        self.monitoring_interval = config['monitoring_interval']

        # vars for _generate_tokens
        self.callids_running_worker = {}
        self.callids_running_processed = set()
        self.callids_done_processed = set()

        # vars for _mark_status_as_running
        self.callids_running_processed_timeout = set()

        # vars for _mark_status_as_ready
        self.callids_done_processed_status = set()
        self._ready_pool = None

    def stop(self):
        """
        Stops the monitor thread
        """
        self.should_run = False

    def join(self, timeout=None):
        """
        Waits for the monitor thread, and drops the pool it downloads the
        statuses with, which outlives the thread on a join that timed out
        """
        super().join(timeout)
        self._shutdown_ready_pool()

    def _get_ready_pool(self):
        if self._ready_pool is None:
            self._ready_pool = cf.ThreadPoolExecutor(
                max_workers=self.THREADPOOL_SIZE
            )
        return self._ready_pool

    def _shutdown_ready_pool(self):
        pool = self._ready_pool
        if pool is None:
            return
        self._ready_pool = None
        pool.shutdown(wait=False)

    def _tag_future_as_running(self, callids_running):
        """
        Mark which futures are in running status based on callids_running
        """
        current_time = time.time()
        to_process = (
            callids_running - self.callids_running_processed_timeout
        )
        pending = {
            _future_id(f): f
            for f in self.futures
            if f.invoked and not _is_started(f)
        }
        for call in to_process:
            f = pending.get(call[0])
            if f is None:
                continue
            call_status = {
                'type': '__init__',
                'activation_id': call[1],
                'worker_start_tstamp': current_time,
            }
            f._set_running(call_status)

        self.callids_running_processed_timeout.update(to_process)
        self._future_timeout_checker(self.futures)

    def _tag_future_as_ready(self, callids_done):
        """
        Mark which futures has a call_status ready to be downloaded
        """
        not_ready_futures = [
            f for f in self.futures if not _is_finished(f)
        ]
        to_process = callids_done - self.callids_done_processed_status
        fs_to_query = []

        ten_percent = int(len(self.futures) * (10 / 100))
        if len(self.futures) - len(callids_done) <= max(10, ten_percent):
            fs_to_query = not_ready_futures
        else:
            for f in not_ready_futures:
                if _future_id(f) in to_process:
                    fs_to_query.append(f)

        if not fs_to_query:
            return

        def get_status(f):
            cs = self.internal_storage.get_call_status(
                f.executor_id, f.job_id, f.call_id
            )
            f._status_query_count += 1
            if cs:
                if not self._check_new_futures(cs, f):
                    f._set_ready(cs)
                return _future_id(f)
            return None

        try:
            call_ids_processed = set(
                self._get_ready_pool().map(get_status, fs_to_query)
            )
        except Exception:
            return
        finally:
            # The final sweep of run() happens after the thread is done, so
            # the pool it lazily recreated has to be dropped again
            if not self.is_alive():
                self._shutdown_ready_pool()

        call_ids_processed.discard(None)
        self.callids_done_processed_status.update(call_ids_processed)

    def _generate_tokens(self, callids_running, callids_done):
        """
        Hands a token back to the invoker for every worker that finished the
        whole chunk of calls it was given
        """
        if not self.generate_tokens or not self.should_run:
            return

        running_new = (
            callids_running - self.callids_running_processed
        )
        done_new = callids_done - self.callids_done_processed

        for call_id, worker_id in running_new:
            self.workers.setdefault(worker_id, set()).add(call_id)
            self.callids_running_worker[call_id] = worker_id

        for callid_done in done_new:
            if callid_done in self.callids_running_worker:
                worker_id = self.callids_running_worker[callid_done]
                self.callids_done_worker.setdefault(worker_id, []).append(
                    callid_done
                )

        for worker_id in self.callids_done_worker:
            job_id = self.callids_done_worker[worker_id][0][1]
            if job_id not in self.present_jobs:
                continue
            chunksize = self.job_chunksize[job_id]
            done_count = len(self.callids_done_worker[worker_id])
            if worker_id not in self.workers_done and done_count == chunksize:
                self.workers_done.append(worker_id)
                if self.should_run:
                    self.token_bucket_q.put('#')
                else:
                    break

        self.callids_running_processed.update(running_new)
        self.callids_done_processed.update(done_new)

    def _poll_and_process_job_status(self, previous_log, log_time):
        """
        Reads the job status from storage and applies it to the futures.
        Returns the call ids that are newly done, along with the updated
        log state its caller has to pass back on the next round
        """
        status = self.internal_storage.get_job_status(
            self.executor_id, job_ids=self.present_jobs
        )
        callids_running, callids_done = status
        new_callids_done = (
            callids_done - self.callids_done_processed_status
        )

        self._generate_tokens(callids_running, callids_done)
        self._tag_future_as_running(callids_running)
        self._tag_future_as_ready(callids_done)

        previous_log, log_time = self._print_status_log(previous_log, log_time)

        return new_callids_done, previous_log, log_time

    def run(self):
        """
        Polls the storage backend until the monitor is stopped, backing off
        to the configured interval whenever a round brings nothing new
        """
        logger.debug(
            f'{log_prefix(self.executor_id)} - Starting Storage job monitor'
        )

        wait_dur_sec = self.monitoring_interval
        previous_log = None
        log_time = 0

        while self.should_run:
            try:
                new_callids_done, previous_log, log_time = (
                    self._poll_and_process_job_status(
                        previous_log, log_time
                    )
                )
                if new_callids_done:
                    wait_dur_sec = self.monitoring_interval / 5
                else:
                    wait_dur_sec = self.monitoring_interval
            except Exception as e:
                logger.error(
                    f'{log_prefix(self.executor_id)} - Error during '
                    f'monitor: {e}',
                    exc_info=True,
                )
            if not self.should_run:
                break
            time.sleep(wait_dur_sec)
            log_time += wait_dur_sec

        # One last sweep, so that statuses written between the final poll
        # and the stop are not lost. The storage may already be gone
        try:
            self._poll_and_process_job_status(previous_log, log_time)
        except Exception:
            pass

        self._shutdown_ready_pool()
        logger.debug(
            f'{log_prefix(self.executor_id)} - Storage job monitor finished'
        )


class JobMonitor:
    """
    Owns the monitor thread of one executor, and picks the implementation
    that matches the configured monitoring backend
    """

    def __init__(self, executor_id, internal_storage, config=None):
        self.executor_id = executor_id
        self.internal_storage = internal_storage
        self.storage_config = internal_storage.get_storage_config()
        self.storage_backend = internal_storage.backend
        self.config = config
        self.type = (
            config['lithops']['monitoring'].lower() if config else 'storage'
        )

        self.token_bucket_q = queue.Queue()
        self.monitor = None
        self.job_chunksize = {}

        self.MonitorClass = getattr(
            lithops.monitor,
            f'{self.type.capitalize()}Monitor'
        )

    def start(self, fs, job_id=None, chunksize=None, generate_tokens=False):
        """
        Tracks a new set of futures, spawning the monitor thread unless a
        live one can take them over
        """
        if self.type == 'storage':
            interval = self.storage_config['monitoring_interval']
            monitor_config = {'monitoring_interval': interval}
        else:
            monitor_config = self.config.get(self.type)

        if job_id:
            self.job_chunksize[job_id] = chunksize

        if not self.monitor or not self.monitor.is_alive():
            self.monitor = self.MonitorClass(
                executor_id=self.executor_id,
                internal_storage=self.internal_storage,
                token_bucket_q=self.token_bucket_q,
                job_chunksize=self.job_chunksize,
                generate_tokens=generate_tokens,
                config=monitor_config
            )

        self.monitor.add_futures(fs)

        if not self.monitor.is_alive():
            self.monitor.start()

    def is_alive(self):
        """
        Tells whether the monitor thread is still running
        """
        return self.monitor.is_alive()

    def remove(self, fs):
        """
        Stops tracking a set of futures
        """
        if self.monitor and self.monitor.is_alive():
            self.monitor.remove_futures(fs)

    def stop(self):
        """
        Stops the monitor thread and waits for it to wind down
        """
        if self.monitor and self.monitor.is_alive():
            self.monitor.stop()
            self.monitor.join(timeout=5)
