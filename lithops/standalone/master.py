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
import copy
import time
import json
import uuid
import flask
import queue
import logging
import multiprocessing as mp
from pathlib import Path
from gevent.pywsgi import WSGIServer
from concurrent.futures import ThreadPoolExecutor

from lithops.constants import LITHOPS_TEMP_DIR, STANDALONE_LOG_FILE, JOBS_DIR,\
    STANDALONE_SERVICE_PORT, STANDALONE_CONFIG_FILE, STANDALONE_INSTALL_DIR
from lithops.localhost.localhost import LocalhostHandler
from lithops.utils import verify_runtime_name, iterchunks, setup_lithops_logger
from lithops.standalone.utils import get_worker_setup_script
from lithops.standalone.keeper import BudgetKeeper


setup_lithops_logger(logging.DEBUG, filename=STANDALONE_LOG_FILE)
logger = logging.getLogger('lithops.standalone.master')

app = flask.Flask(__name__)

INSTANCE_START_TIMEOUT = 200
MAX_INSTANCE_CREATE_RETRIES = 3
STANDALONE_CONFIG = None
STANDALONE_HANDLER = None
BUDGET_KEEPER = None
JOB_PROCESSES = {}
WORK_QUEUES = {}
MASTER_IP = None
MP_MANAGER = mp.Manager()
LOCALHOST_MANAGER_PROCESS = None

EXEC_MODE = 'consume'
WORKERS = MP_MANAGER.list()

# worker heartbeat timeout in seconds. used in reuse mode.
# worker sends heartbeat by invoking get_tasks each ~1sec
WORKER_HEARTBEAT = 20
WORKERS_STATE = {}


def is_worker_instance_ready(vm):
    """
    Checks if the VM instance is ready to receive ssh connections
    """
    try:
        vm.get_ssh_client().run_remote_command('id')
    except Exception as e:
        logger.debug('ssh to {} failed: {}'
                     .format(vm.ip_address, e))
        vm.del_ssh_client()
        return False
    return True


def wait_worker_instance_ready(vm):
    """
    Waits until the VM instance is ready to receive ssh connections
    """
    logger.info('Waiting {} to become ready'.format(vm))

    start = time.time()
    while(time.time() - start < INSTANCE_START_TIMEOUT):
        if is_worker_instance_ready(vm):
            logger.info('{} ready in {} seconds'
                        .format(vm, round(time.time()-start, 2)))
            return True
        time.sleep(5)

    msg = 'Readiness probe expired on {}'.format(vm)
    logger.error(msg)
    raise TimeoutError(msg)


def setup_worker(worker_info, work_queue, job_key, workers):
    """
    Run worker process
    Install all the Lithops dependencies into the worker.
    Runs the job
    """

    instance_name, ip_address, instance_id, ssh_credentials = worker_info
    logger.info('Starting setup for VM instance {}'.format(instance_name))

    vm = STANDALONE_HANDLER.backend.get_vm(instance_name)
    vm.ip_address = ip_address
    vm.instance_id = instance_id
    vm.ssh_credentials = ssh_credentials

    worker_ready = False
    retry = 0

    logger.info('Queue empty: {} - Queue size: {}'
                .format(work_queue.empty(), work_queue.qsize()))

    while(not worker_ready and not work_queue.empty()
          and retry < MAX_INSTANCE_CREATE_RETRIES):
        try:
            wait_worker_instance_ready(vm)
            worker_ready = True
        except TimeoutError:  # VM not started in time
            if retry == MAX_INSTANCE_CREATE_RETRIES:
                msg = '{} readiness probe failed after {} retries.'.format(vm, retry)
                logger.debug(msg)
                raise Exception(msg)
            logger.info('Recreating VM instance {}'.format(vm.name))
            retry += 1
            vm.delete()
            vm.create()

    if work_queue.empty():
        logger.info('Work queue is already empty. Skipping {}'.format(vm))
        return

    # upload zip lithops package
    logger.info('Uploading lithops files to {}'.format(vm))
    vm.get_ssh_client().upload_local_file('/opt/lithops/lithops_standalone.zip',
                                          '/tmp/lithops_standalone.zip')
    logger.info('Executing lithops installation process on {}'.format(vm))

    vm_data = {'instance_name': vm.name,
               'ip_address': vm.ip_address,
               'instance_id': vm.instance_id,
               'master_ip': MASTER_IP,
               'job_key': job_key}

    script = get_worker_setup_script(STANDALONE_CONFIG, vm_data)
    vm.get_ssh_client().run_remote_command(script, run_async=True)
    vm.del_ssh_client()
    logger.info('Installation script submitted to {}'.format(vm))
    logger.debug(f'Appending to WORKERS {vm_data}')
    workers.append(vm_data)


