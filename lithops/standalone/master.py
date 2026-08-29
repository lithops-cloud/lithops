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
from lithops.constants import (
    CPU_COUNT,
    LITHOPS_TEMP_DIR,
    SA_MASTER_LOG_FILE,
    JOBS_DIR,
    SA_MASTER_SERVICE_PORT,
    SA_WORKER_SERVICE_PORT,
    SA_CONFIG_FILE,
    SA_MASTER_DATA_FILE,
)
from lithops.utils import (
    verify_runtime_name,
    setup_lithops_logger,
    log_prefix,
)
from lithops.standalone.utils import (
    JobStatus,
    StandaloneMode,
    WorkerStatus,
    get_host_setup_script,
    get_worker_setup_script,
    install_script_kwargs_from_config,
)

logger = logging.getLogger('lithops.standalone.master')

app = flask.Flask(__name__)

MAX_INSTANCE_CREATE_RETRIES = 2
JOB_MONITOR_CHECK_INTERVAL = 1
_LOG_FORMAT = (
    "%(asctime)s\t[%(levelname)s] %(name)s:%(lineno)s -- %(message)s"
)
_NOT_A_DICT = 'The action did not receive a dictionary as an argument.'

redis_client = None
budget_keeper = None
master_ip = None


def _configure_logging():
    """Sends everything this service logs to the master log"""
    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
    setup_lithops_logger(
        logging.DEBUG, filename=SA_MASTER_LOG_FILE, log_format=_LOG_FORMAT
    )


def _json_body():
    """Returns the body of the request, or None when it is not JSON"""
    return flask.request.get_json(force=True, silent=True)


def _require_dict(payload):
    """Returns an error response when the body is not a dictionary"""
    if not isinstance(payload, dict):
        return error(_NOT_A_DICT)
    return None


def _map_if_any(fn, items):
    """
    Runs fn over every item in parallel, reporting the ones that failed.
    Nothing here is fatal: a worker that cannot be reached is a row missing
    from a listing or a stop request nobody answered, not a failed call
    """
    if not items:
        return

    with ThreadPoolExecutor(len(items)) as executor:
        futures = [executor.submit(fn, item) for item in items]

    # Results are only read once every thread is done, since a lazy map()
    # would drop the errors on the floor
    for item, future in zip(items, futures):
        try:
            future.result()
        except Exception as e:
            logger.error(f'Could not process {item}: {e}')


def _worker_key(worker_name):
    """Returns the redis key holding the state of a worker"""
    return f"worker:{worker_name}"


def _job_key_id(job_key):
    """Returns the redis key holding the state of a job"""
    return f"job:{job_key}"


# /---------------------------------------------------------------------------/
# Workers
# /---------------------------------------------------------------------------/

def is_worker_free(worker_private_ip):
    """
    True when the Lithops service of a worker answers and has a free process.
    A worker that cannot be reached counts as not free, as there is no way to
    give it any work
    """
    url = f"http://{worker_private_ip}:{SA_WORKER_SERVICE_PORT}/ping"
    try:
        resp = requests.get(url, timeout=0.5).json()
        logger.debug(f'Worker processes status from {worker_private_ip}: {resp}')
        return resp.get('free', 0) > 0
    except Exception as e:
        logger.debug(f'Worker {worker_private_ip} did not answer: {e}')
        return False


def get_worker_ttd(worker_private_ip):
    """
    Returns the seconds left before a worker stops itself, asking the worker
    unless it is this very instance, and Unknown when it cannot be asked
    """
    try:
        if master_ip == worker_private_ip:
            ttd = str(budget_keeper.get_time_to_dismantle())
        else:
            url = f"http://{worker_private_ip}:{SA_WORKER_SERVICE_PORT}/ttd"
            ttd = requests.get(url, timeout=0.5).text
        logger.debug(f'Worker TTD from {worker_private_ip}: {ttd}')
        return ttd
    except Exception as e:
        logger.error(f"Unable to get TTD from {worker_private_ip}: {e}")
        return "Unknown"


