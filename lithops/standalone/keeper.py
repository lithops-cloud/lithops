import json
import os
import time
import threading
import logging
from lithops.standalone import StandaloneHandler
from lithops.constants import SA_DATA_FILE, JOBS_DIR
from lithops.standalone.utils import JobStatus


logger = logging.getLogger(__name__)


class BudgetKeeper(threading.Thread):
    """
    BudgetKeeper class used to automatically stop the VM instance
    """
    def __init__(self, config, stop_callback=None):
        threading.Thread.__init__(self)
        self.last_usage_time = time.time()

        self.standalone_config = config
        self.stop_callback = stop_callback
        self.auto_dismantle = config['auto_dismantle']
        self.soft_dismantle_timeout = config['soft_dismantle_timeout']
        self.hard_dismantle_timeout = config['hard_dismantle_timeout']
        self.exec_mode = config['exec_mode']

        self.runing = False
        self.jobs = {}

        with open(SA_DATA_FILE, 'r') as ad:
            instance_data = json.load(ad)

        self.standalone_handler = StandaloneHandler(self.standalone_config)
        self.instance = self.standalone_handler.backend.get_instance(**instance_data)

        logger.debug(f"Starting BudgetKeeper for {self.instance.name} ({self.instance.private_ip}), "
                     f"instance ID: {self.instance.instance_id}")
        logger.debug(f"Delete {self.instance.name} on dismantle: {self.instance.delete_on_dismantle}")

    def add_job(self, job_key):
        self.last_usage_time = time.time()
        self.jobs[job_key] = JobStatus.RUNNING.value

    def run(self):
        self.runing = True
        jobs_running = False

        logger.debug("BudgetKeeper started")

        if self.auto_dismantle:
            logger.debug('Auto dismantle activated - Soft timeout: {}s, Hard Timeout: {}s'
                         .format(self.soft_dismantle_timeout, self.hard_dismantle_timeout))
        else:
            # If auto_dismantle is deactivated, the VM will be always automatically
            # stopped after hard_dismantle_timeout. This will prevent the VM
            # being started forever due a wrong configuration
            logger.debug(f'Auto dismantle deactivated - Hard Timeout: {self.hard_dismantle_timeout}s')

        while self.runing:
            time_since_last_usage = time.time() - self.last_usage_time

            for job_key in self.jobs.keys():
                done = os.path.join(JOBS_DIR, job_key + '.done')
                if os.path.isfile(done):
                    self.jobs[job_key] = JobStatus.DONE.value

            if len(self.jobs) > 0 and all(value == JobStatus.DONE.value for value in self.jobs.values()) \
               and self.auto_dismantle:

                # here we need to catch a moment when number of running JOBS become zero.
                # when it happens we reset countdown back to soft_dismantle_timeout
                if jobs_running:
                    jobs_running = False
                    self.last_usage_time = time.time()

                time_since_last_usage = time.time() - self.last_usage_time

                time_to_dismantle = int(self.soft_dismantle_timeout - time_since_last_usage)
            else:
                time_to_dismantle = int(self.hard_dismantle_timeout - time_since_last_usage)
                jobs_running = True

            if time_to_dismantle > 0:
                logger.debug(f"Time to dismantle: {time_to_dismantle} seconds")
                check_interval = min(60, max(time_to_dismantle / 10, 1))
                time.sleep(check_interval)
            else:
                self.stop_instance()

    def stop_instance(self):
        logger.debug("Dismantling setup")

        self.stop_callback() if self.stop_callback is not None else None

        try:
            self.instance.stop()
            self.runing = False
        except Exception as e:
            logger.debug(f"Dismantle error {e}")
            time.sleep(5)