def stop_job_process(job_key):
    """
    Stops a job process
    """
    global JOB_PROCESSES

    done = os.path.join(JOBS_DIR, job_key+'.done')
    Path(done).touch()

    if job_key in JOB_PROCESSES and JOB_PROCESSES[job_key].is_alive():
        JOB_PROCESSES[job_key].terminate()
        logger.info('Finished job {} invocation'.format(job_key))
    del JOB_PROCESSES[job_key]


def run_job_local(work_queue):
    """
    Localhost jobs manager process for consume mode
    """
    pull_runtime = STANDALONE_CONFIG.get('pull_runtime', False)

    try:
        localhos_handler = LocalhostHandler({'pull_runtime': pull_runtime})

        while True:
            job_payload = work_queue.get()
            job_payload['config']['lithops']['backend'] = 'localhost'
            localhos_handler.invoke(job_payload)

    except Exception as e:
        logger.error(e)


def run_job_worker(job_payload, work_queue, workers_list):
    """
    Process responsible to wait for workers to become ready, and
    submit individual tasks of the job to them
    """
    job_key = job_payload['job_key']
    call_ids = job_payload['call_ids']
    chunksize = job_payload['chunksize']
    workers = job_payload['worker_instances']

    for call_ids_range in iterchunks(call_ids, chunksize):
        task_payload = copy.deepcopy(job_payload)
        dbr = task_payload['data_byte_ranges']
        task_payload['call_ids'] = call_ids_range
        task_payload['data_byte_ranges'] = [dbr[int(call_id)] for call_id in call_ids_range]
        work_queue.put(task_payload)

    logger.info("Total tasks in {} work queue: {}".format(job_key, work_queue.qsize()))

    # run setup only in case not reusing old workers
    if workers:
        with ThreadPoolExecutor(len(workers)) as executor:
            for worker_info in workers:
                executor.submit(setup_worker, worker_info, work_queue, job_key, workers_list)

        logger.info('All workers set up for job {}'.format(job_key))

    while not work_queue.empty():
        time.sleep(1)

    done = os.path.join(JOBS_DIR, job_key+'.done')
    Path(done).touch()

    logger.info('Finished job {} invocation.'.format(job_key))


def error(msg):
    response = flask.jsonify({'error': msg})
    response.status_code = 404
    return response


@app.route('/workers', methods=['GET'])
def get_workers():
    """
    Returns the number of spawned workers

    Currently returns only spawned workers metadata
    TODO - add support to list only available workers when each worker updates itself in WORKERS via POST
    TODO - job.done for master is not same as job.done for worker, can be improved by touch on master from worker instead of touch on master
    """

    logger.debug(f'in get_workers, workers = {WORKERS}, workers state: {WORKERS_STATE}')

    workers = []
    for w in WORKERS:
        vm = STANDALONE_HANDLER.backend.get_vm(w['instance_name'])
        vm.ip_address = w['ip_address']
        vm.instance_id = w['instance_id']

        # either available via ssh, to cover case when worker service not running yet
        # or via heartbeat
        hb = WORKERS_STATE[w['ip_address']]
        if is_worker_instance_ready(vm) or (time.time() - hb < WORKER_HEARTBEAT):
            workers.append(w)
        else:
            # delete worker in case it is not available. may cover edge cases when for some reason keeper not started on worker
            vm.delete()

    response = flask.jsonify(workers)
    response.status_code = 200

    return response


@app.route('/get-task/<job_key>', methods=['GET'])
def get_task(job_key):
    """
    Returns a task from the work queue
    """
    global WORK_QUEUES
    global WORKERS_STATE

    try:
        # track active workers
        worker_ip = flask.request.remote_addr

        WORKERS_STATE[worker_ip] = time.time()

        task_payload = WORK_QUEUES.setdefault(job_key, MP_MANAGER.Queue()).get(timeout=0.1)
        response = flask.jsonify(task_payload)
        response.status_code = 200
        logger.info('Calls {} invoked on {}'
                    .format(', '.join(task_payload['call_ids']),
                            flask.request.remote_addr))
    except queue.Empty:
        if EXEC_MODE != 'reuse':
            stop_job_process(job_key)
        response = ('', 204)
    return response


@app.route('/clear', methods=['POST'])
def clear():
    """
    Stops received job processes
    """
    global JOB_PROCESSES

    job_key_list = flask.request.get_json(force=True, silent=True)
    for job_key in job_key_list:
        if job_key in JOB_PROCESSES and JOB_PROCESSES[job_key].is_alive():
            logger.info('Received SIGTERM: Stopping job process {}'
                        .format(job_key))
        stop_job_process(job_key)

    return ('', 204)


