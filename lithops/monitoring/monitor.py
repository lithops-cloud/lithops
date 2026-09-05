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
import logging
import pickle
import sys
import threading
import time
from typing import Any, Dict, Optional

from tblib import pickling_support

from lithops.utils import _future_id, log_prefix, monitoring_queue_name

# _future_timeout_checker() pickles sys.exc_info() so that the client can
# re-raise a real traceback for a worker that never reported back
pickling_support.install()

logger = logging.getLogger(__name__)

LOG_INTERVAL = 30  # Print monitor debug every LOG_INTERVAL seconds

# Package every monitoring backend lives under. A Monitor subclass defined
# there is a backend, and the contract is checked against it
BACKENDS_PACKAGE = 'lithops.monitoring.backends'


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


def is_named_error(exc, *names):
    """
    Tells whether an exception is one of the named cloud SDK errors, without
    importing the SDK that defines them. The whole inheritance chain is
    checked, so a subclass of the named error matches too
    """
    return any(
        klass.__name__ in names for klass in type(exc).__mro__
    )


def _backend_package_of(cls) -> Optional[str]:
    """
    Name of the backend package a class is defined in, or None when it does
    not live under :data:`BACKENDS_PACKAGE`
    """
    prefix = f'{BACKENDS_PACKAGE}.'
    module = cls.__module__ or ''
    if not module.startswith(prefix):
        return None
    return module[len(prefix):].split('.')[0]