@app.route('/worker/list', methods=['GET'])
def list_workers():
    """Returns a table of every worker the master knows about"""
    logger.debug('Listing workers')
    budget_keeper.last_usage_time = time.time()

    result = [[
        'Worker Name', 'Created', 'Instance Type', 'Processes',
        'Runtime', 'Mode', 'Status', 'TTD',
    ]]

    def get_worker(worker):
        """Appends the row of one worker to the table"""
        worker_data = redis_client.hgetall(worker)
        ttd = get_worker_ttd(worker_data['private_ip'])
        ttd = ttd if ttd in ["Unknown", "Disabled"] else ttd + "s"
        created = datetime.fromtimestamp(
            float(worker_data['created'])
        ).strftime('%Y-%m-%d %H:%M:%S UTC')
        result.append((
            worker_data['name'],
            created,
            worker_data['instance_type'],
            str(worker_data['worker_processes']),
            worker_data['runtime'],
            worker_data['exec_mode'],
            worker_data['status'],
            ttd,
        ))

    _map_if_any(get_worker, redis_client.keys('worker:*'))
    logger.debug(f"workers: {result}")
    return flask.jsonify(result)


@app.route('/worker/get', methods=['GET'])
def get_workers():
    """
    Returns the workers that are free and of the shape the caller asked for,
    which is how reuse mode finds the workers a new job can run on
    """
    budget_keeper.last_usage_time = time.time()

    workers = redis_client.keys('worker:*')
    logger.debug(f'Getting workers - Total workers: {len(workers)}')

    payload = _json_body()
    bad_request = _require_dict(payload)
    if bad_request is not None:
        return bad_request

    worker_instance_type = payload['worker_instance_type']
    worker_processes = payload['worker_processes']
    runtime_name = payload['runtime_name']

    active_workers = []
    for worker in workers:
        worker_data = redis_client.hgetall(worker)
        if (
            worker_data['instance_type'] == worker_instance_type
            and worker_data['runtime'] == runtime_name
            and int(worker_data['worker_processes']) == int(worker_processes)
        ):
            active_workers.append(worker_data)

    worker_type = f'{worker_instance_type}-{worker_processes}-{runtime_name}'
    logger.debug(f'Workers for {worker_type}: {len(active_workers)}')

    free_workers = []

    def check_worker(worker_data):
        """Keeps a worker that still has a free process"""
        if is_worker_free(worker_data['private_ip']):
            free_workers.append((
                worker_data['name'],
                worker_data['private_ip'],
                worker_data['instance_id'],
                worker_data['ssh_credentials'],
                worker_data['instance_type'],
                runtime_name,
            ))

    _map_if_any(check_worker, active_workers)
    logger.debug(f'Free workers for {worker_type}: {len(free_workers)}')

    response = flask.jsonify(free_workers)
    response.status_code = 200
    return response


