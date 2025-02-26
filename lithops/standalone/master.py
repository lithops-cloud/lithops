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
import redis
import flask
import logging
import requests
import concurrent.futures as cf
from pathlib import Path
from datetime import datetime
from gevent.pywsgi import WSGIServer
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

from lithops.version import __version__
from lithops.localhost import LocalhostHandler
from lithops.standalone import LithopsValidationError
from lithops.standalone.keeper import BudgetKeeper
from lithops.config import extract_standalone_config
from lithops.standalone.standalone import StandaloneHandler
from lithops.version import __version__ as lithops_version
from lithops.constants import (
    CPU_COUNT,
    LITHOPS_TEMP_DIR,
    SA_MASTER_LOG_FILE,
    JOBS_DIR,
    SA_MASTER_SERVICE_PORT,
    SA_WORKER_SERVICE_PORT,
    SA_CONFIG_FILE,
    SA_MASTER_DATA_FILE
)
from lithops.utils import (
    verify_runtime_name,
    setup_lithops_logger
)
from lithops.standalone.utils import (
    JobStatus,
    StandaloneMode,
    WorkerStatus,
    get_host_setup_script,
    get_worker_setup_script
)

os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

log_format = "%(asctime)s\t[%(levelname)s] %(name)s:%(lineno)s -- %(message)s"
setup_lithops_logger(logging.DEBUG, filename=SA_MASTER_LOG_FILE, log_format=log_format)
logger = logging.getLogger('lithops.standalone.master')

app = flask.Flask(__name__)

MAX_INSTANCE_CREATE_RETRIES = 2
JOB_MONITOR_CHECK_INTERVAL = 1

redis_client = None
budget_keeper = None
master_ip = None


# /---------------------------------------------------------------------------/
# Workers
# /---------------------------------------------------------------------------/

def is_worker_free(worker_private_ip):
    """
    Checks if the Lithops service is ready and free in the worker VM instance
    """
    url = f"http://{worker_private_ip}:{SA_WORKER_SERVICE_PORT}/ping"
    try:
        r = requests.get(url, timeout=0.5)
        resp = r.json()
        logger.debug(f'Worker processes status from {worker_private_ip}: {resp}')
        return True if resp.get('free', 0) > 0 else False
    except Exception:
        return False


def get_worker_ttd(worker_private_ip):
    """
    Checks if the Lithops service is ready and free in the worker VM instance
    """
    try:
        if master_ip == worker_private_ip:
            ttd = str(budget_keeper.get_time_to_dismantle())
        else:
            url = f"http://{worker_private_ip}:{SA_WORKER_SERVICE_PORT}/ttd"
            r = requests.get(url, timeout=0.5)
            ttd = r.text
        logger.debug(f'Worker TTD from {worker_private_ip}: {ttd}')
        return ttd
    except Exception as e:
        logger.error(f"Unable to get TTD from {worker_private_ip}: {e}")
        return "Unknown"


@app.route('/worker/list', methods=['GET'])
def list_workers():
    """
    Returns the current workers list
    """
    logger.debug('Listing workers')

    budget_keeper.last_usage_time = time.time()

    result = [['Worker Name', 'Created', 'Instance Type', 'Processes', 'Runtime', 'Mode', 'Status', 'TTD']]

    def get_worker(worker):
        worker_data = redis_client.hgetall(worker)
        name = worker_data['name']
        status = worker_data['status']
        private_ip = worker_data['private_ip']
        ttd = get_worker_ttd(private_ip)
        ttd = ttd if ttd in ["Unknown", "Disabled"] else ttd + "s"
        timestamp = float(worker_data['created'])
        created = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')
        instance_type = worker_data['instance_type']
        worker_processes = str(worker_data['worker_processes'])
        exec_mode = worker_data['exec_mode']
        runtime = worker_data['runtime']
        result.append((name, created, instance_type, worker_processes, runtime, exec_mode, status, ttd))

    workers = redis_client.keys('worker:*')
    if workers:
        with ThreadPoolExecutor(len(workers)) as ex:
            ex.map(get_worker, workers)

    logger.debug(f"workers: {result}")
    return flask.jsonify(result)