class Monitor(threading.Thread):
    """
    Base class of the background threads that follow the futures of an
    executor and move them along their states as their status arrives.

    A monitoring backend is a subclass of this class (or of
    :class:`MessageMonitor` / :class:`PollingMessageMonitor`). It must
    implement ``run()`` — or ``_receive_messages()`` when it subclasses
    :class:`PollingMessageMonitor` — and may override ``stop()`` and
    ``prepare_config()``. The class is loaded from
    ``lithops.monitoring.backends.<name>`` as ``MonitoringBackend``.

    ``backend_name`` names the configuration section the backend reads, and
    is derived from the package the class lives in so that the two cannot
    drift apart.
    """

    #: Config section this backend reads, and the name ``monitoring:``
    #: selects it by. Filled in from the package name for backends
    backend_name = None

    #: How many statuses that arrived before their future may be held
    MAX_HELD_STATUS = 100_000

    def __init_subclass__(cls, abstract: bool = False, **kwargs):
        """
        Checks the backend contract as soon as the class is defined, so that
        a backend that does not hold up its end fails at import rather than
        halfway through a job.

        ``abstract=True`` opts a helper class out of the check
        """
        super().__init_subclass__(**kwargs)

        package = _backend_package_of(cls)
        if abstract or package is None:
            return

        if cls.backend_name is None:
            cls.backend_name = package
        elif cls.backend_name != package:
            raise TypeError(
                f"{cls.__name__}.backend_name is '{cls.backend_name}' but the "
                f"backend package is '{package}'. The two name the same "
                f"thing: the config section, and the value of 'monitoring:'"
            )

        polling = globals().get('PollingMessageMonitor')
        implements_run = cls.run is not threading.Thread.run
        implements_receive = polling is not None and issubclass(
            cls, polling
        ) and cls._receive_messages is not polling._receive_messages
        if not implements_run and not implements_receive:
            raise TypeError(
                f'{cls.__name__} implements neither run() nor '
                f'_receive_messages(). A monitoring backend has to consume '
                f'statuses one way or the other'
            )

    def __init__(self, executor_id,
                 internal_storage,
                 token_bucket_q,
                 job_chunksize,
                 generate_tokens,
                 config):

        super().__init__()
        self.executor_id = executor_id
        self.internal_storage = internal_storage
        # Every idle wait of the loop goes through this event rather than
        # time.sleep(), so that stop() ends it at once instead of leaving
        # the caller to wait out a poll interval. stop() is called after
        # every wait() whose futures are all done, not only at shutdown
        self._stopped = threading.Event()
        self.token_bucket_q = token_bucket_q
        self.job_chunksize = job_chunksize
        self.generate_tokens = generate_tokens
        self.config = config
        self.daemon = True
        self._cleaned = False

        # Futures are tracked from the client threads that submit jobs and
        # read from the monitor thread. One lock covers the set, the index
        # that finds a future by its call id, and the set of live job ids
        self._futures_lock = threading.RLock()
        self.futures = set()
        self._futures_by_id = {}
        self.present_jobs = set()

        # vars for _generate_tokens
        self.workers_done = set()
        self.callids_done_worker = {}
        # vars for MessageMonitor._hold_status
        self._held_status = {}
        self._held_lock = threading.Lock()
        self._held_overflow_logged = False
        self._held_may_match = False
        # When a status last arrived. A channel that is delivering has
        # nothing for the storage sweep to recover
        self._last_message_tstamp = time.time()
        # Re-entrancy guard of _apply_held_status(), per thread: the monitor
        # thread and the threads that submit jobs both get there
        self._applying_held = threading.local()
        # vars for _print_status_log
        self._last_status_counts = None
        self._last_status_log_time = 0.0

    @property
    def should_run(self):
        """Whether the loop should keep going. False once stop() was called"""
        return not self._stopped.is_set()

    @should_run.setter
    def should_run(self, value):
        if value:
            self._stopped.clear()
        else:
            self._stopped.set()

    def sleep(self, seconds):
        """
        Waits, unless the monitor is stopped first. Returns False when the
        wait was cut short by stop()
        """
        if seconds <= 0:
            return self.should_run
        return not self._stopped.wait(seconds)

    @classmethod
    def prepare_config(
            cls,
            config: Optional[Dict[str, Any]],
            internal_storage,
    ) -> Dict[str, Any]:
        """
        Returns the dict this backend's ``__init__`` expects, extracted from
        the full Lithops config.

        Backends whose settings live in the config section named after them
        (``rabbitmq``, ``aws_sqs``, ...) can keep this default.
        """
        if not config:
            return {}
        return config.get(cls.backend_name) or {}

    def monitoring_queue_name(self):
        """
        Name of the queue, topic or key this monitor reads from.

        Derived from the executor id, unless the config names one: a
        monitor that follows the calls of an executor it does not own, as
        the remote invoker does, needs its own queue so that it does not
        take the messages the owner is waiting for
        """
        named = (self.config or {}).get('queue_name')
        return named or monitoring_queue_name(self.executor_id)

    def add_futures(self, fs):
        """
        Extends the current thread list of futures to track
        """
        with self._futures_lock:
            self.futures.update(fs)
            for future in fs:
                self._futures_by_id[_future_id(future)] = future
            # Nothing held can start matching unless futures were added, so
            # this is what keeps _take_held_status() from walking the held
            # set once per message while a nested job piles statuses up
            self._held_may_match = True
            # Rebound rather than mutated, so that a reader that got hold of
            # the set before this call keeps iterating a set of its own
            self.present_jobs = self.present_jobs | {
                future.job_id for future in fs
            }

    def remove_futures(self, fs):
        """
        Remove from the current thread a list of futures
        """
        self._print_status_log()
        with self._futures_lock:
            self.futures.difference_update(fs)
            for future in fs:
                future_id = _future_id(future)
                if self._futures_by_id.get(future_id) is future:
                    del self._futures_by_id[future_id]
            self.present_jobs = {future.job_id for future in self.futures}

    def tracked_futures(self):
        """
        A snapshot of the futures being tracked, safe to iterate while other
        threads add or remove some
        """
        with self._futures_lock:
            return tuple(self.futures)

    def job_ids(self):
        """
        A snapshot of the ids of the jobs that still have futures to track
        """
        with self._futures_lock:
            return set(self.present_jobs)

    def future_by_id(self, future_id):
        """
        The tracked future a call status belongs to, or None when it is not
        tracked (yet)
        """
        with self._futures_lock:
            return self._futures_by_id.get(future_id)

    def stop(self):
        """
        Asks the monitor thread to exit. Does not delete queues or keys:
        the executor may still map() again.

        Returns as soon as the thread has been asked; JobMonitor.cleanup()
        is what waits for it, right before the resources it consumes from
        are deleted. Override to cut short a blocking read that this alone
        cannot reach (close a connection, cancel a consumer).
        """
        self.should_run = False

    def _create_resources(self):
        """
        Creates the queues, topics or keys this monitor consumes from.
        Called by the backend once its client is built.
        """

    def _delete_resources(self):
        """
        Deletes what :meth:`_create_resources` created. Called once,
        through cleanup().
        """

    def cleanup(self):
        """
        Deletes queues, keys or other backend resources that must not
        outlive the executor. Called from clean() and executor shutdown.
        Idempotent: a second call is a no-op.
        """
        if self._cleaned:
            return
        self._cleaned = True
        self._delete_resources()

    def _all_ready(self):
        """
        Checks if all futures are ready, success or done
        """
        return all(_is_finished(f) for f in self.tracked_futures())

    def _check_new_futures(self, call_status, f):
        """
        Checks if a function returned new futures to track
        """
        if 'new_futures' not in call_status:
            return False

        f._set_futures(call_status)
        self.add_futures(f._new_futures)
        logger.debug(
            f'{log_prefix(self.executor_id)} - Received {len(f._new_futures)} '
            'new function Futures to track'
        )

        return True

    def _future_timeout_checker(self, futures=None):
        """
        Checks if running futures exceeded the timeout
        """
        current_time = time.time()
        if futures is None:
            futures = self.tracked_futures()
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

    def _print_status_log(self, force=False):
        """
        Logs pending/running/done counts.

        Redis and RabbitMQ see a change on every message, so this is
        throttled: the first snapshot, then one every LOG_INTERVAL seconds
        while the job is running, and one more when it finishes or when
        ``force`` is set on shutdown.
        """
        futures = self.tracked_futures()
        if not futures:
            return

        callids_pending = callids_running = callids_done = 0
        for fut in futures:
            if fut.invoked:
                callids_pending += 1
            if fut.running:
                callids_running += 1
            if _is_finished(fut):
                callids_done += 1
        counts = (callids_pending, callids_running, callids_done)

        now = time.time()
        changed = counts != self._last_status_counts
        still_working = callids_done < len(futures)
        elapsed = now - self._last_status_log_time > LOG_INTERVAL
        should_log = (
            self._last_status_counts is None
            or (changed and (not still_working or force))
            or (still_working and elapsed)
        )

        self._last_status_counts = counts
        if not should_log:
            return

        self._last_status_log_time = now
        logger.debug(
            f'{log_prefix(self.executor_id)} - Pending: '
            f'{callids_pending} - Running: {callids_running} - '
            f'Done: {callids_done}'
        )


