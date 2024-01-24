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
import copy
import time
import json
import uuid
import flask
import queue
import logging
import requests
import concurrent.futures as cf
from pathlib import Path
from datetime import datetime
from gevent.pywsgi import WSGIServer
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

from lithops.localhost import LocalhostHandler
from lithops.standalone import LithopsValidationError
from lithops.standalone.keeper import BudgetKeeper
from lithops.config import extract_standalone_config
from lithops.standalone.standalone import StandaloneHandler
from lithops.version import __version__ as lithops_version
from lithops.constants import (
    LITHOPS_TEMP_DIR,
    SA_LOG_FILE,
    JOBS_DIR,
    SA_SERVICE_PORT,
    SA_CONFIG_FILE,
    SA_DATA_FILE,
    CPU_COUNT
)
from lithops.utils import (
    verify_runtime_name,
    iterchunks,
    setup_lithops_logger
)
from lithops.standalone.utils import (
    JobStatus,
    StandaloneMode,
    WorkerStatus,
    get_worker_setup_script
)


log_format = "%(asctime)s\t[%(levelname)s] %(name)s:%(lineno)s -- %(message)s"
setup_lithops_logger(logging.DEBUG, filename=SA_LOG_FILE, log_format=log_format)
logger = logging.getLogger('lithops.standalone.master')

app = flask.Flask(__name__)

MAX_INSTANCE_CREATE_RETRIES = 2
REUSE_WORK_QUEUE_NAME = 'all'

workers = {}
work_queues = {}
jobs_list = {}

budget_keeper = None
master_ip = None
exec_mode = None

# variables for consume mode
localhost_manager_process = None
localhos_handler = None
running_job_key = None


def is_worker_free(worker):
    """
    Checks if the Lithops service is ready and free in the worker VM instance
    """
    url = f"http://{worker.private_ip}:{SA_SERVICE_PORT}/ping"
    r = requests.get(url, timeout=0.5)
    if r.status_code == 200:
        if r.json()['status'] == 'free':
            return True
    return False


def setup_worker(standalone_handler, worker_info, work_queue_name):
    """
    Run worker process
    Install all the Lithops dependencies into the worker.
    Runs the job
    """
    global workers

    worker = standalone_handler.backend.get_instance(**worker_info, public=False)
    worker.metadata = standalone_handler.config

    workers[worker.name] = worker

    logger.debug(f'Starting setup for {worker}')

    max_instance_create_retries = worker.metadata.get('worker_create_retries', MAX_INSTANCE_CREATE_RETRIES)

    def wait_worker_ready(worker):
        instance_ready_retries = 1

        while instance_ready_retries <= max_instance_create_retries:
            try:
                worker.status = WorkerStatus.STARTING.value
                worker.wait_ready()
                break
            except TimeoutError as e:  # VM not started in time
                worker.status = WorkerStatus.ERROR.value
                worker.err = 'Timeout Error while waitting the VM to get ready'
                if instance_ready_retries == max_instance_create_retries:
                    logger.debug(f'Readiness probe expired for {worker}')
                    raise e
                logger.warning(f'Timeout Error. Recreating {worker}')
                worker.delete()
                worker.create()
                instance_ready_retries += 1

    wait_worker_ready(worker)

    instance_validate_retries = 1
    while instance_validate_retries <= max_instance_create_retries:
        try:
            logger.debug(f'Validating {worker}')
            worker.validate_capabilities()
            break
        except LithopsValidationError as e:
            worker.status = WorkerStatus.ERROR.value
            worker.err = f'Validation error: {e}'
            if instance_validate_retries == max_instance_create_retries:
                logger.debug(f'Validation probe expired for {worker}')
                raise e
            logger.warning(f'{worker} validation error: {e}')
            worker.delete()
            worker.create()
            instance_validate_retries += 1
            wait_worker_ready(worker)

    workers[worker.private_ip] = workers.pop(worker.name)
    worker.status = WorkerStatus.STARTED.value
    worker.err = None

    try:
        logger.debug(f'Uploading lithops files to {worker}')
        worker.get_ssh_client().upload_local_file(
            '/opt/lithops/lithops_standalone.zip',
            '/tmp/lithops_standalone.zip')

        logger.debug(f'Preparing installation script for {worker}')
        vm_data = {
            'name': worker.name,
            'private_ip': worker.private_ip,
            'instance_id': worker.instance_id,
            'ssh_credentials': worker.ssh_credentials,
            'instance_type': worker.instance_type,
            'master_ip': master_ip,
            'work_queue_name': work_queue_name
        }
        remote_script = "/tmp/install_lithops.sh"
        script = get_worker_setup_script(worker.metadata, vm_data)

        logger.debug(f'Submitting installation script to {worker}')
        worker.get_ssh_client().upload_data_to_file(script, remote_script)
        cmd = f"chmod 777 {remote_script}; sudo {remote_script};"
        worker.get_ssh_client().run_remote_command(cmd, run_async=True)
        worker.del_ssh_client()

        logger.debug(f'Installation script submitted to {worker}')

        worker.status = WorkerStatus.INSTALLING.value

    except Exception as e:
        worker.status = WorkerStatus.ERROR.value
        worker.err = f'Unable to setup lithops in the VM: {str(e)}'
        raise e