def _redis_field(value):
    """
    Returns a config value as something a redis hash accepts, which is only
    bytes, str, int or float
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, bool):
        return str(value)
    return value


def save_worker(worker, standalone_config, work_queue_name):
    """
    Registers a worker in redis, which is where every listing and every
    lookup of a free worker reads from. The backend section is left out, as
    it holds the credentials of the account
    """
    config = copy.deepcopy(standalone_config)
    del config[config['backend']]
    config = {key: _redis_field(value) for key, value in config.items()}

    worker_processes = (
        CPU_COUNT if worker.config['worker_processes'] == 'AUTO'
        else worker.config['worker_processes']
    )

    redis_client.hset(_worker_key(worker.name), mapping={
        'name': worker.name,
        'status': WorkerStatus.STARTING.value,
        'private_ip': worker.private_ip or '',
        'instance_id': worker.instance_id or '',
        'instance_type': worker.instance_type,
        'worker_processes': worker_processes,
        'created': str(time.time()),
        'ssh_credentials': json.dumps(worker.ssh_credentials),
        'queue_name': work_queue_name,
        'err': "",
        **config,
    })


def _worker_vm_data(instance, work_queue_name):
    """Returns the data a worker VM needs to reach the master and its queue"""
    return {
        'name': instance.name,
        'private_ip': instance.private_ip,
        'instance_id': instance.instance_id,
        'ssh_credentials': instance.ssh_credentials,
        'instance_type': instance.instance_type,
        'master_ip': master_ip,
        'work_queue_name': work_queue_name,
        'lithops_version': __version__,
    }


def _mark_worker_error(worker_name, message):
    """Records why a worker could not be set up, for the worker listing"""
    redis_client.hset(_worker_key(worker_name), mapping={
        'status': WorkerStatus.ERROR.value,
        'err': message,
    })


def _worker_setup_script(standalone_handler, vm_data):
    """Returns the script that installs Lithops and the service on a worker"""
    script = get_host_setup_script(
        run_install=False,
        **install_script_kwargs_from_config(standalone_handler.config),
    )
    script += get_worker_setup_script(standalone_handler.config, vm_data)
    return script


def setup_worker_create_reuse(standalone_handler, worker_info, work_queue_name):
    """
    Installs Lithops on a worker VM, recreating the instance when it does not
    come up or does not have what the runtime needs. The installation itself
    is left running in the background, and the worker reports back when its
    service comes up
    """
    worker = standalone_handler.backend.get_instance(**worker_info, public=False)

    if redis_client.hget(_worker_key(worker.name), 'status') == WorkerStatus.ACTIVE.value:
        return

    save_worker(worker, standalone_handler.config, work_queue_name)

    max_retries = worker.config.get(
        'worker_create_retries', MAX_INSTANCE_CREATE_RETRIES
    )

    def wait_worker_ready(worker):
        """Waits for a worker to boot, recreating it while there are tries left"""
        instance_ready_retries = 1
        while instance_ready_retries <= max_retries:
            try:
                worker.wait_ready()
                break
            except TimeoutError:
                err_msg = 'Timeout Error while waiting the VM to get ready'
                _mark_worker_error(worker.name, err_msg)
                if instance_ready_retries == max_retries:
                    logger.debug(f'Readiness probe expired for {worker}')
                    raise
                logger.warning(f'Timeout Error. Recreating {worker}')
                worker.delete()
                worker.create()
                instance_ready_retries += 1

    wait_worker_ready(worker)

    instance_validate_retries = 1
    while instance_validate_retries <= max_retries:
        try:
            logger.debug(f'Validating {worker}')
            worker.validate_capabilities()
            break
        except LithopsValidationError as e:
            _mark_worker_error(worker.name, f'Validation error: {e}')
            if instance_validate_retries == max_retries:
                logger.debug(f'Validation probe expired for {worker}')
                raise
            logger.warning(f'{worker} validation error: {e}')
            worker.delete()
            worker.create()
            instance_validate_retries += 1
            wait_worker_ready(worker)

    redis_client.hset(_worker_key(worker.name), mapping={
        'private_ip': worker.private_ip,
        'status': WorkerStatus.STARTED.value,
        'err': '',
    })

    try:
        logger.debug(f'Uploading lithops files to {worker}')
        worker.get_ssh_client().upload_local_file(
            '/opt/lithops/lithops_standalone.zip',
            '/tmp/lithops_standalone.zip',
        )

        logger.debug(f'Preparing installation script for {worker}')
        remote_script = "/tmp/install_lithops.sh"
        script = _worker_setup_script(
            standalone_handler, _worker_vm_data(worker, work_queue_name)
        )

        logger.debug(f'Submitting installation script to {worker}')
        worker.get_ssh_client().upload_data_to_file(script, remote_script)
        cmd = f"chmod 755 {remote_script}; sudo {remote_script}; rm {remote_script}"
        worker.get_ssh_client().run_remote_command(cmd, run_async=True)
        worker.del_ssh_client()

        logger.debug(f'Installation script submitted to {worker}')
        redis_client.hset(
            _worker_key(worker.name), 'status', WorkerStatus.INSTALLING.value
        )
    except Exception as e:
        _mark_worker_error(
            worker.name, f'Unable to setup lithops in the VM: {e}'
        )
        raise


def setup_worker_consume(standalone_handler, worker_info, work_queue_name):
    """
    Installs the worker service on this very instance, which is what consume
    mode runs the jobs on
    """
    instance = standalone_handler.backend.get_instance(**worker_info, public=False)
    instance.private_ip = master_ip

    if redis_client.hget(_worker_key(instance.name), 'status') == WorkerStatus.ACTIVE.value:
        return

    save_worker(instance, standalone_handler.config, work_queue_name)

    try:
        logger.debug(f'Setting up the worker in the current {instance}')
        worker_setup_script = "/tmp/install_lithops.sh"
        script = _worker_setup_script(
            standalone_handler, _worker_vm_data(instance, work_queue_name)
        )
        with open(worker_setup_script, 'w') as script_file:
            script_file.write(script)

        redis_client.hset(
            _worker_key(instance.name),
            'status',
            WorkerStatus.INSTALLING.value,
        )
        os.chmod(worker_setup_script, 0o755)
        # os.system reports the wait status, not the exit code, so it is
        # logged as such rather than as a number that looks like one
        wait_status = os.system("sudo " + worker_setup_script)
        if wait_status != 0:
            logger.error(
                f'The setup script of {instance} failed with wait status '
                f'{wait_status}'
            )
        os.remove(worker_setup_script)
    except Exception as e:
        _mark_worker_error(
            instance.name, f'Unable to setup lithops in the VM: {e}'
        )
        raise


def handle_workers(job_payload, workers, work_queue_name):
    """
    Sets up every worker of a job in parallel. A worker that fails to be set
    up is one worker less, and the job runs on the ones that came up
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
                standalone_handler, workers[0], work_queue_name
            )
            total_correct += 1
        except Exception as e:
            logger.error(e)
    else:
        with ThreadPoolExecutor(len(workers)) as executor:
            for worker_info in workers:
                futures.append(executor.submit(
                    setup_worker_create_reuse,
                    standalone_handler,
                    worker_info,
                    work_queue_name,
                ))

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
    Cancels jobs: takes their tasks out of the work queue, tells every worker
    to kill the ones already running, and marks the jobs as canceled
    """
    for job_key in job_key_list:
        logger.debug(f'Received SIGTERM: Stopping job process {job_key}')

        queue_name = redis_client.hget(_job_key_id(job_key), 'queue_name')
        if not queue_name:
            logger.debug(f'Job {job_key} has no work queue to clean')
            continue

        tmp_queue = []
        while redis_client.llen(queue_name) > 0:
            task_payload_json = redis_client.rpop(queue_name)
            if task_payload_json is None:
                # A worker took the last task between the two calls
                break
            task_payload = json.loads(task_payload_json)
            if task_payload['job_key'] != job_key:
                tmp_queue.append(task_payload_json)

        for task_payload_json in tmp_queue:
            redis_client.lpush(queue_name, task_payload_json)

        def stop_task(worker):
            """Asks one worker to kill the tasks of this job"""
            worker_data = redis_client.hgetall(worker)
            url = (
                f"http://{worker_data['private_ip']}:"
                f"{SA_WORKER_SERVICE_PORT}/stop/{job_key}"
            )
            requests.post(url, timeout=0.5)

        _map_if_any(stop_task, redis_client.keys('worker:*'))

        Path(os.path.join(JOBS_DIR, job_key + '.done')).touch()
        if redis_client.hget(_job_key_id(job_key), 'status') != JobStatus.DONE.value:
            redis_client.hset(
                _job_key_id(job_key), 'status', JobStatus.CANCELED.value
            )


@app.route('/job/stop', methods=['POST'])
def stop():
    """Cancels the given jobs, in the background"""
    job_key_list = _json_body()
    if not isinstance(job_key_list, list):
        return error('The action did not receive a list as an argument.')
    Thread(target=cancel_job_process, args=(job_key_list,)).start()
    return ('', 204)


@app.route('/job/list', methods=['GET'])
def list_jobs():
    """Returns a table of every job the master knows about"""
    logger.debug('Listing jobs')
    budget_keeper.last_usage_time = time.time()

    result = [[
        'Job ID', 'Function Name', 'Submitted', 'Worker Type',
        'Runtime', 'Tasks Done', 'Job Status',
    ]]

    for job_redis_key in redis_client.keys('job:*'):
        job_data = redis_client.hgetall(job_redis_key)
        job_key = job_data['job_key']
        exec_mode = job_data['exec_mode']
        timestamp = float(job_data['submitted'])
        worker_type = (
            job_data['worker_type']
            if exec_mode != StandaloneMode.CONSUME.value
            else 'VM'
        )
        submitted = datetime.fromtimestamp(timestamp).strftime(
            '%Y-%m-%d %H:%M:%S UTC'
        )
        total_tasks = str(job_data['total_tasks'])
        done_tasks = str(redis_client.llen(f'tasksdone:{job_key}'))
        result.append((
            job_key,
            job_data['func_name'] + "()",
            submitted,
            worker_type,
            job_data['runtime_name'],
            f'{done_tasks}/{total_tasks}',
            job_data['status'],
        ))

    logger.debug(f'jobs: {result}')
    return flask.jsonify(result)


def handle_job(job_payload, queue_name):
    """
    Registers a job and pushes one task per call into its work queue, each
    task carrying only the data range of its own call
    """
    job_key = job_payload['job_key']

    redis_client.hset(_job_key_id(job_key), mapping={
        'job_key': job_key,
        'status': JobStatus.SUBMITTED.value,
        'submitted': job_payload['host_submit_tstamp'],
        'func_name': job_payload['func_name'],
        'worker_type': job_payload.get('worker_instance_type', 'VM'),
        'runtime_name': job_payload['runtime_name'],
        'exec_mode': job_payload['config']['standalone']['exec_mode'],
        'total_tasks': len(job_payload['call_ids']),
        'queue_name': queue_name,
    })

    dbr = job_payload['data_byte_ranges']
    for call_id in job_payload['call_ids']:
        task_payload = copy.deepcopy(job_payload)
        task_payload['call_ids'] = [call_id]
        task_payload['data_byte_ranges'] = [dbr[int(call_id)]]
        redis_client.lpush(queue_name, json.dumps(task_payload))

    logger.debug(
        f"Job {job_key} correctly submitted to work queue '{queue_name}'"
    )


@app.route('/job/run', methods=['POST'])
def run():
    """
    Takes a job in: queues its tasks and sets its workers up, both in the
    background, so that the caller is not left waiting for the VMs
    """
    job_payload = _json_body()
    bad_request = _require_dict(job_payload)
    if bad_request is not None:
        return bad_request

    try:
        runtime_name = job_payload['runtime_name']
        verify_runtime_name(runtime_name)
    except Exception as e:
        return error(str(e))

    job_key = job_payload['job_key']
    logger.debug(f'Received job {job_key}')

    budget_keeper.add_job(job_key)

    exec_mode = StandaloneMode[
        job_payload['config']['standalone']['exec_mode'].upper()
    ]
    workers = job_payload.pop('worker_instances')

    if exec_mode == StandaloneMode.CONSUME:
        queue_name = f'wq:localhost:{runtime_name.replace("/", "-")}'.lower()
    elif exec_mode == StandaloneMode.CREATE:
        queue_name = f'wq:{job_key}'.lower()
    elif exec_mode == StandaloneMode.REUSE:
        worker_it = job_payload['worker_instance_type']
        worker_wp = job_payload['worker_processes']
        queue_name = (
            f'wq:{worker_it}-{worker_wp}-{runtime_name.replace("/", "-")}'
        ).lower()

    Thread(target=handle_job, args=(job_payload, queue_name)).start()
    Thread(target=handle_workers, args=(job_payload, workers, queue_name)).start()

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    response = flask.jsonify({'activationId': act_id})
    response.status_code = 202
    return response


def job_monitor():
    """
    Follows the tasks of every job as they finish, reporting the progress and
    leaving behind the done file the budget keeper watches
    """
    logger.info("Starting job monitoring thread")
    jobs_data = {}

    while True:
        time.sleep(JOB_MONITOR_CHECK_INTERVAL)
        for job_redis_key in redis_client.keys('job:*'):
            job_key = job_redis_key.replace("job:", "")
            if job_key not in jobs_data:
                budget_keeper.add_job(job_key)
                job_data = redis_client.hgetall(job_redis_key)
                jobs_data[job_key] = {
                    'total': int(job_data['total_tasks']),
                    'done': 0,
                }
            if jobs_data[job_key]['total'] == jobs_data[job_key]['done']:
                continue
            done_tasks = int(redis_client.llen(f"tasksdone:{job_key}"))
            if jobs_data[job_key]['done'] != done_tasks:
                total_tasks = jobs_data[job_key]['total']
                jobs_data[job_key]['done'] = done_tasks
                exec_id, job_id = job_key.rsplit('-', 1)
                msg = (
                    f'{log_prefix(exec_id, job_id)} - '
                    f'Tasks done: {done_tasks}/{total_tasks}'
                )
                if jobs_data[job_key]['total'] == jobs_data[job_key]['done']:
                    Path(os.path.join(JOBS_DIR, f'{job_key}.done')).touch()
                    msg += " - Completed!"
                logger.debug(msg)


# /---------------------------------------------------------------------------/
# Misc
# /---------------------------------------------------------------------------/

@app.route('/clean', methods=['POST'])
def clean():
    """Drops every job and worker the master had recorded"""
    logger.debug("Clean command received. Cleaning all data from redis")
    redis_client.flushall()
    return ('', 204)


@app.route('/ping', methods=['GET'])
def ping():
    """Answers with the Lithops version this master runs"""
    response = flask.jsonify({'response': __version__})
    response.status_code = 200
    return response


def error(msg):
    """Builds the response of a request the master could not act on"""
    response = flask.jsonify({'error': msg})
    response.status_code = 404
    return response


@app.route('/metadata', methods=['GET'])
def get_metadata():
    """
    Returns the metadata of a runtime, which the master extracts by running
    it locally, as it is the only instance that is up at this point
    """
    payload = _json_body()
    bad_request = _require_dict(payload)
    if bad_request is not None:
        return bad_request

    try:
        verify_runtime_name(payload['runtime'])
    except Exception as e:
        return error(str(e))

    localhost_handler = LocalhostHandler(payload)
    localhost_handler.init()
    runtime_meta = localhost_handler.deploy_runtime(payload['runtime'])

    if 'lithops_version' in runtime_meta:
        logger.debug(
            f"Runtime metadata extracted correctly from {payload['runtime']}"
            f" - Lithops {runtime_meta['lithops_version']}"
        )
    response = flask.jsonify(runtime_meta)
    response.status_code = 200
    return response


def main():
    """
    Entry point of the master service: starts the countdown that stops the
    instance, the job monitor, and the endpoints the client talks to
    """
    global redis_client
    global budget_keeper
    global master_ip

    _configure_logging()

    with open(SA_CONFIG_FILE, 'r') as config_file:
        standalone_config = json.load(config_file)

    with open(SA_MASTER_DATA_FILE, 'r') as data_file:
        master_data = json.load(data_file)
        master_ip = master_data['private_ip']

    budget_keeper = BudgetKeeper(
        standalone_config, master_data, stop_callback=clean
    )
    budget_keeper.start()

    redis_client = redis.Redis(decode_responses=True)

    Thread(target=job_monitor, daemon=True).start()

    server = WSGIServer(
        ('0.0.0.0', SA_MASTER_SERVICE_PORT), app, log=app.logger
    )
    server.serve_forever()


if __name__ == '__main__':
    main()
