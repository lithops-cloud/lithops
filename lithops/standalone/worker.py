#
# (C) Copyright Cloudlab URV 2020
# (C) Copyright IBM Corp. 2024
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
import json
import flask
import logging
import signal
import requests
import subprocess as sp
from pathlib import Path
from threading import Thread
from functools import partial
from gevent.pywsgi import WSGIServer
from concurrent.futures import ThreadPoolExecutor

from lithops.utils import setup_lithops_logger
from lithops.standalone.keeper import BudgetKeeper
from lithops.standalone.utils import StandaloneMode, WorkerStatus
from lithops.constants import (
    LITHOPS_TEMP_DIR,
    RN_LOG_FILE,
    SA_INSTALL_DIR,
    SA_LOG_FILE,
    JOBS_DIR,
    SA_MASTER_SERVICE_PORT,
    SA_CONFIG_FILE,
    SA_DATA_FILE,
    JOBS_PREFIX,
    SA_WORKER_SERVICE_PORT
)

log_format = "%(asctime)s\t[%(levelname)s] %(name)s:%(lineno)s -- %(message)s"
setup_lithops_logger(logging.DEBUG, filename=SA_LOG_FILE, log_format=log_format)
logger = logging.getLogger('lithops.standalone.worker')

app = flask.Flask(__name__)

budget_keeper = None
job_processes = {}
worker_threads = {}


@app.route('/ping', methods=['GET'])
def ping():
    idle_count = sum(1 for worker in worker_threads.values() if worker['status'] == WorkerStatus.IDLE.value)
    busy_count = sum(1 for worker in worker_threads.values() if worker['status'] == WorkerStatus.BUSY.value)
    response = flask.jsonify({'busy': busy_count, 'free': idle_count})
    response.status_code = 200
    return response


@app.route('/stop/<job_key>', methods=['POST'])
def stop(job_key):
    logger.debug(f'Received SIGTERM: Stopping job process {job_key}')

    for job_key_call_id in job_processes:
        if job_key_call_id.startswith(job_key):
            PID = job_processes[job_key_call_id].pid
            PGID = os.getpgid(PID)
            os.killpg(PGID, signal.SIGKILL)
            Path(os.path.join(JOBS_DIR, job_key_call_id + '.done')).touch()
            job_processes[job_key_call_id] = None

    response = flask.jsonify({'response': 'cancel'})
    response.status_code = 200
    return response


def notify_stop(master_ip):
    try:
        url = f'http://{master_ip}:{SA_MASTER_SERVICE_PORT}/worker/status/stop'
        resp = requests.post(url)
        logger.debug("Stop worker: " + str(resp.status_code))
    except Exception as e:
        logger.error(e)


def notify_delete(master_ip):
    try:
        url = f'http://{master_ip}:{SA_MASTER_SERVICE_PORT}/worker/status/delete'
        resp = requests.post(url)
        logger.debug("Delete worker: " + str(resp.status_code))
    except Exception as e:
        logger.error(e)


def notify_done(master_ip, job_key, call_id):
    try:
        url = f'http://{master_ip}:{SA_MASTER_SERVICE_PORT}/worker/status/done/{job_key}/{call_id}'
        requests.post(url)
    except Exception as e:
        logger.error(e)


def redis_queue_consumer(pid, master_ip, work_queue_name, exec_mode, local_job_dir):
    global worker_threads

    worker_threads[pid]['status'] = WorkerStatus.IDLE.value

    logger.info(f"Redis consumer process {pid} started")

    while True:
        url = f'http://{master_ip}:{SA_MASTER_SERVICE_PORT}/get-task/{work_queue_name}'

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

        logger.debug(f'Received task from {url}')
        worker_threads[pid]['status'] = WorkerStatus.BUSY.value

        job_payload = resp.json()

        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        job_key = job_payload['job_key']
        call_id = job_payload['call_ids'][0]
        job_key_call_id = f'{job_key}-{call_id}'

        try:
            logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Running '
                         f'CallID {call_id} in the local worker')
            budget_keeper.add_job(job_key_call_id)
            job_file = f'{job_key_call_id}-job.json'
            os.makedirs(local_job_dir, exist_ok=True)
            job_filename = os.path.join(local_job_dir, job_file)

            with open(job_filename, 'w') as jl:
                json.dump(job_payload, jl, default=str)

            cmd = ["python3", f"{SA_INSTALL_DIR}/runner.py", 'run_job', job_filename]
            log = open(RN_LOG_FILE, 'a')
            process = sp.Popen(cmd, stdout=log, stderr=log, start_new_session=True)
            job_processes[job_key_call_id] = process
            process.communicate()  # blocks until the process finishes
            logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - CallID {call_id} execution finished')
        except Exception as e:
            logger.error(e)

        notify_done(master_ip, job_key, call_id)
        worker_threads[pid]['status'] = WorkerStatus.IDLE.value


def run_worker():
    global budget_keeper
    global worker_threads

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    # read the Lithops standaole configuration file
    with open(SA_CONFIG_FILE, 'r') as cf:
        standalone_config = json.load(cf)
        backend = standalone_config['backend']

    # Read the VM data file that contains the instance id, the master IP,
    # and the queue for getting tasks
    with open(SA_DATA_FILE, 'r') as ad:
        vm_data = json.load(ad)

    # Start the budget keeper. It is responsible to automatically terminate the
    # worker after X seconds

    stop_callback = partial(notify_stop, vm_data['master_ip'])
    delete_callback = partial(notify_delete, vm_data['master_ip'])
    budget_keeper = BudgetKeeper(standalone_config, stop_callback, delete_callback)
    budget_keeper.start()

    # Start the http server. This will be used by the master VM to pìng this
    # worker and for canceling tasks
    def run_wsgi():
        server = WSGIServer((vm_data['private_ip'], SA_WORKER_SERVICE_PORT), app, log=app.logger)
        server.serve_forever()
    Thread(target=run_wsgi, daemon=True).start()

    # Start the consumer threads
    worker_processes = standalone_config[backend]['worker_processes']
    logger.info(f"Starting Worker - Instace type: {vm_data['instance_type']} - Runtime "
                f"name: {standalone_config['runtime']} - Worker processes: {worker_processes}")

    local_job_dir = os.path.join(LITHOPS_TEMP_DIR, JOBS_PREFIX)
    os.makedirs(local_job_dir, exist_ok=True)

    # Create a ThreadPoolExecutor for cosnuming tasks
    redis_queue_consumer_futures = []
    with ThreadPoolExecutor(max_workers=worker_processes) as executor:
        for i in range(worker_processes):
            worker_threads[i] = {}
            future = executor.submit(
                redis_queue_consumer, i,
                vm_data['master_ip'],
                vm_data['work_queue_name'],
                standalone_config['exec_mode'],
                local_job_dir
            )
            redis_queue_consumer_futures.append(future)
            worker_threads[i]['future'] = future

        for future in redis_queue_consumer_futures:
            future.result()

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
    run_worker()