@app.route('/worker/get', methods=['GET'])
def get_workers():
    """
    Returns the number of free workers
    """
    budget_keeper.last_usage_time = time.time()

    workers = redis_client.keys('worker:*')
    logger.debug(f'Getting workers - Total workers: {len(workers)}')

    payload = flask.request.get_json(force=True, silent=True)
    if payload and not isinstance(payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    worker_instance_type = payload['worker_instance_type']
    worker_processes = payload['worker_processes']
    runtime_name = payload['runtime_name']

    active_workers = []

    for worker in workers:
        worker_data = redis_client.hgetall(worker)
        if worker_data['instance_type'] == worker_instance_type \
           and worker_data['runtime'] == runtime_name \
           and int(worker_data['worker_processes']) == int(worker_processes):
            active_workers.append(worker_data)

    worker_type = f'{worker_instance_type}-{worker_processes}-{runtime_name}'
    logger.debug(f'Workers for {worker_type}: {len(active_workers)}')

    free_workers = []

    def check_worker(worker_data):
        if is_worker_free(worker_data['private_ip']):
            free_workers.append(
                (
                    worker_data['name'],
                    worker_data['private_ip'],
                    worker_data['instance_id'],
                    worker_data['ssh_credentials'],
                    worker_data['instance_type'],
                    runtime_name
                )
            )

    if active_workers:
        with ThreadPoolExecutor(len(active_workers)) as ex:
            ex.map(check_worker, active_workers)

    logger.debug(f'Free workers for {worker_type}: {len(free_workers)}')

    response = flask.jsonify(free_workers)
    response.status_code = 200

    return response


def save_worker(worker, standalone_config, work_queue_name):
    """
    Saves the worker instance with the provided data in redis
    """
    config = copy.deepcopy(standalone_config)
    del config[config['backend']]
    config = {key: str(value) if isinstance(value, bool) else value for key, value in config.items()}

    worker_processes = CPU_COUNT if worker.config['worker_processes'] == 'AUTO' \
        else worker.config['worker_processes']

    redis_client.hset(f"worker:{worker.name}", mapping={
        'name': worker.name,
        'status': WorkerStatus.STARTING.value,
        'private_ip': worker.private_ip or '',
        'instance_id': worker.instance_id or '',
        'instance_type': worker.instance_type,
        'worker_processes': worker_processes,
        'created': str(time.time()),
        'ssh_credentials': json.dumps(worker.ssh_credentials),
        'queue_name': work_queue_name,
        'err': "", **config,
    })


def setup_worker_create_reuse(standalone_handler, worker_info, work_queue_name):
    """
    Run the worker setup process and installs all the Lithops dependencies into it
    """
    worker = standalone_handler.backend.get_instance(**worker_info, public=False)

    if redis_client.hget(f"worker:{worker.name}", 'status') == WorkerStatus.ACTIVE.value:
        return

    save_worker(worker, standalone_handler.config, work_queue_name)

    max_instance_create_retries = worker.config.get('worker_create_retries', MAX_INSTANCE_CREATE_RETRIES)

    def wait_worker_ready(worker):
        instance_ready_retries = 1

        while instance_ready_retries <= max_instance_create_retries:
            try:
                worker.wait_ready()
                break
            except TimeoutError as e:  # VM not started in time
                redis_client.hset(f"worker:{worker.name}", 'status', WorkerStatus.ERROR.value)
                err_msg = 'Timeout Error while waitting the VM to get ready'
                redis_client.hset(f"worker:{worker.name}", 'err', err_msg)
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
            redis_client.hset(f"worker:{worker.name}", 'status', WorkerStatus.ERROR.value)
            redis_client.hset(f"worker:{worker.name}", 'err', f'Validation error: {e}')
            if instance_validate_retries == max_instance_create_retries:
                logger.debug(f'Validation probe expired for {worker}')
                raise e
            logger.warning(f'{worker} validation error: {e}')
            worker.delete()
            worker.create()
            instance_validate_retries += 1
            wait_worker_ready(worker)

    redis_client.hset(f"worker:{worker.name}", 'private_ip', worker.private_ip)
    redis_client.hset(f"worker:{worker.name}", 'status', WorkerStatus.STARTED.value)
    redis_client.hset(f"worker:{worker.name}", 'err', '')

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
            'work_queue_name': work_queue_name,
            'lithops_version': __version__
        }
        remote_script = "/tmp/install_lithops.sh"
        script = get_host_setup_script()
        script += get_worker_setup_script(standalone_handler.config, vm_data)

        logger.debug(f'Submitting installation script to {worker}')
        worker.get_ssh_client().upload_data_to_file(script, remote_script)
        cmd = f"chmod 755 {remote_script}; sudo {remote_script}; rm {remote_script}"
        worker.get_ssh_client().run_remote_command(cmd, run_async=True)
        worker.del_ssh_client()

        logger.debug(f'Installation script submitted to {worker}')
        redis_client.hset(f"worker:{worker.name}", 'status', WorkerStatus.INSTALLING.value)

    except Exception as e:
        redis_client.hset(f"worker:{worker.name}", 'status', WorkerStatus.ERROR.value)
        worker.err = f'Unable to setup lithops in the VM: {str(e)}'
        raise e


