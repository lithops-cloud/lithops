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
import queue

from lithops.monitoring.backends import load_backend_attr, resolve_backend
from lithops.utils import log_prefix

logger = logging.getLogger(__name__)


class JobMonitor:
    """
    Owns the monitor thread of one executor, and picks the implementation
    that matches the configured monitoring backend.

    ``config`` is the full Lithops config. The selected backend extracts
    the section it needs through :meth:`Monitor.prepare_config`.
    ``backend`` overrides ``config['lithops']['monitoring']`` when set, and
    ``queue_name`` the queue the monitor reads from, which the remote
    invoker needs so as not to consume what the client is waiting for.
    """

    #: How long stop() waits for the monitor thread to wind down. A poll
    #: blocks for PollingMessageMonitor.POLL_TIMEOUT at most, so a healthy
    #: monitor is gone well inside this; the rest is slack for a consumer
    #: that has to unwind a connection, and the cap on how long a wedged
    #: one may hold up the exit of the executor
    STOP_TIMEOUT = 10

    def __init__(
            self,
            executor_id,
            internal_storage,
            config=None,
            backend=None,
            queue_name=None,
    ):
        self.executor_id = executor_id
        self.internal_storage = internal_storage
        self.storage_config = internal_storage.get_storage_config()
        self.storage_backend = internal_storage.backend
        self.config = config
        self.queue_name = queue_name
        self.type = resolve_backend(config, backend)

        self.token_bucket_q = queue.Queue()
        self.monitor = None
        self.job_chunksize = {}

        self.MonitorClass = load_backend_attr(
            self.type, 'MonitoringBackend'
        )

    def start(self, fs, job_id=None, chunksize=None, generate_tokens=False):
        """
        Tracks a new set of futures, spawning the monitor thread unless a
        live one can take them over
        """
        if job_id:
            self.job_chunksize[job_id] = chunksize

        if not self.monitor or self._thread_finished():
            self._spawn_monitor(generate_tokens)
        elif generate_tokens:
            self.monitor.generate_tokens = True

        self.monitor.add_futures(fs)

        if not self.monitor.is_alive():
            self.monitor.start()

    def prepare(self):
        """
        Creates backend resources (queues, keys) before workers are
        invoked, so the first status is not published into nowhere.
        """
        if self.monitor is None:
            self._spawn_monitor(generate_tokens=False)

    def _spawn_monitor(self, generate_tokens):
        # A monitor that was stopped is replaced, never revived, and the old
        # thread is waited for first: two threads reading the same queue
        # would split the statuses between them, and the one on its way out
        # takes what it reads to the grave
        self._join_monitor()
        monitor_config = self.MonitorClass.prepare_config(
            self.config, self.internal_storage
        )
        if self.queue_name:
            # Copied rather than mutated: prepare_config() may well have
            # handed back the caller's own config section
            monitor_config = dict(monitor_config)
            monitor_config['queue_name'] = self.queue_name
        self.monitor = self.MonitorClass(
            executor_id=self.executor_id,
            internal_storage=self.internal_storage,
            token_bucket_q=self.token_bucket_q,
            job_chunksize=self.job_chunksize,
            generate_tokens=generate_tokens,
            config=monitor_config
        )

    def _thread_finished(self):
        """
        Whether the current monitor is spent: it ran and exited, or it was
        asked to stop. A stopped one is not reused, since its loop would
        return on the next round without picking the new futures up
        """
        if self.monitor is None:
            return False
        if not self.monitor.should_run:
            return True
        return (
            self.monitor.ident is not None
            and not self.monitor.is_alive()
        )

    def _join_monitor(self):
        """
        Waits for the monitor thread to wind down, and says whether it did.

        Only the paths that replace the monitor or delete what it consumes
        from have to wait; a plain stop() leaves the thread to exit on its
        own, so that a wait() whose futures are all done returns at once
        """
        if self.monitor is None or not self.monitor.is_alive():
            return True
        self.monitor.join(timeout=self.STOP_TIMEOUT)
        if self.monitor.is_alive():
            logger.warning(
                f'{log_prefix(self.executor_id)} - The {self.type} job '
                f'monitor did not stop within {self.STOP_TIMEOUT} seconds'
            )
            return False
        return True

    def is_alive(self):
        """
        Tells whether the monitor thread is still running. False when none
        was ever started, which is what an executor asked to wait on futures
        it did not invoke itself has
        """
        return self.monitor is not None and self.monitor.is_alive()

    def remove(self, fs):
        """
        Stops tracking a set of futures
        """
        if self.monitor and self.monitor.is_alive():
            self.monitor.remove_futures(fs)

    def stop(self):
        """
        Asks the monitor thread to exit, without waiting for it.

        This runs after every wait() whose futures are all done, not only at
        shutdown, and a backend whose read blocks for a poll interval would
        hold the caller up every single time. The thread is a daemon and
        winds down on its own; cleanup() and the next start() are the two
        that wait for it, because they replace it or delete what it reads
        from. Queues stay until cleanup().
        """
        if self.monitor is None:
            return
        self.monitor.stop()

    def cleanup(self):
        """
        Deletes queues, keys or other backend resources of this executor,
        once the thread that consumes from them has wound down
        """
        if self.monitor is None:
            return
        self.monitor.stop()
        if not self._join_monitor():
            logger.warning(
                f'{log_prefix(self.executor_id)} - Deleting the {self.type} '
                'monitoring resources while it is still reading from them'
            )
        self.monitor.cleanup()