def start_workers(job_payload, work_queue_name):
    """
    Creates the workers (if any)
    """
    workers = job_payload['worker_instances']
    standalone_config = extract_standalone_config(job_payload['config'])
    standalone_handler = StandaloneHandler(standalone_config)

    if not workers:
        return

    futures = []
    total_correct = 0

    with ThreadPoolExecutor(len(workers)) as executor:
        for worker_info in workers:
            futures.append(executor.submit(setup_worker, standalone_handler, worker_info, work_queue_name))

    for future in cf.as_completed(futures):
        try:
            future.result()
            total_correct += 1
        except Exception as e:
            logger.error(e)

    logger.debug(f'{total_correct} of {len(workers)} workers started for work queue {work_queue_name}')


def run_job_local(work_queue):
    """
    Localhost jobs manager process for consume mode
    """
    global localhos_handler
    global running_job_key

    def wait_job_completed(job_key):
        done = os.path.join(JOBS_DIR, job_key + '.done')
        while True:
            if os.path.isfile(done):
                break
            time.sleep(1)

    try:
        while True:
            job_payload = work_queue.get()
            localhos_handler = LocalhostHandler(job_payload['config']['standalone'])
            localhos_handler.init()
            running_job_key = job_payload['job_key']
            jobs_list[running_job_key]['status'] = JobStatus.RUNNING.value
            wp = job_payload['worker_processes']
            job_payload['worker_processes'] = CPU_COUNT if wp == "AUTO" else wp
            localhos_handler.invoke(job_payload)
            wait_job_completed(running_job_key)
            jobs_list[running_job_key]['status'] = JobStatus.DONE.value
            localhos_handler.clear()

    except Exception as e:
        logger.error(e)


def run_job_worker(job_payload, work_queue):
    """
    Process responsible to put all the individual tasks in
    queue and wait until the job is completely finished.
    """
    job_key = job_payload['job_key']
    call_ids = job_payload['call_ids']
    chunksize = job_payload['chunksize']

    for call_ids_range in iterchunks(call_ids, chunksize):
        task_payload = copy.deepcopy(job_payload)
        dbr = task_payload['data_byte_ranges']
        task_payload['call_ids'] = call_ids_range
        task_payload['data_byte_ranges'] = [dbr[int(call_id)] for call_id in call_ids_range]
        work_queue.put(task_payload)

    jobs_list[job_key]['status'] = JobStatus.RUNNING.value

    while not work_queue.empty():
        time.sleep(1)

    Path(os.path.join(JOBS_DIR, job_key + '.done')).touch()
    jobs_list[job_key]['status'] = JobStatus.DONE.value

    logger.debug(f'Job process {job_key} finished')


def error(msg):
    response = flask.jsonify({'error': msg})
    response.status_code = 404
    return response


@app.route('/worker/status/stop', methods=['POST'])
def stop_worker():
    """
    Returns the current workers list
    """
    worker_ip = flask.request.remote_addr
    workers[worker_ip].status = WorkerStatus.STOPPED.value
    return ('', 204)


@app.route('/worker/status/idle', methods=['POST'])
def idle_worker():
    """
    Returns the current workers list
    """
    worker_ip = flask.request.remote_addr
    workers[worker_ip].status = WorkerStatus.IDLE.value
    return ('', 204)


