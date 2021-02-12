import json
import os
import time
import threading
import logging
from lithops.standalone.standalone import StandaloneHandler
from lithops.constants import STANDALONE_INSTALL_DIR, JOBS_DIR


logger = logging.getLogger(__name__)


class BudgetKeeper(threading.Thread):
    """
    BudgetKeeper class used to automatically stop the VM instance
    """
    def __init__(self, config):
        threading.Thread.__init__(self)
        self.last_usage_time = time.time()

        self.standalone_config = config
        self.jobs = {}

        access_data = os.path.join(STANDALONE_INSTALL_DIR, 'access.data')
        with open(access_data, 'r') as ad:
            vsi_details = json.load(ad)
        self.instance_name = vsi_details['instance_name']
        self.ip_address = vsi_details['ip_address']
        self.instance_id = vsi_details['instance_id']

        logger.info(("Starting BudgetKeeper for {} ({}), instance ID: {}"
                     .format(self.instance_name, self.ip_address, self.instance_id)))

        self.standalone_handler = StandaloneHandler(self.standalone_config)
        vsi = self.standalone_handler.backend.create_worker(self.instance_name)
        vsi.ip_address = self.ip_address
        vsi.instance_id = self.instance_id
        vsi.delete_on_dismantle = False if 'master' in self.instance_name else True

    def update_config(self, config):
        self.standalone_config.update(config)
        self.standalone_handler.auto_dismantle = config['auto_dismantle']
        self.standalone_handler.soft_dismantle_timeout = config['soft_dismantle_timeout']
        self.standalone_handler.hard_dismantle_timeout = config['hard_dismantle_timeout']

    def run(self):
        runing = True
        jobs_running = False

        logger.info("BudgetKeeper started")

        if self.standalone_handler.auto_dismantle:
            logger.info('Auto dismantle activated - Soft timeout: {}s, Hard Timeout: {}s'
                        .format(self.standalone_handler.soft_dismantle_timeout,
                                self.standalone_handler.hard_dismantle_timeout))
        else:
            # If auto_dismantle is deactivated, the VM will be always automatically
            # stopped after hard_dismantle_timeout. This will prevent the VM
            # being started forever due a wrong configuration
            logger.info('Auto dismantle deactivated - Hard Timeout: {}s'
                        .format(self.standalone_handler.hard_dismantle_timeout))

        while runing:
            time_since_last_usage = time.time() - self.last_usage_time
            check_interval = self.standalone_handler.soft_dismantle_timeout / 10
            for job_key in self.jobs.keys():
                done = os.path.join(JOBS_DIR, job_key+'.done')
                if os.path.isfile(done):
                    self.jobs[job_key] = 'done'
            if len(self.jobs) > 0 and all(value == 'done' for value in self.jobs.values()) \
               and self.standalone_handler.auto_dismantle:

                # here we need to catch a moment when number of running JOBS become zero.
                # when it happens we reset countdown back to soft_dismantle_timeout
                if jobs_running:
                    jobs_running = False
                    self.last_usage_time = time.time()
                    time_since_last_usage = time.time() - self.last_usage_time

                time_to_dismantle = int(self.standalone_handler.soft_dismantle_timeout - time_since_last_usage)
            else:
                time_to_dismantle = int(self.standalone_handler.hard_dismantle_timeout - time_since_last_usage)
                jobs_running = True

            if time_to_dismantle > 0:
                logger.info("Time to dismantle: {} seconds".format(time_to_dismantle))
                time.sleep(check_interval)
            else:
                logger.info("Dismantling setup")
                try:
                    self.standalone_handler.dismantle()
                    runing = False
                except Exception as e:
                    logger.info("Dismantle error {}".format(e))
