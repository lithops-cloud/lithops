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
import json
import time
import redis
import flask
import logging
import signal
import subprocess as sp
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from functools import partial
from gevent.pywsgi import WSGIServer
from concurrent.futures import ThreadPoolExecutor

from lithops.utils import setup_lithops_logger, log_prefix
from lithops.standalone.keeper import BudgetKeeper
from lithops.standalone.utils import JobStatus, StandaloneMode, WorkerStatus
from lithops.constants import (
    CPU_COUNT,
    LITHOPS_TEMP_DIR,
    RN_LOG_FILE,
    SA_INSTALL_DIR,
    SA_WORKER_LOG_FILE,
    JOBS_DIR,
    LOGS_DIR,
    SA_CONFIG_FILE,
    SA_WORKER_DATA_FILE,
    SA_WORKER_SERVICE_PORT,
)

logger = logging.getLogger('lithops.standalone.worker')

app = flask.Flask(__name__)

_LOG_FORMAT = (
    "%(asctime)s\t[%(levelname)s] %(name)s:%(lineno)s -- %(message)s"
)
# Reuse/consume workers sit on BRPOP while they wait for the next job. A
# timeout of 0 holds that connection forever, and a connection that goes
# stale (idle NAT, Redis keepalive) never sees the LPUSH of the next job:
# /ping still reports the process as free, the job sits in the queue, and
# the budget keeper eventually dismantles the worker as idle.
_QUEUE_POLL_TIMEOUT = 5

redis_client = None
budget_keeper = None

job_processes = {}
worker_threads = {}
canceled = []