def setup_worker_consume(standalone_handler, worker_info, work_queue_name):
    """
    Run the worker setup process in the case of Consume mode
    """
    instance = standalone_handler.backend.get_instance(**worker_info, public=False)
    instance.private_ip = master_ip

    if redis_client.hget(f"worker:{instance.name}", 'status') == WorkerStatus.ACTIVE.value:
        return

    save_worker(instance, standalone_handler.config, work_queue_name)

    try:
        logger.debug(f'Setting up the worker in the current {instance}')
        vm_data = {
            'name': instance.name,
            'private_ip': instance.private_ip,
            'instance_id': instance.instance_id,
            'ssh_credentials': instance.ssh_credentials,
            'instance_type': instance.instance_type,
            'master_ip': master_ip,
            'work_queue_name': work_queue_name,
            'lithops_version': __version__
        }
        worker_setup_script = "/tmp/install_lithops.sh"
        script = get_worker_setup_script(standalone_handler.config, vm_data)
        with open(worker_setup_script, 'w') as wis:
            wis.write(script)

        redis_client.hset(f"worker:{instance.name}", 'status', WorkerStatus.INSTALLING.value)
        os.chmod(worker_setup_script, 0o755)
        os.system("sudo " + worker_setup_script)
        os.remove(worker_setup_script)

    except Exception as e:
        redis_client.hset(f"worker:{instance.name}", 'status', WorkerStatus.ERROR.value)
        instance.err = f'Unable to setup lithops in the VM: {str(e)}'
        raise e


def handle_workers(job_payload, workers, work_queue_name):
    """
    Creates the workers (if any)
    """
    if not workers:
        return

    logger.debug(f"Going to setup {len(workers)} workers")

    standalone_config = extract_standalone_config(job_payload['config'])
    standalone_handler = StandaloneHandler(standalone_config)

    futures = []
    total_correct = 0

    if standalone_config['exec_mode'] == StandaloneMode.CONSUME.value:
        try:
            setup_worker_consume(
                standalone_handler,
                workers[0],
                work_queue_name
            )
            total_correct += 1
        except Exception as e:
            # TODO: If the local worker can't start, cancel all jobs
            # in the budget keeper
            logger.error(e)
    else:
        with ThreadPoolExecutor(len(workers)) as executor:
            for worker_info in workers:
                future = executor.submit(
                    setup_worker_create_reuse,
                    standalone_handler,
                    worker_info,
                    work_queue_name
                )
                futures.append(future)

        for future in cf.as_completed(futures):
            try:
                future.result()
                total_correct += 1
            except Exception as e:
                logger.error(e)

    logger.debug(
        f'{total_correct} of {len(workers)} workers started '
        f'for work queue: {work_queue_name}'
    )


# /---------------------------------------------------------------------------/
# Jobs
# /---------------------------------------------------------------------------/