@app.route('/run', methods=['POST'])
def run():
    """
    Run a job locally, in consume mode
    """
    global BUDGET_KEEPER
    global WORK_QUEUES
    global JOB_PROCESSES
    global WORKERS
    global EXEC_MODE
    global LOCALHOST_MANAGER_PROCESS

    job_payload = flask.request.get_json(force=True, silent=True)
    if job_payload and not isinstance(job_payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime = job_payload['runtime_name']
        verify_runtime_name(runtime)
    except Exception as e:
        return error(str(e))

    job_key = job_payload['job_key']
    logger.info('Received job {}'.format(job_key))

    BUDGET_KEEPER.last_usage_time = time.time()
    BUDGET_KEEPER.update_config(job_payload['config']['standalone'])
    BUDGET_KEEPER.jobs[job_key] = 'running'

    EXEC_MODE = job_payload['config']['standalone'].get('exec_mode', 'consume')

    if EXEC_MODE == 'consume':
        work_queue = WORK_QUEUES.setdefault('local', MP_MANAGER.Queue())
        if not LOCALHOST_MANAGER_PROCESS:
            logger.debug('Starting manager process for localhost jobs')
            lmp = mp.Process(target=run_job_local, args=(work_queue,))
            lmp.daemon = True
            lmp.start()
            LOCALHOST_MANAGER_PROCESS = lmp
        logger.info(f'Putting job {job_key} into master queue')
        work_queue.put(job_payload)

    elif EXEC_MODE == 'create':
        # Create mode runs the job in worker VMs
        logger.debug(f'Starting process for job {job_key}')
        work_queue = MP_MANAGER.Queue()
        WORK_QUEUES[job_key] = work_queue
        jp = mp.Process(target=run_job_worker, args=(job_payload, work_queue, WORKERS))
        jp.daemon = True
        jp.start()
        JOB_PROCESSES[job_key] = jp

    elif EXEC_MODE == 'reuse':
        # Reuse mode runs the job on running workers
        # TODO: Consider to add support to manage pull of available workers
        # TODO: Spawn only the missing delta of workers
        logger.debug(f'Starting process for job {job_key}')
        work_queue = WORK_QUEUES.setdefault('all', MP_MANAGER.Queue())
        jp = mp.Process(target=run_job_worker, args=(job_payload, work_queue, WORKERS))
        jp.daemon = True
        jp.start()
        JOB_PROCESSES[job_key] = jp

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    response = flask.jsonify({'activationId': act_id})
    response.status_code = 202

    return response


@app.route('/ping', methods=['GET'])
def ping():
    response = flask.jsonify({'response': 'pong'})
    response.status_code = 200
    return response


@app.route('/preinstalls', methods=['GET'])
def preinstalls():
    global LOCALHOST_HANDLER

    payload = flask.request.get_json(force=True, silent=True)
    if payload and not isinstance(payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime = payload['runtime']
        verify_runtime_name(runtime)
    except Exception as e:
        return error(str(e))

    pull_runtime = STANDALONE_CONFIG.get('pull_runtime', False)
    localhost_handler = LocalhostHandler({'runtime': runtime, 'pull_runtime': pull_runtime})
    localhost_handler.init()
    runtime_meta = localhost_handler.create_runtime(runtime)
    localhost_handler.clear()

    logger.info(runtime_meta)
    response = flask.jsonify(runtime_meta)
    response.status_code = 200

    return response


def main():
    global STANDALONE_CONFIG
    global STANDALONE_HANDLER
    global BUDGET_KEEPER
    global MASTER_IP

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    with open(STANDALONE_CONFIG_FILE, 'r') as cf:
        STANDALONE_CONFIG = json.load(cf)

    # Delete ssh_key_filename
    backend = STANDALONE_CONFIG['backend']
    if 'ssh_key_filename' in STANDALONE_CONFIG[backend]:
        del STANDALONE_CONFIG[backend]['ssh_key_filename']

    vm_data_file = os.path.join(STANDALONE_INSTALL_DIR, 'access.data')
    with open(vm_data_file, 'r') as ad:
        MASTER_IP = json.load(ad)['ip_address']

    BUDGET_KEEPER = BudgetKeeper(STANDALONE_CONFIG)
    BUDGET_KEEPER.start()

    STANDALONE_HANDLER = BUDGET_KEEPER.sh

    server = WSGIServer(('0.0.0.0', STANDALONE_SERVICE_PORT),
                        app, log=app.logger)
    server.serve_forever()


if __name__ == '__main__':
    main()
