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

import logging
import time
import concurrent.futures as cf

from lithops.monitoring.monitor import (
    Monitor,
    _future_id,
    _is_finished,
    _is_started,
)
from lithops.utils import log_prefix

logger = logging.getLogger(__name__)


class StorageMonitor(Monitor):
    """
    Job monitor that learns the status of every call by polling the storage
    backend, where the workers leave their status objects.

    This is a monitoring *channel*, not a storage *provider*. The objects
    it reads live in whichever storage backend the executor already uses
    (S3, IBM COS, localhost, ...).
    """

    THREADPOOL_SIZE = 64

    #: How often the calls that the listing does not report as done are
    #: queried anyway, near the end of a job. The listing is what says which
    #: statuses are there; this is only a safety net for one that is behind,
    #: so it runs on a clock rather than on every poll
    BLIND_SWEEP_INTERVAL = 30

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
        self.worker_job = {}

        # vars for _mark_status_as_running
        self.callids_running_processed_timeout = set()

        # vars for _mark_status_as_ready
        self.callids_done_processed_status = set()
        self._ready_pool = None
        self._last_blind_sweep = time.time()

    @classmethod
    def prepare_config(cls, config, internal_storage):
        interval = internal_storage.get_storage_config()['monitoring_interval']
        return {'monitoring_interval': interval}

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
        for call in to_process:
            f = self.future_by_id(call[0])
            if f is None or not f.invoked or _is_started(f):
                continue
            call_status = {
                'type': '__init__',
                'activation_id': call[1],
                'worker_start_tstamp': current_time,
            }
            f._set_running(call_status)

        self.callids_running_processed_timeout.update(to_process)
        self._future_timeout_checker()

    def _tag_future_as_ready(self, callids_done):
        """
        Mark which futures has a call_status ready to be downloaded
        """
        futures = self.tracked_futures()
        not_ready_futures = [f for f in futures if not _is_finished(f)]
        to_process = callids_done - self.callids_done_processed_status

        # The calls the listing reports as done and whose status has not
        # been read yet. This is the whole job in the normal case
        fs_to_query = [
            f for f in not_ready_futures if _future_id(f) in to_process
        ]

        # Near the end, the calls the listing does NOT report as done are
        # queried as well, in case it is behind. Rate limited: a job with a
        # long tail spends most of its life in this branch, and querying
        # every straggler on every poll turned one GET per call into
        # dozens, all of them for objects the listing had already said
        # were not there
        ten_percent = int(len(futures) * (10 / 100))
        near_the_end = (
            len(futures) - len(callids_done) <= max(10, ten_percent)
        )
        now = time.time()
        if near_the_end and now - self._last_blind_sweep >= \
                self.BLIND_SWEEP_INTERVAL:
            self._last_blind_sweep = now
            queried = set(fs_to_query)
            fs_to_query.extend(
                f for f in not_ready_futures if f not in queried
            )

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
        except Exception as e:
            # One unreadable status object must not take the monitor down,
            # but it is not something to keep quiet about either: the next
            # round queries the same futures again
            if self.should_run:
                logger.warning(
                    f'{log_prefix(self.executor_id)} - Could not read the '
                    f'status of {len(fs_to_query)} call(s): {e}',
                    exc_info=True,
                )
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
            self.callids_running_worker[call_id] = worker_id

        for callid_done in done_new:
            worker_id = self.callids_running_worker.get(callid_done)
            if worker_id is None:
                continue
            self.callids_done_worker.setdefault(worker_id, set()).add(
                callid_done
            )
            # The job the worker belongs to, kept aside so that the chunksize
            # can be looked up without picking a call id back out of the set
            self.worker_job.setdefault(worker_id, callid_done[1])

        present_jobs = self.present_jobs
        for worker_id, done_calls in self.callids_done_worker.items():
            if worker_id in self.workers_done:
                continue
            job_id = self.worker_job.get(worker_id)
            if job_id is None or job_id not in present_jobs:
                continue
            chunksize = self.job_chunksize.get(job_id)
            if chunksize is None or len(done_calls) < chunksize:
                continue
            self.workers_done.add(worker_id)
            if not self.should_run:
                break
            self.token_bucket_q.put('#')

        self.callids_running_processed.update(running_new)
        self.callids_done_processed.update(done_new)

    def _poll_and_process_job_status(self):
        """
        Reads the job status from storage and applies it to the futures.
        Returns the call ids that are newly done
        """
        status = self.internal_storage.get_job_status(
            self.executor_id, job_ids=self.job_ids()
        )
        callids_running, callids_done = status
        new_callids_done = (
            callids_done - self.callids_done_processed_status
        )

        self._generate_tokens(callids_running, callids_done)
        self._tag_future_as_running(callids_running)
        self._tag_future_as_ready(callids_done)

        self._print_status_log()

        return new_callids_done

    def run(self):
        """
        Polls the storage backend until the monitor is stopped, backing off
        to the configured interval whenever a round brings nothing new
        """
        logger.debug(
            f'{log_prefix(self.executor_id)} - Starting Storage job monitor'
        )

        wait_dur_sec = self.monitoring_interval

        while self.should_run:
            try:
                new_callids_done = self._poll_and_process_job_status()
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
            # Short-circuited, so that a monitor already stopped does not
            # even ask to wait before the final sweep
            if not self.should_run or not self.sleep(wait_dur_sec):
                break

        # One last sweep, so that statuses written between the final poll
        # and the stop are not lost. The storage may already be gone
        try:
            self._poll_and_process_job_status()
        except Exception as e:
            logger.debug(
                f'{log_prefix(self.executor_id)} - The final status sweep '
                f'did not go through: {e}'
            )

        self._print_status_log(force=True)
        self._shutdown_ready_pool()
        logger.debug(
            f'{log_prefix(self.executor_id)} - Storage job monitor finished'
        )
