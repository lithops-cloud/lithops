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
import requests
import multiprocessing as mp
from pathlib import Path
from gevent.pywsgi import WSGIServer
from threading import Thread
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

INSTANCE_START_TIMEOUT = 120
MAX_INSTANCE_CREATE_RETRIES = 2
REUSE_WORK_QUEUE_NAME = 'all'

exec_mode = 'consume'
mp_manager = mp.Manager()
workers = mp_manager.dict()

standalone_config = None
standalone_handler = None
budget_keeper = None
job_processes = {}
work_queues = {}
master_ip = None

# variables for consume mode
localhost_manager_process = None
localhos_handler = None
last_job_key = None


def is_worker_free(vm):
    """
    Checks if the Lithops service is ready and free in the worker VM instance
    """
    url = f"http://{vm.ip_address}:{STANDALONE_SERVICE_PORT}/ping"
    r = requests.get(url, timeout=0.5)
    if r.status_code == 200:
        if r.json()['status'] == 'free':
            return True
    return False


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


def setup_worker(worker_info, work_queue_name):
    """
    Run worker process
    Install all the Lithops dependencies into the worker.
    Runs the job
    """
    global workers

    instance_name, ip_address, instance_id, ssh_credentials = worker_info
    logger.info(f'Starting setup for VM instance {instance_name} ({ip_address})')
    logger.info(f'SSH data: {ssh_credentials}')

    vm = standalone_handler.backend.get_vm(instance_name)
    vm.ip_address = ip_address
    vm.instance_id = instance_id
    vm.ssh_credentials = ssh_credentials

    worker_ready = False
    retry = 0

    while not worker_ready and retry < MAX_INSTANCE_CREATE_RETRIES:
        try:
            wait_worker_instance_ready(vm)
            worker_ready = True
        except TimeoutError:  # VM not started in time
            if retry == MAX_INSTANCE_CREATE_RETRIES:
                msg = f'{vm} readiness probe failed after {retry} retries.'
                logger.debug(msg)
                vm.delete()
                raise Exception(msg)
            retry += 1

    # upload zip lithops package
    logger.info('Uploading lithops files to {}'.format(vm))
    vm.get_ssh_client().upload_local_file('/opt/lithops/lithops_standalone.zip',
                                          '/tmp/lithops_standalone.zip')
    logger.info('Executing lithops installation process on {}'.format(vm))

    vm_data = {'instance_name': vm.name,
               'ip_address': vm.ip_address,
               'instance_id': vm.instance_id,
               'ssh_credentials': vm.ssh_credentials,
               'master_ip': master_ip,
               'work_queue': work_queue_name}

    remote_script = "/tmp/install_lithops.sh"
    script = get_worker_setup_script(standalone_config, vm_data)
    vm.get_ssh_client().upload_data_to_file(script, remote_script)
    cmd = f"chmod 777 {remote_script}; sudo {remote_script};"
    vm.get_ssh_client().run_remote_command(cmd, run_async=True)
    vm.del_ssh_client()
    logger.info('Installation script submitted to {}'.format(vm))

    logger.debug(f'Appending {vm.name} to Worker list')
    workers[vm.name] = vm_data


def start_workers(job_payload, work_queue_name):
    """
    Creates the workers
    """
    workers = job_payload['worker_instances']
    # run setup only in case not reusing old workers
    if workers:
        with ThreadPoolExecutor(len(workers)) as executor:
            for worker_info in workers:
                executor.submit(setup_worker, worker_info, work_queue_name)

        logger.info(f'All workers set up for work queue "{work_queue_name}"')


def run_job_local(work_queue):
    """
    Localhost jobs manager process for consume mode
    """
    global localhos_handler
    global last_job_key

    pull_runtime = standalone_config.get('pull_runtime', False)

    def wait_job_completed(job_key):
        done = os.path.join(JOBS_DIR, job_key+'.done')
        while True:
            if os.path.isfile(done):
                break
            time.sleep(1)

    try:
        localhos_handler = LocalhostHandler({'pull_runtime': pull_runtime})

        while True:
            job_payload = work_queue.get()
            job_key = job_payload['job_key']
            last_job_key = job_key
            job_payload['config']['lithops']['backend'] = 'localhost'
            localhos_handler.invoke(job_payload)
            wait_job_completed(job_key)

    except Exception as e:
        logger.error(e)