class MessageMonitor(Monitor, abstract=True):
    """
    Monitor for backends that receive one call-status message at a time
    (RabbitMQ, SQS, Pub/Sub, ...).

    The backend only has to deliver each JSON status payload to
    :meth:`_apply_status_message`; tagging futures and handing tokens
    back to the invoker live here.
    """

    def _hold_status(self, call_status):
        """
        Keeps a status whose future is not tracked yet.

        A nested executor publishes the statuses of its own calls to the
        queue of every executor up the chain, and those can arrive before
        the status that tells this monitor the nested futures exist. A
        message is read once, so dropping it here would leave a future
        running for ever. Held by call id, so an __end__ supersedes the
        __init__ of the same call
        """
        with self._held_lock:
            self._held_status[_status_id(call_status)] = call_status
            self._held_may_match = True
            if len(self._held_status) <= self.MAX_HELD_STATUS:
                return
            # A status whose future never shows up would be held for the
            # whole life of the executor, so the oldest ones give way. A
            # dict keeps insertion order, so the first key is the oldest
            while len(self._held_status) > self.MAX_HELD_STATUS:
                del self._held_status[next(iter(self._held_status))]
            if not self._held_overflow_logged:
                self._held_overflow_logged = True
                logger.warning(
                    f'{log_prefix(self.executor_id)} - More than '
                    f'{self.MAX_HELD_STATUS} call statuses arrived for '
                    'futures that are not tracked; dropping the oldest'
                )

    def _take_held_status(self):
        """
        Removes and returns the held statuses whose future is now tracked.

        Also forgets the ones whose future finished some other way, such
        as an expired execution timeout, so they are not held for ever
        """
        with self._held_lock:
            if not self._held_status or not self._held_may_match:
                return ()
            self._held_may_match = False
            ready = []
            for future_id in list(self._held_status):
                future = self.future_by_id(future_id)
                if future is None:
                    continue
                call_status = self._held_status.pop(future_id)
                if not _is_finished(future):
                    ready.append(call_status)
            return tuple(ready)

    def _apply_held_status(self):
        """
        Applies the statuses that arrived before their future did.

        The statuses leave the held set before any of them is applied, and
        the lock is not held while applying. Applying one can reveal further
        futures, whose own held statuses this then picks up, so the work is
        drained in a loop rather than by calling back into here: a chain of
        nested jobs would otherwise recurse once per held status
        """
        local = self._applying_held
        if getattr(local, 'busy', False):
            return
        local.busy = True
        try:
            while True:
                batch = self._take_held_status()
                if not batch:
                    return
                for call_status in batch:
                    self._apply_status_message(call_status)
        finally:
            local.busy = False

    def add_futures(self, fs):
        """
        Tracks new futures, applying any status that beat them here
        """
        super().add_futures(fs)
        self._apply_held_status()

    def _tag_future_as_running(self, call_status):
        """
        Assigns a call_status to its future. Returns whether the future is
        tracked, which is what tells the caller the status can be dropped
        """
        future = self.future_by_id(_status_id(call_status))
        if future is None:
            return False
        if not _is_started(future):
            future._set_running(call_status)
        return True

    def _tag_future_as_ready(self, call_status):
        """
        Tags a future as ready based on call_status. Returns whether the
        future is tracked
        """
        future = self.future_by_id(_status_id(call_status))
        if future is None:
            return False
        if not _is_finished(future):
            if not self._check_new_futures(call_status, future):
                future._set_ready(call_status)
        return True

    def _generate_tokens(self, call_status):
        """
        Hands a token back to the invoker once a whole worker is free.

        The call ids of a worker are kept in a set: a message service that
        redelivers can hand the same __end__ over twice, and counting it
        twice would either release a token early or push the count past the
        chunksize and never release one at all
        """
        if not self.generate_tokens or not self.should_run:
            return

        chunksize = call_status.get('chunksize')
        if chunksize is None:
            chunksize = self.job_chunksize.get(call_status['job_id'])
        if chunksize is None:
            return

        call_id = _status_id(call_status)
        worker_id = call_status['activation_id']
        done_for_worker = self.callids_done_worker.setdefault(worker_id, set())
        done_for_worker.add(call_id)

        if (
            worker_id not in self.workers_done
            and len(done_for_worker) >= chunksize
        ):
            self.workers_done.add(worker_id)
            if self.should_run:
                self.token_bucket_q.put('#')

    def _apply_status_message(self, call_status):
        """
        Applies one worker status payload to its future, holding it back
        when the future it belongs to is not tracked yet
        """
        # A status arriving is the proof the channel works, which is what
        # tells the storage sweep it has nothing to look for
        self._last_message_tstamp = time.time()
        if call_status['type'] == '__init__':
            if not self._tag_future_as_running(call_status):
                self._hold_status(call_status)
        elif call_status['type'] == '__end__':
            if self._tag_future_as_ready(call_status):
                self._generate_tokens(call_status)
            else:
                self._hold_status(call_status)

    def _storage_sweep(self):
        """
        Picks up from the Object Storage the statuses whose message never
        arrived.

        A message service delivers a status at most once (RabbitMQ acks on
        delivery, a Redis BLPOP removes it), so a status can be lost. The
        worker also writes every __end__ to the storage, and this is what
        reads it back: without it a lost __end__ turns into a bogus
        execution timeout, and losing both statuses of a call hangs wait()
        for ever, since the timeout checker only looks at running futures
        """
        if self.internal_storage is None:
            return 0

        pending = [f for f in self.tracked_futures() if not _is_finished(f)]
        if not pending:
            return 0

        _running, callids_done = self.internal_storage.get_job_status(
            self.executor_id, job_ids=self.job_ids()
        )
        if not callids_done:
            return 0

        recovered = 0
        for future in pending:
            future_id = _future_id(future)
            if future_id not in callids_done or _is_finished(future):
                continue
            call_status = self.internal_storage.get_call_status(*future_id)
            future._status_query_count += 1
            if not call_status:
                continue
            if not self._check_new_futures(call_status, future):
                future._set_ready(call_status)
            recovered += 1
            if self.generate_tokens and 'activation_id' in call_status:
                self._generate_tokens(call_status)

        if recovered:
            logger.debug(
                f'{log_prefix(self.executor_id)} - Recovered {recovered} '
                f'call status(es) from the storage, whose {self.backend_name} '
                'message never arrived'
            )
        return recovered