@app.route('/worker/list', methods=['GET'])
def list_workers():
    """
    Returns the current workers list
    """
    global budget_keeper

    budget_keeper.last_usage_time = time.time()

    result = [['Worker Name', 'Instance Type', 'Processes', 'Runtime', 'Execution Mode', 'Status']]

    for worker_key in workers:
        worker = workers[worker_key]
        status = worker.status
        instance_type = worker.instance_type
        worker_processes = str(worker.config['worker_processes'])
        exec_mode = worker.metadata['exec_mode']
        runtime = worker.metadata['runtime']
        result.append((worker.name, instance_type, worker_processes, runtime, exec_mode, status))

    logger.debug(f'Listing workers: {result}')
    return flask.jsonify(result)


@app.route('/worker/<worker_instance_type>/<runtime_name>', methods=['GET'])
def get_workers(worker_instance_type, runtime_name):
    """
    Returns the number of free workers
    """
    global budget_keeper

    budget_keeper.last_usage_time = time.time()

    logger.debug(f'Total workers: {len(workers)}')

    active_workers = []
    for worker in workers.values():
        if worker.instance_type == worker_instance_type \
           and worker.metadata['runtime'] == runtime_name:
            active_workers.append(worker)
    logger.debug(f'Workers for {worker_instance_type}-{runtime_name}: {len(active_workers)}')

    free_workers = []

    def check_worker(worker):
        if is_worker_free(worker):
            free_workers.append(
                (
                    worker.name,
                    worker.private_ip,
                    worker.instance_id,
                    worker.ssh_credentials,
                    worker.instance_type,
                    runtime_name
                )
            )

    if active_workers:
        with ThreadPoolExecutor(len(active_workers)) as ex:
            ex.map(check_worker, active_workers)

    logger.debug(f'Free workers for {worker_instance_type}-{runtime_name}: {len(free_workers)}')

    response = flask.jsonify(free_workers)
    response.status_code = 200

    return response


@app.route('/get-task/<work_queue_name>', methods=['GET'])
def get_task(work_queue_name):
    """
    Returns a task from the work queue
    """
    global work_queues

    worker_ip = flask.request.remote_addr

    try:
        task_payload = work_queues.setdefault(work_queue_name, queue.Queue()).get(False)
        response = flask.jsonify(task_payload)
        response.status_code = 200
        job_key = task_payload['job_key']
        calls = task_payload['call_ids']
        workers[worker_ip].status = WorkerStatus.BUSSY.value
        logger.debug(f'Worker {worker_ip} retrieved Job {job_key} - Calls {calls}')
    except queue.Empty:
        response = ('', 204)

    return response


def stop_job_process(job_key_list):
    """
    Stops a job process
    """
    global localhos_handler
    global work_queues

    for job_key in job_key_list:
        logger.debug(f'Received SIGTERM: Stopping job process {job_key}')

        work_queue_name = jobs_list[job_key]['queue_name']

        if work_queue_name == 'localhost':
            if job_key == running_job_key:
                # kill current running job process
                localhos_handler.clear()
                Path(os.path.join(JOBS_DIR, job_key + '.done')).touch()
            else:
                # Delete job_payload from pending queue
                work_queue = work_queues.setdefault(work_queue_name, queue.Queue())
                tmp_queue = []
                while not work_queue.empty():
                    try:
                        job_payload = work_queue.get(False)
                        if job_payload['job_key'] != job_key:
                            tmp_queue.append(job_payload)
                    except Exception:
                        pass
                for job_payload in tmp_queue:
                    work_queue.put(job_payload)

        else:
            work_queue = work_queues.setdefault(work_queue_name, queue.Queue())
            while not work_queue.empty():
                try:
                    work_queue.get(False)
                except Exception:
                    pass

            def stop_task(worker):
                url = f"http://{worker.private_ip}:{SA_SERVICE_PORT}/stop/{job_key}"
                requests.post(url, timeout=0.5)

            # Send stop signal to all workers
            with ThreadPoolExecutor(len(workers)) as ex:
                ex.map(stop_task, workers.values())


@app.route('/stop', methods=['POST'])
def stop():
    """
    Stops received job processes
    """
    job_key_list = flask.request.get_json(force=True, silent=True)
    # Start a separate thread to do the task in background,
    # for not keeping the client waiting.
    Thread(target=stop_job_process, args=(job_key_list, )).start()

    return ('', 204)