def cancel_job_process(job_key_list):
    """
    Cleans the work queues and sends the SIGTERM to the workers
    """
    for job_key in job_key_list:
        logger.debug(f'Received SIGTERM: Stopping job process {job_key}')

        queue_name = redis_client.hget(f'job:{job_key}', 'queue_name')

        tmp_queue = []
        while redis_client.llen(queue_name) > 0:
            task_payload_json = redis_client.rpop(queue_name)
            task_payload = json.loads(task_payload_json)
            if task_payload['job_key'] != job_key:
                tmp_queue.append(task_payload_json)

        for task_payload_json in tmp_queue:
            redis_client.lpush(queue_name, task_payload_json)

        def stop_task(worker):
            worker_data = redis_client.hgetall(worker)
            url = f"http://{worker_data['private_ip']}:{SA_WORKER_SERVICE_PORT}/stop/{job_key}"
            requests.post(url, timeout=0.5)

        # Send stop signal to all workers
        workers = redis_client.keys('worker:*')
        with ThreadPoolExecutor(len(workers)) as ex:
            ex.map(stop_task, workers)

        Path(os.path.join(JOBS_DIR, job_key + '.done')).touch()
        if redis_client.hget(f"job:{job_key}", 'status') != JobStatus.DONE.value:
            redis_client.hset(f"job:{job_key}", 'status', JobStatus.CANCELED.value)


@app.route('/job/stop', methods=['POST'])
def stop():
    """
    Stops received job processes
    """
    job_key_list = flask.request.get_json(force=True, silent=True)
    # Start a separate thread to do the task in background,
    # for not keeping the client waiting.
    Thread(target=cancel_job_process, args=(job_key_list, )).start()

    return ('', 204)


@app.route('/job/list', methods=['GET'])
def list_jobs():
    """
    Returns the current workers state
    """
    logger.debug('Listing jobs')

    budget_keeper.last_usage_time = time.time()

    result = [['Job ID', 'Function Name', 'Submitted', 'Worker Type', 'Runtime', 'Tasks Done', 'Job Status']]

    for job_job_key in redis_client.keys('job:*'):
        job_data = redis_client.hgetall(job_job_key)
        job_key = job_data['job_key']
        exec_mode = job_data['exec_mode']
        status = job_data['status']
        func_name = job_data['func_name'] + "()"
        timestamp = float(job_data['submitted'])
        runtime = job_data['runtime_name']
        worker_type = job_data['worker_type'] if exec_mode != StandaloneMode.CONSUME.value else 'VM'
        submitted = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')
        total_tasks = str(job_data['total_tasks'])
        done_tasks = str(redis_client.llen(f'tasksdone:{job_key}'))
        job = (job_key, func_name, submitted, worker_type, runtime, f'{done_tasks}/{total_tasks}', status)
        result.append(job)

    logger.debug(f'jobs: {result}')
    return flask.jsonify(result)


def handle_job(job_payload, queue_name):
    """
    Process responsible to put the job in redis and all the
    individual tasks in a work queue
    """
    job_key = job_payload['job_key']

    redis_client.hset(f"job:{job_key}", mapping={
        'job_key': job_key,
        'status': JobStatus.SUBMITTED.value,
        'submitted': job_payload['host_submit_tstamp'],
        'func_name': job_payload['func_name'],
        'worker_type': job_payload.get('worker_instance_type', 'VM'),
        'runtime_name': job_payload['runtime_name'],
        'exec_mode': job_payload['config']['standalone']['exec_mode'],
        'total_tasks': len(job_payload['call_ids']),
        'queue_name': queue_name
    })

    dbr = job_payload['data_byte_ranges']
    for call_id in job_payload['call_ids']:
        task_payload = copy.deepcopy(job_payload)
        task_payload['call_ids'] = [call_id]
        task_payload['data_byte_ranges'] = [dbr[int(call_id)]]
        redis_client.lpush(queue_name, json.dumps(task_payload))

    logger.debug(f"Job {job_key} correctly submitted to work queue '{queue_name}'")