class PollingMessageMonitor(MessageMonitor, abstract=True):
    """
    Pulls status messages with a timeout so the same loop can expire
    futures and notice stop(). Redis, SQS, Pub/Sub and Azure Queue use
    this; RabbitMQ keeps its own blocking AMQP consumer.
    """

    POLL_TIMEOUT = 2

    #: How long the channel has to have been quiet before the statuses the
    #: workers left in the storage are read back for the futures whose
    #: message never arrived. Zero disables it
    STORAGE_SWEEP_INTERVAL = 60

    #: The sweep backs off to this while it keeps finding nothing
    MAX_SWEEP_INTERVAL = 600

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # How long the channel has to be quiet before the next sweep. Grows
        # while the sweeps keep finding nothing
        self._sweep_interval = self.STORAGE_SWEEP_INTERVAL

    def _receive_messages(self, timeout):
        """Yields JSON strings. Empty if nothing arrived."""
        raise NotImplementedError

    def _close_receiver(self):
        """
        Releases whatever _receive_messages() opened. Called on the monitor
        thread once its loop is done, so a backend whose client must be used
        from a single thread can close it from the thread that used it
        """

    def _poll_once(self):
        """
        Receives and applies one batch of status messages, then sleeps off
        whatever is left of the poll budget when nothing arrived.

        The wait belongs here rather than in _receive_messages(): a
        backend without server-side long polling (Azure Queue) returns
        right away on an empty queue, and so does one that keeps failing
        (unreachable service, wrong credentials), either of which would
        otherwise turn this loop into a spin.
        """
        poll_t = time.time()
        received = False
        try:
            for payload in self._receive_messages(self.POLL_TIMEOUT):
                self._apply_status_message(json.loads(payload))
                # A status can name new futures whose own statuses were
                # read earlier and held back. Applied per message rather
                # than per batch, because a backend that only returns once
                # the queue has gone quiet would otherwise sit on them
                self._apply_held_status()
                received = True
        except Exception as e:
            # A failed poll must not take the monitor down with it: nothing
            # else moves the futures along, so wait() would block for ever.
            # The storage sweep is what recovers whatever was lost with it
            if self.should_run:
                logger.error(
                    f'{log_prefix(self.executor_id)} - Error during '
                    f'monitor: {e}',
                    exc_info=True,
                )
        if received:
            return
        remaining = self.POLL_TIMEOUT - (time.time() - poll_t)
        self.sleep(remaining)

    def _sweep_storage(self, last_sweep):
        """
        Reads the call statuses back from the storage when the channel has
        gone quiet, and returns when that last happened.

        Two things keep this off the critical path of a healthy job. It only
        looks while no status has arrived for a whole interval, since a
        channel that is delivering has nothing to recover; and every sweep
        that finds nothing doubles the wait before the next one, up to
        MAX_SWEEP_INTERVAL, since a long-running job is quiet by nature. A
        sweep lists every status key of every live job, which on a large map
        is a page of listing per thousand calls
        """
        if not self.STORAGE_SWEEP_INTERVAL:
            return last_sweep

        now = time.time()
        if now - self._last_message_tstamp < self._sweep_interval:
            return last_sweep
        if now - last_sweep < self._sweep_interval:
            return last_sweep

        try:
            recovered = self._storage_sweep()
        except Exception as e:
            if self.should_run:
                logger.debug(
                    f'{log_prefix(self.executor_id)} - Could not read the '
                    f'call statuses back from the storage: {e}'
                )
            recovered = 0

        if recovered:
            self._sweep_interval = self.STORAGE_SWEEP_INTERVAL
        else:
            self._sweep_interval = min(
                self._sweep_interval * 2, self.MAX_SWEEP_INTERVAL
            )
        return now

    def run(self):
        logger.debug(
            f'{log_prefix(self.executor_id)} - Starting '
            f'{self.backend_name} job monitor'
        )
        # Both sweeps walk every tracked future, so they run on a clock
        # rather than once per loop: a backend that hands over one message
        # at a time would otherwise turn a map of n calls into n*n work
        last_sweep = time.time()
        self._sweep_interval = self.STORAGE_SWEEP_INTERVAL
        last_check = 0.0
        try:
            # Stay up until stop(), like StorageMonitor, so wait() does not
            # spawn a second thread (and a second cleanup) once every future
            # is ready. New futures of a later map() are added to this one.
            while self.should_run:
                now = time.time()
                if now - last_check >= self.POLL_TIMEOUT:
                    last_check = now
                    self._print_status_log()
                    self._future_timeout_checker()
                    last_sweep = self._sweep_storage(last_sweep)
                self._poll_once()
        finally:
            self._print_status_log(force=True)
            try:
                self._close_receiver()
            except Exception:
                logger.debug(
                    f'{log_prefix(self.executor_id)} - Could not close the '
                    f'{self.backend_name} receiver',
                    exc_info=True,
                )
            logger.debug(
                f'{log_prefix(self.executor_id)} - '
                f'{self.backend_name} job monitor finished'
            )