@app.route('/job/list', methods=['GET'])
def list_jobs():
    """
    Returns the current workers state
    """
    global budget_keeper

    budget_keeper.last_usage_time = time.time()

    result = [['Job ID', 'Function Name', 'Submitted', 'Worker Type', 'Runtime', 'Total Tasks', 'Status']]

    for job_key in jobs_list:
        job_data = jobs_list[job_key]
        exec_mode = job_data['exec_mode']
        status = job_data['status']
        func_name = job_data['func_name'] + "()"
        timestamp = job_data['submitted']
        runtime = job_data['runtime_name']
        worker_type = job_data['worker_type'] if exec_mode != StandaloneMode.CONSUME.value else 'VM'
        submitted = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')
        total_tasks = str(job_data['total_tasks'])
        result.append((job_key, func_name, submitted, worker_type, runtime, total_tasks, status))

    logger.debug(f'Listing jobs: {result}')
    return flask.jsonify(result)


@app.route('/job/run', methods=['POST'])
def run():
    """
    Run a job locally, in consume mode
    """
    global budget_keeper
    global work_queues
    global exec_mode
    global localhost_manager_process

    job_payload = flask.request.get_json(force=True, silent=True)
    if job_payload and not isinstance(job_payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime_name = job_payload['runtime_name']
        verify_runtime_name(runtime_name)
    except Exception as e:
        return error(str(e))

    job_key = job_payload['job_key']
    logger.debug(f'Received job {job_key}')

    budget_keeper.add_job(job_key)

    exec_mode = job_payload['config']['standalone']['exec_mode']

    jobs_list[job_key] = {
        'status': JobStatus.RECEIVED.value,
        'submitted': job_payload['host_submit_tstamp'],
        'func_name': job_payload['func_name'],
        'worker_type': job_payload.get('worker_instance_type'),
        'runtime_name': job_payload['runtime_name'],
        'exec_mode': exec_mode,
        'total_tasks': len(job_payload['call_ids']),
        'queue_name': None
    }

    if exec_mode == StandaloneMode.CONSUME.value:
        # Consume mode runs jobs in this master VM
        jobs_list[job_key]['queue_name'] = 'localhost'
        work_queue = work_queues.setdefault('localhost', queue.Queue())
        if not localhost_manager_process:
            logger.debug('Starting manager process for localhost jobs')
            lmp = Thread(target=run_job_local, args=(work_queue, ), daemon=True)
            lmp.start()
            localhost_manager_process = lmp
        logger.debug(f'Putting job {job_key} into master queue')
        work_queue.put(job_payload)

    elif exec_mode in [StandaloneMode.CREATE.value, StandaloneMode.REUSE.value]:
        # Create and reuse mode runs jobs on woker VMs
        logger.debug(f'Starting process for job {job_key}')
        worker_it = job_payload['worker_instance_type']
        queue_name = f'{worker_it}-{runtime_name.replace("/", "-")}' if exec_mode == StandaloneMode.REUSE.value else job_key
        work_queue = work_queues.setdefault(queue_name, queue.Queue())
        jobs_list[job_key]['queue_name'] = queue_name
        Thread(target=start_workers, args=(job_payload, queue_name)).start()
        Thread(target=run_job_worker, args=(job_payload, work_queue), daemon=True).start()

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    response = flask.jsonify({'activationId': act_id})
    response.status_code = 202

    return response


@app.route('/ping', methods=['GET'])
def ping():
    response = flask.jsonify({'response': lithops_version})
    response.status_code = 200
    return response


@app.route('/metadata', methods=['GET'])
def get_metadata():
    payload = flask.request.get_json(force=True, silent=True)
    if payload and not isinstance(payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        verify_runtime_name(payload['runtime'])
    except Exception as e:
        return error(str(e))

    localhos_handler = LocalhostHandler(payload)
    localhos_handler.init()
    runtime_meta = localhos_handler.deploy_runtime(payload['runtime'])

    if 'lithops_version' in runtime_meta:
        logger.debug("Runtime metdata extracted correctly: Lithops "
                     f"{runtime_meta['lithops_version']}")
    response = flask.jsonify(runtime_meta)
    response.status_code = 200

    return response


def main():
    global budget_keeper
    global master_ip

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    with open(SA_CONFIG_FILE, 'r') as cf:
        standalone_config = json.load(cf)

    with open(SA_DATA_FILE, 'r') as ad:
        master_ip = json.load(ad)['private_ip']

    budget_keeper = BudgetKeeper(standalone_config)
    budget_keeper.start()

    server = WSGIServer(('0.0.0.0', SA_SERVICE_PORT), app, log=app.logger)
    server.serve_forever()


if __name__ == '__main__':
    main()