def _configure_logging():
    """Creates the directories the worker writes to and opens its log"""
    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
    os.makedirs(JOBS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    setup_lithops_logger(
        logging.DEBUG, filename=SA_WORKER_LOG_FILE, log_format=_LOG_FORMAT
    )


def _kill_process_group(process):
    """
    Kills a task process along with everything it forked, which is why the
    whole process group goes down and not just the process itself
    """
    if not process or process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:
        pass


@app.route('/ping', methods=['GET'])
def ping():
    """Reports how many of the worker processes are busy and how many free"""
    idle_count = sum(
        1 for worker in worker_threads.values()
        if worker['status'] == WorkerStatus.IDLE.value
    )
    busy_count = sum(
        1 for worker in worker_threads.values()
        if worker['status'] == WorkerStatus.BUSY.value
    )
    response = flask.jsonify({'busy': busy_count, 'free': idle_count})
    response.status_code = 200
    return response


@app.route('/ttd', methods=['GET'])
def ttd():
    """Reports the seconds left before this worker stops itself"""
    if budget_keeper:
        ttd_value = budget_keeper.get_time_to_dismantle()
    else:
        ttd_value = "Disabled"
    return str(ttd_value), 200


@app.route('/stop/<job_key>', methods=['POST'])
def stop(job_key):
    """Kills the task processes of a job and marks its tasks as done"""
    logger.debug(f'Received SIGTERM: Stopping job process {job_key}')
    canceled.append(job_key)

    # A snapshot, because the consumer threads add and remove entries while
    # this runs
    for job_key_call_id, process in list(job_processes.items()):
        if not job_key_call_id.startswith(job_key):
            continue
        logger.debug(f"Killing Job {job_key} - PID {getattr(process, 'pid', None)}")
        _kill_process_group(process)
        Path(os.path.join(JOBS_DIR, job_key_call_id + '.done')).touch()
        job_processes.pop(job_key_call_id, None)

    response = flask.jsonify({'response': 'cancel'})
    response.status_code = 200
    return response


@contextmanager
def _reported(what):
    """
    Runs a piece of Redis bookkeeping, reporting a failure instead of raising
    it: a worker that cannot tell the master what it is doing still has to run
    the tasks it was given
    """
    try:
        yield
    except Exception as e:
        logger.error(f'Could not {what}: {e}')


def notify_worker_active(worker_name):
    """Tells the master this worker is up"""
    with _reported(f'mark worker {worker_name} as active'):
        redis_client.hset(
            f"worker:{worker_name}", 'status', WorkerStatus.ACTIVE.value
        )


def notify_worker_idle(worker_name):
    """Tells the master this worker is free to take another job"""
    with _reported(f'mark worker {worker_name} as idle'):
        redis_client.hset(f"worker:{worker_name}", mapping={
            'status': WorkerStatus.IDLE.value,
            'runtime': '',
            'worker_processes': '',
        })


def notify_worker_stop(worker_name):
    """Tells the master this worker is stopping"""
    with _reported(f'mark worker {worker_name} as stopped'):
        redis_client.hset(
            f"worker:{worker_name}", 'status', WorkerStatus.STOPPED.value
        )


def notify_worker_delete(worker_name):
    """Tells the master this worker is going away for good"""
    with _reported(f'delete worker {worker_name}'):
        redis_client.delete(f"worker:{worker_name}")


def notify_task_start(job_key, call_id):
    """Marks the job as running, the first time one of its tasks starts"""
    with _reported(f'mark job {job_key} as running'):
        if redis_client.hget(f"job:{job_key}", 'status') == JobStatus.SUBMITTED.value:
            redis_client.hset(
                f"job:{job_key}", 'status', JobStatus.RUNNING.value
            )


def notify_task_done(job_key, call_id):
    """
    Counts a finished task, and marks the job as done once every one of its
    tasks has been counted
    """
    with _reported(f'mark task {call_id} of job {job_key} as done'):
        done_tasks = int(redis_client.rpush(f"tasksdone:{job_key}", call_id))
        if int(redis_client.hget(f"job:{job_key}", 'total_tasks')) == done_tasks:
            redis_client.hset(f"job:{job_key}", 'status', JobStatus.DONE.value)


def _wait_for_task(work_queue_name, exec_mode):
    """
    Returns the next task payload from the work queue, or None when there is
    nothing to run right now. Create mode treats that as the end of the job.
    The other modes poll with a timeout so that a stale BRPOP is dropped and
    opened again, instead of waiting forever on a connection that will never
    see the next job
    """
    if exec_mode == StandaloneMode.CREATE.value:
        return redis_client.rpop(work_queue_name)

    item = redis_client.brpop(work_queue_name, timeout=_QUEUE_POLL_TIMEOUT)
    if item is None:
        return None
    _key, task_payload_str = item
    return task_payload_str


def redis_queue_consumer(pid, work_queue_name, exec_mode, backend):
    """
    Takes tasks from the work queue and runs them one after another, until the
    queue runs dry in create mode, or forever in the modes where the worker
    waits for the jobs still to come
    """
    worker_threads[pid]['status'] = WorkerStatus.IDLE.value
    logger.info(f"Redis consumer process {pid} started")

    while True:
        try:
            task_payload_str = _wait_for_task(work_queue_name, exec_mode)
        except Exception as e:
            logger.error(
                f'Redis consumer {pid} could not read the queue: {e}'
            )
            time.sleep(1)
            continue

        if task_payload_str is None:
            if exec_mode == StandaloneMode.CREATE.value:
                break
            continue

        worker_threads[pid]['status'] = WorkerStatus.BUSY.value
        try:
            task_payload = json.loads(task_payload_str)
            executor_id = task_payload['executor_id']
            job_id = task_payload['job_id']
            job_key = task_payload['job_key']
            call_id = task_payload['call_ids'][0]
            job_key_call_id = f'{job_key}-{call_id}'

            logger.debug(
                f'{log_prefix(executor_id, job_id)} - Running '
                f'CallID {call_id} in the local worker (consumer {pid})'
            )
            notify_task_start(job_key, call_id)

            if budget_keeper:
                budget_keeper.add_job(job_key_call_id)

            task_filename = os.path.join(JOBS_DIR, f'{job_key_call_id}.task')
            with open(task_filename, 'w') as task_file:
                json.dump(task_payload, task_file, default=str)

            cmd = [
                "python3",
                f"{SA_INSTALL_DIR}/runner.py",
                backend,
                task_filename,
            ]
            with open(RN_LOG_FILE, 'a') as log:
                process = sp.Popen(
                    cmd, stdout=log, stderr=log, start_new_session=True
                )
                job_processes[job_key_call_id] = process
                process.communicate()
            # Popped, not deleted: the stop route may have taken it already
            job_processes.pop(job_key_call_id, None)

            if os.path.exists(task_filename):
                os.remove(task_filename)

            Path(os.path.join(JOBS_DIR, f'{job_key_call_id}.done')).touch()

            msg = f'{log_prefix(executor_id, job_id)} - '
            if job_key in canceled:
                msg += f'CallID {call_id} execution canceled'
            else:
                notify_task_done(job_key, call_id)
                msg += f'CallID {call_id} execution finished'
            logger.debug(msg)
        except Exception as e:
            logger.error(e)

        worker_threads[pid]['status'] = WorkerStatus.IDLE.value

    logger.info(f"Redis consumer process {pid} finished")


def run_worker():
    """
    Entry point of the worker service: connects to the master, starts the
    countdown that stops the instance, serves the control endpoints, and runs
    one consumer per worker process until there is nothing left to run
    """
    global redis_client
    global budget_keeper

    _configure_logging()

    with open(SA_CONFIG_FILE, 'r') as config_file:
        standalone_config = json.load(config_file)

    with open(SA_WORKER_DATA_FILE, 'r') as data_file:
        worker_data = json.load(data_file)

    redis_client = redis.Redis(
        host=worker_data['master_ip'],
        decode_responses=True,
        socket_keepalive=True,
    )
    notify_worker_active(worker_data['name'])

    if worker_data['master_ip'] != worker_data['private_ip']:
        stop_callback = partial(notify_worker_stop, worker_data['name'])
        delete_callback = partial(notify_worker_delete, worker_data['name'])
        budget_keeper = BudgetKeeper(
            standalone_config, worker_data, stop_callback, delete_callback
        )
        budget_keeper.start()

    def run_wsgi():
        """Serves the control endpoints of this worker"""
        ip_address = (
            "0.0.0.0" if os.getenv("DOCKER") == "Lithops"
            else worker_data['private_ip']
        )
        server = WSGIServer(
            (ip_address, SA_WORKER_SERVICE_PORT), app, log=app.logger
        )
        server.serve_forever()

    Thread(target=run_wsgi, daemon=True).start()

    worker_processes = standalone_config[
        standalone_config['backend']
    ]['worker_processes']
    worker_processes = (
        CPU_COUNT if worker_processes == 'AUTO' else worker_processes
    )
    logger.info(
        f"Starting Worker - Instance type: {worker_data['instance_type']} - "
        f"Runtime name: {standalone_config['runtime']} - "
        f"Worker processes: {worker_processes}"
    )

    redis_queue_consumer_futures = []
    with ThreadPoolExecutor(max_workers=worker_processes) as executor:
        for i in range(worker_processes):
            worker_threads[i] = {}
            future = executor.submit(
                redis_queue_consumer,
                i,
                worker_data['work_queue_name'],
                standalone_config['exec_mode'],
                standalone_config['backend'],
            )
            redis_queue_consumer_futures.append(future)
            worker_threads[i]['future'] = future

        for future in redis_queue_consumer_futures:
            future.result()

    if standalone_config['exec_mode'] == StandaloneMode.CONSUME.value:
        notify_worker_idle(worker_data['name'])

    logger.debug('Worker service finished')

    if budget_keeper:
        try:
            budget_keeper.stop_instance()
        except Exception as e:
            logger.error(f'Could not stop the instance: {e}')


if __name__ == '__main__':
    run_worker()