@app.route('/job/run', methods=['POST'])
def run():
    """
    Entry point for running jobs
    """
    job_payload = flask.request.get_json(force=True, silent=True)
    if job_payload and not isinstance(job_payload, dict):
        return error('The action did not receive a dictionary as an argument')

    try:
        runtime_name = job_payload['runtime_name']
        verify_runtime_name(runtime_name)
    except Exception as e:
        return error(str(e))

    job_key = job_payload['job_key']
    logger.debug(f'Received job {job_key}')

    budget_keeper.add_job(job_key)

    exec_mode = job_payload['config']['standalone']['exec_mode']
    exec_mode = StandaloneMode[exec_mode.upper()]
    workers = job_payload.pop('worker_instances')

    if exec_mode == StandaloneMode.CONSUME:
        queue_name = f'wq:localhost:{runtime_name.replace("/", "-")}'.lower()
    elif exec_mode == StandaloneMode.CREATE:
        queue_name = f'wq:{job_key}'.lower()
    elif exec_mode == StandaloneMode.REUSE:
        worker_it = job_payload['worker_instance_type']
        worker_wp = job_payload['worker_processes']
        queue_name = f'wq:{worker_it}-{worker_wp}-{runtime_name.replace("/", "-")}'.lower()

    Thread(target=handle_job, args=(job_payload, queue_name)).start()
    Thread(target=handle_workers, args=(job_payload, workers, queue_name)).start()

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    response = flask.jsonify({'activationId': act_id})
    response.status_code = 202

    return response


def job_monitor():
    logger.info("Starting job monitoring thread")

    jobs_data = {}

    while True:
        time.sleep(JOB_MONITOR_CHECK_INTERVAL)
        for job_job_key in redis_client.keys('job:*'):
            job_key = job_job_key.replace("job:", "")
            if job_key not in jobs_data:
                budget_keeper.add_job(job_key)
                job_data = redis_client.hgetall(job_job_key)
                jobs_data[job_key] = {'total': int(job_data['total_tasks']), 'done': 0}
            if jobs_data[job_key]['total'] == jobs_data[job_key]['done']:
                continue
            done_tasks = int(redis_client.llen(f"tasksdone:{job_key}"))
            if jobs_data[job_key]['done'] != done_tasks:
                total_tasks = jobs_data[job_key]['total']
                jobs_data[job_key]['done'] = done_tasks
                exec_id, job_id = job_key.rsplit('-', 1)
                msg = f"ExecutorID: {exec_id} | JObID: {job_id} - Tasks done: {done_tasks}/{total_tasks}"
                if jobs_data[job_key]['total'] == jobs_data[job_key]['done']:
                    Path(os.path.join(JOBS_DIR, f'{job_key}.done')).touch()
                    msg += " - Completed!"
                logger.debug(msg)


# /---------------------------------------------------------------------------/
# Misc
# /---------------------------------------------------------------------------/

@app.route('/clean', methods=['POST'])
def clean():
    logger.debug("Clean command received. Cleaning all data from redis")
    redis_client.flushall()

    return ('', 204)


@app.route('/ping', methods=['GET'])
def ping():
    response = flask.jsonify({'response': lithops_version})
    response.status_code = 200
    return response


def error(msg):
    response = flask.jsonify({'error': msg})
    response.status_code = 404
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
        logger.debug(f"Runtime metdata extracted correctly from {payload['runtime']}"
                     f" - Lithops {runtime_meta['lithops_version']}")
    response = flask.jsonify(runtime_meta)
    response.status_code = 200

    return response


def main():
    global redis_client
    global budget_keeper
    global master_ip

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    with open(SA_CONFIG_FILE, 'r') as cf:
        standalone_config = json.load(cf)

    with open(SA_MASTER_DATA_FILE, 'r') as ad:
        master_data = json.load(ad)
        master_ip = master_data['private_ip']

    budget_keeper = BudgetKeeper(standalone_config, master_data, stop_callback=clean)
    budget_keeper.start()

    redis_client = redis.Redis(decode_responses=True)

    Thread(target=job_monitor, daemon=True).start()

    server = WSGIServer(('0.0.0.0', SA_MASTER_SERVICE_PORT), app, log=app.logger)
    server.serve_forever()


if __name__ == '__main__':
    main()
