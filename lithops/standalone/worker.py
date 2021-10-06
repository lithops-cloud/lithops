#
# Copyright Cloudlab URV 2020
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
import logging
import time
import json
import requests

from lithops.constants import LITHOPS_TEMP_DIR, STANDALONE_LOG_FILE, JOBS_DIR,\
    STANDALONE_SERVICE_PORT, STANDALONE_CONFIG_FILE, STANDALONE_INSTALL_DIR
from lithops.localhost.localhost import LocalhostHandler
from lithops.utils import verify_runtime_name, setup_lithops_logger
from lithops.standalone.keeper import BudgetKeeper

setup_lithops_logger(logging.DEBUG, filename=STANDALONE_LOG_FILE)
logger = logging.getLogger('lithops.standalone.worker')


STANDALONE_CONFIG = None
BUDGET_KEEPER = None
LOCALHOST_HANDLER = {}


def wait_job_completed(job_key):
    """
    Waits until the current job is completed
    """
    global BUDGET_KEEPER

    done = os.path.join(JOBS_DIR, job_key+'.done')
    while True:
        if os.path.isfile(done):
            os.remove(done)
            BUDGET_KEEPER.jobs[job_key] = 'done'
            break
        time.sleep(1)


def run_worker(master_ip, job_key):
    """
    Run a job
    """
    global BUDGET_KEEPER

    pull_runtime = STANDALONE_CONFIG.get('pull_runtime', False)
    localhos_handler = LocalhostHandler({'pull_runtime': pull_runtime})

    while True:
        url = 'http://{}:{}/get-task/{}'.format(master_ip, STANDALONE_SERVICE_PORT, job_key)
        logger.info('Getting task from {}'.format(url))

        try:
            resp = requests.get(url)
        except:
            time.sleep(1)
            continue

        if resp.status_code != 200:
            if STANDALONE_CONFIG.get('exec_mode') == 'reuse':
                time.sleep(1)
                continue
            else:
                logger.info('All tasks completed'.format(url))
                return

        job_payload = resp.json()
        logger.info(job_payload)
        logger.info('Got tasks {}'.format(', '.join(job_payload['call_ids'])))

        try:
            runtime = job_payload['runtime_name']
            verify_runtime_name(runtime)
        except Exception:
            return

        BUDGET_KEEPER.last_usage_time = time.time()
        BUDGET_KEEPER.update_config(job_payload['config']['standalone'])
        BUDGET_KEEPER.jobs[job_payload['job_key']] = 'running'

        try:
            localhos_handler.invoke(job_payload)
        except Exception as e:
            logger.error(e)

        wait_job_completed(job_payload['job_key'])


def main():
    global STANDALONE_CONFIG
    global BUDGET_KEEPER

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    with open(STANDALONE_CONFIG_FILE, 'r') as cf:
        STANDALONE_CONFIG = json.load(cf)

    vm_data_file = os.path.join(STANDALONE_INSTALL_DIR, 'access.data')
    with open(vm_data_file, 'r') as ad:
        vm_data = json.load(ad)
        master_ip = vm_data['master_ip']
        job_key = vm_data['job_key']

    BUDGET_KEEPER = BudgetKeeper(STANDALONE_CONFIG)
    BUDGET_KEEPER.start()

    if STANDALONE_CONFIG.get('exec_mode') == 'reuse':
        job_key = 'all'

    run_worker(master_ip, job_key)
    logger.info('Finished')

    try:
        # Try to stop the VM once no more pending tasks to run
        BUDGET_KEEPER.vm.stop()
    except Exception:
        pass


if __name__ == '__main__':
    main()
