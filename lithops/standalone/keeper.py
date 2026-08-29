#
# (C) Copyright Cloudlab URV 2020
# (C) Copyright IBM Corp. 2023
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
import time
import threading
import logging
from typing import Any, Callable, Dict, Optional

from lithops.standalone import StandaloneHandler
from lithops.constants import JOBS_DIR
from lithops.standalone.utils import JobStatus


logger = logging.getLogger(__name__)


class BudgetKeeper(threading.Thread):
    """
    Background thread that stops the VM instance it runs on once it has been
    idle for long enough, so that a forgotten or misconfigured run does not
    keep paying for it
    """

    def __init__(
        self,
        config: Dict[str, Any],
        instance_data: Dict[str, Any],
        stop_callback: Optional[Callable] = None,
        delete_callback: Optional[Callable] = None,
    ):
        super().__init__()
        self.last_usage_time = time.time()

        self.standalone_config = config
        self.stop_callback = stop_callback
        self.delete_callback = delete_callback
        self.auto_dismantle = config['auto_dismantle']
        self.soft_dismantle_timeout = config['soft_dismantle_timeout']
        self.hard_dismantle_timeout = config['hard_dismantle_timeout']
        self.exec_mode = config['exec_mode']

        self.running = False
        self.jobs = {}
        self.time_to_dismantle = self.hard_dismantle_timeout

        self.standalone_handler = StandaloneHandler(self.standalone_config)
        self.instance = self.standalone_handler.backend.get_instance(**instance_data)

        logger.debug(
            f"Starting BudgetKeeper for {self.instance.name} "
            f"({self.instance.private_ip}), instance ID: {self.instance.instance_id}"
        )
        logger.debug(
            f"Delete {self.instance.name} on dismantle: "
            f"{self.instance.delete_on_dismantle}"
        )

    def get_time_to_dismantle(self):
        """Returns the seconds left before the instance is stopped"""
        return self.time_to_dismantle

    def add_job(self, job_key):
        """Marks a job as running, which pushes the countdown forward"""
        self.last_usage_time = time.time()
        self.jobs[job_key] = JobStatus.RUNNING.value

    def set_job_done(self, job_key):
        """Marks a job as done, which starts the idle countdown"""
        self.last_usage_time = time.time()
        self.jobs[job_key] = JobStatus.DONE.value

    def _all_jobs_done(self):
        """True when there has been at least one job and none is running"""
        return bool(self.jobs) and all(
            status == JobStatus.DONE.value for status in self.jobs.values()
        )

    def _mark_finished_jobs(self):
        """
        Marks as done the jobs whose runner left a done file behind. Iterates
        over a snapshot, because the service adds jobs from its own threads
        """
        for job_key in list(self.jobs.keys()):
            done_file = os.path.join(JOBS_DIR, job_key + '.done')
            if os.path.isfile(done_file):
                self.jobs[job_key] = JobStatus.DONE.value

    def _log_dismantle_settings(self):
        """Reports the timeouts the countdown will use"""
        if self.auto_dismantle:
            logger.debug(
                f'Auto dismantle activated - Soft timeout: '
                f'{self.soft_dismantle_timeout}s, Hard Timeout: '
                f'{self.hard_dismantle_timeout}s'
            )
        else:
            # If auto_dismantle is deactivated, the VM will be always automatically
            # stopped after hard_dismantle_timeout. This will prevent the VM
            # being started forever due a wrong configuration
            logger.debug(
                f'Auto dismantle deactivated - '
                f'Hard Timeout: {self.hard_dismantle_timeout}s'
            )

    def run(self):
        """
        Counts down to the moment the instance is stopped, for as long as
        nothing pushes the countdown forward
        """
        self.running = True
        jobs_running = False

        logger.debug("BudgetKeeper started")
        self._log_dismantle_settings()

        while self.running:
            time_since_last_usage = time.time() - self.last_usage_time
            self._mark_finished_jobs()

            if self._all_jobs_done() and self.auto_dismantle:
                # Catch the moment when the number of running jobs becomes zero
                # and reset the countdown back to soft_dismantle_timeout.
                if jobs_running:
                    jobs_running = False
                    self.last_usage_time = time.time()

                time_since_last_usage = time.time() - self.last_usage_time
                self.time_to_dismantle = int(
                    self.soft_dismantle_timeout - time_since_last_usage
                )
            else:
                self.time_to_dismantle = int(
                    self.hard_dismantle_timeout - time_since_last_usage
                )
                jobs_running = True

            if self.time_to_dismantle > 0:
                logger.debug(
                    f"Time to dismantle: {self.time_to_dismantle} seconds"
                )
                check_interval = min(60, max(self.time_to_dismantle / 10, 1))
                time.sleep(check_interval)
            else:
                self.stop_instance()

    def stop_instance(self):
        """
        Stops or deletes the instance, telling whoever registered a callback
        first so that it can report the instance is going away
        """
        logger.debug("Dismantling setup")

        if self.instance.delete_on_dismantle:
            if self.delete_callback is not None:
                self.delete_callback()
        elif self.stop_callback is not None:
            self.stop_callback()

        try:
            self.instance.stop()
            self.running = False
        except Exception as e:
            logger.debug(f"Dismantle error {e}")
            time.sleep(5)