def run_job_worker(job_payload, work_queue, work_queue_name):
    """
    Process responsible to wait for workers to become ready, and
    submit individual tasks of the job to them
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

    logger.info(f"Total tasks in work queue '{work_queue_name}': {work_queue.qsize()}")

    while not work_queue.empty():
        time.sleep(1)

    done = os.path.join(JOBS_DIR, job_key+'.done')
    Path(done).touch()

    logger.info(f'Job process "{job_key}" finished')


def error(msg):
    response = flask.jsonify({'error': msg})
    response.status_code = 404
    return response


@app.route('/workers', methods=['GET'])
def get_workers():
    """
    Returns the number of free workers
    """
    global workers

    logger.info(f'Getting workers: {workers}')

    worker_vms = []
    worker_vms_free = []

    for vm_name in workers:
        vm = standalone_handler.backend.get_vm(vm_name)
        vm.ip_address = workers[vm_name]['ip_address']
        vm.instance_id = workers[vm_name]['instance_id']
        vm.ssh_credentials = workers[vm_name]['ssh_credentials']
        worker_vms.append(vm)

    def check_worker(vm):
        if is_worker_free(vm):
            worker_vms_free.append((
                vm.name,
                vm.ip_address,
                vm.instance_id,
                vm.ssh_credentials)
            )

    if worker_vms:
        with ThreadPoolExecutor(len(worker_vms)) as ex:
            ex.map(check_worker, worker_vms)

    logger.info(f'Total free workers: {len(worker_vms_free)}')

    response = flask.jsonify(worker_vms_free)
    response.status_code = 200

    return response


@app.route('/get-task/<work_queue_name>', methods=['GET'])
def get_task(work_queue_name):
    """
    Returns a task from the work queue
    """
    global work_queues

    try:
        task_payload = work_queues.setdefault(work_queue_name, mp_manager.Queue()).get(False)
        response = flask.jsonify(task_payload)
        response.status_code = 200
        logger.info('Calls {} invoked on {}'
                    .format(', '.join(task_payload['call_ids']),
                            flask.request.remote_addr))
    except queue.Empty:
        response = ('', 204)
    return response


def stop_job_process(job_key):
    """
    Stops a job process
    """
    global job_processes
    global localhos_handler
    global work_queues

    if exec_mode == 'consume':
        if job_key == last_job_key:
            # kill current running job process
            localhos_handler.clear()
            done = os.path.join(JOBS_DIR, job_key+'.done')
            Path(done).touch()
        else:
            # Delete job_payload from pending queue
            work_queue = work_queues['local']
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

    elif exec_mode == 'create':
        # empty work queue
        work_queue = work_queues.setdefault(job_key, mp_manager.Queue())
        while not work_queue.empty():
            try:
                work_queue.get(False)
            except Exception:
                pass

    elif exec_mode == 'reuse':
        # empty work queue
        work_queue = work_queues.setdefault(REUSE_WORK_QUEUE_NAME, mp_manager.Queue())
        while not work_queue.empty():
            try:
                work_queue.get(False)
            except Exception:
                pass


@app.route('/stop', methods=['POST'])
def stop():
    """
    Stops received job processes
    """
    job_key_list = flask.request.get_json(force=True, silent=True)
    for job_key in job_key_list:
        logger.info(f'Received SIGTERM: Stopping job process {job_key}')
        stop_job_process(job_key)

    return ('', 204)


@app.route('/run', methods=['POST'])
def run():
    """
    Run a job locally, in consume mode
    """
    global budget_keeper
    global work_queues
    global job_processes
    global workers
    global exec_mode
    global localhost_manager_process

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

    budget_keeper.last_usage_time = time.time()
    budget_keeper.update_config(job_payload['config']['standalone'])
    budget_keeper.jobs[job_key] = 'running'

    exec_mode = job_payload['config']['standalone'].get('exec_mode', 'consume')

    if exec_mode == 'consume':
        work_queue_name = 'local'
        work_queue = work_queues.setdefault(work_queue_name, mp_manager.Queue())
        if not localhost_manager_process:
            logger.debug('Starting manager process for localhost jobs')
            lmp = Thread(target=run_job_local, args=(work_queue, ), daemon=True)
            lmp.start()
            localhost_manager_process = lmp
        logger.info(f'Putting job {job_key} into master queue')
        work_queue.put(job_payload)

    elif exec_mode == 'create':
        # Create mode runs the job in worker VMs
        logger.debug(f'Starting process for job {job_key}')
        work_queue_name = job_key
        work_queue = work_queues.setdefault(work_queue_name, mp_manager.Queue())
        mp.Process(target=start_workers, args=(job_payload, work_queue_name)).start()
        jp = Thread(target=run_job_worker, args=(job_payload, work_queue, work_queue_name), daemon=True)
        jp.start()
        job_processes[job_key] = jp

    elif exec_mode == 'reuse':
        # Reuse mode runs the job on running workers
        logger.debug(f'Starting process for job {job_key}')
        work_queue_name = REUSE_WORK_QUEUE_NAME
        work_queue = work_queues.setdefault(work_queue_name, mp_manager.Queue())
        mp.Process(target=start_workers, args=(job_payload, work_queue_name)).start()
        jp = Thread(target=run_job_worker, args=(job_payload, work_queue, work_queue_name), daemon=True)
        jp.start()
        job_processes[job_key] = jp

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

    pull_runtime = standalone_config.get('pull_runtime', False)
    localhost_handler = LocalhostHandler({'runtime': runtime, 'pull_runtime': pull_runtime})
    localhost_handler.init()
    runtime_meta = localhost_handler.create_runtime(runtime)
    localhost_handler.clear()

    logger.info(runtime_meta)
    response = flask.jsonify(runtime_meta)
    response.status_code = 200

    return response


def main():
    global standalone_config
    global standalone_handler
    global budget_keeper
    global master_ip

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    with open(STANDALONE_CONFIG_FILE, 'r') as cf:
        standalone_config = json.load(cf)

    # Delete ssh_key_filename
    backend = standalone_config['backend']
    if 'ssh_key_filename' in standalone_config[backend]:
        del standalone_config[backend]['ssh_key_filename']

    vm_data_file = os.path.join(STANDALONE_INSTALL_DIR, 'access.data')
    with open(vm_data_file, 'r') as ad:
        master_ip = json.load(ad)['ip_address']

    budget_keeper = BudgetKeeper(standalone_config)
    budget_keeper.start()

    standalone_handler = budget_keeper.sh

    server = WSGIServer(('0.0.0.0', STANDALONE_SERVICE_PORT),
                        app, log=app.logger)
    server.serve_forever()


if __name__ == '__main__':
    main()
