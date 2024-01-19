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
import flask
import requests
from pathlib import Path
from threading import Thread
from functools import partial
from gevent.pywsgi import WSGIServer

from lithops.constants import LITHOPS_TEMP_DIR, SA_LOG_FILE, JOBS_DIR, \
    SA_SERVICE_PORT, SA_CONFIG_FILE, SA_DATA_FILE
from lithops.localhost import LocalhostHandler
from lithops.utils import verify_runtime_name, setup_lithops_logger
from lithops.standalone.keeper import BudgetKeeper
from lithops.standalone.utils import StandaloneMode

log_format = "%(asctime)s\t[%(levelname)s] %(name)s:%(lineno)s -- %(message)s"
setup_lithops_logger(logging.DEBUG, filename=SA_LOG_FILE, log_format=log_format)
logger = logging.getLogger('lithops.standalone.worker')

app = flask.Flask(__name__)

budget_keeper = None
localhos_handler = None
running_job_key = None


@app.route('/ping', methods=['GET'])
def ping():
    bussy = localhos_handler.job_manager if localhos_handler else False
    response = flask.jsonify({'status': 'bussy' if bussy else 'free'})
    response.status_code = 200
    return response


@app.route('/stop/<job_key>', methods=['POST'])
def stop(job_key):
    if job_key == running_job_key:
        logger.debug(f'Received SIGTERM: Stopping job process {job_key}')
        localhos_handler.clear()
        Path(os.path.join(JOBS_DIR, job_key + '.done')).touch()
    response = flask.jsonify({'response': 'cancel'})
    response.status_code = 200
    return response


def notify_stop(master_ip):
    try:
        url = f'http://{master_ip}:{SA_SERVICE_PORT}/worker/status/stop'
        resp = requests.post(url)
        logger.debug("Stop worker: " + str(resp.status_code))
    except Exception as e:
        logger.error(e)


def notify_idle(master_ip):
    try:
        url = f'http://{master_ip}:{SA_SERVICE_PORT}/worker/status/idle'
        resp = requests.post(url)
        logger.debug("Free worker: " + str(resp.status_code))
    except Exception as e:
        logger.error(e)


def wait_job_completed(job_key):
    """
    Waits until the current job is completed
    """
    global budget_keeper

    done = os.path.join(JOBS_DIR, job_key + '.done')
    while True:
        if os.path.isfile(done):
            os.remove(done)
            budget_keeper.jobs[job_key] = 'done'
            break
        time.sleep(1)


def run_worker(
        worker_name,
        master_ip,
        work_queue_name,
        instance_type,
        runtime_name,
        worker_processes,
        exec_mode,
        pull_runtime,
        use_gpu
):
    """
    Run a job
    """
    global budget_keeper
    global localhos_handler
    global running_job_key

    logger.info(f"Starting Worker - Instace type: {instance_type} - Runtime "
                f"name: {runtime_name} - Worker processes: {worker_processes}")

    config = {'runtime': runtime_name, 'pull_runtime': pull_runtime, 'use_gpu': use_gpu}
    localhos_handler = LocalhostHandler(config)
    localhos_handler.init()

    while True:
        url = f'http://{master_ip}:{SA_SERVICE_PORT}/get-task/{work_queue_name}'
        logger.debug(f'Getting task from {url}')

        try:
            resp = requests.get(url)
        except Exception:
            time.sleep(1)
            continue

        if resp.status_code != 200:
            if exec_mode == StandaloneMode.REUSE.value:
                time.sleep(1)
                continue
            else:
                logger.debug(f'All tasks completed from {url}')
                return

        job_payload = resp.json()

        try:
            verify_runtime_name(runtime_name)
        except Exception:
            return

        running_job_key = job_payload['job_key']

        budget_keeper.add_job(running_job_key)

        try:
            localhos_handler.invoke(job_payload)
        except Exception as e:
            logger.error(e)

        wait_job_completed(running_job_key)
        notify_idle(master_ip)


def main():
    global budget_keeper

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    # read the Lithops standaole configuration file
    with open(SA_CONFIG_FILE, 'r') as cf:
        standalone_config = json.load(cf)
        backend = standalone_config['backend']
        runtime_name = standalone_config['runtime']
        exec_mode = standalone_config['exec_mode']
        worker_processes = standalone_config[backend]['worker_processes']
        pull_runtime = standalone_config['pull_runtime']
        use_gpu = standalone_config['use_gpu']

    # Read the VM data file that contains the instance id, the master IP,
    # and the queue for getting tasks
    with open(SA_DATA_FILE, 'r') as ad:
        vm_data = json.load(ad)
        worker_name = vm_data['name']
        worker_ip = vm_data['private_ip']
        master_ip = vm_data['master_ip']
        work_queue_name = vm_data['work_queue_name']
        instance_type = vm_data['instance_type']

    # Start the budget keeper. It is responsible to automatically terminate the
    # worker after X seconds
    budget_keeper = BudgetKeeper(standalone_config, partial(notify_stop, master_ip))
    budget_keeper.start()

    # Start the http server. This will be used by the master VM to pìng this
    # worker and for canceling tasks
    def run_wsgi():
        server = WSGIServer((worker_ip, SA_SERVICE_PORT), app, log=app.logger)
        server.serve_forever()
    Thread(target=run_wsgi, daemon=True).start()

    # Start the worker that will get tasks from the work queue
    run_worker(worker_name, master_ip, work_queue_name, instance_type, runtime_name,
               worker_processes, exec_mode, pull_runtime, use_gpu)

    # run_worker will run forever in reuse mode. In create mode it will
    # run until there are no more tasks in the queue.
    logger.debug('Finished')

    try:
        # Try to stop the current worker VM once no more pending tasks to run
        # in case of create mode
        budget_keeper.stop_instance()
    except Exception:
        pass


if __name__ == '__main__':
    main()
