#
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
import time
import json
import sys
import logging
import platform
import threading
import multiprocessing as mp
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from multiprocessing.managers import SyncManager
from xmlrpc.server import SimpleXMLRPCServer

from lithops import utils
from lithops.worker.handler import ShutdownSentinel, create_job, python_queue_consumer
from lithops.worker.utils import get_runtime_metadata
from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DIR, LOGS_DIR, SV_LOG_FILE, LOGGER_FORMAT

log_file_stream = open(SV_LOG_FILE, 'a')

os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(JOBS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(stream=log_file_stream, level=logging.DEBUG, format=LOGGER_FORMAT)
logger = logging.getLogger('lithops.localhost.service')

# Change spawn method for MacOS
if platform.system() == 'Darwin':
    mp.set_start_method("fork")

job_runners = []
manager = None
server = None
worker_status_dict = None
job_status_dict = None
work_queue = None
job_status_lock = None

MAX_IDLE_TIMEOUT = 2

# Set Localhost backend to the env
os.environ['__LITHOPS_BACKEND'] = 'Localhost'


class ProcessStatus(Enum):
    IDLE = 'idle'
    BUSY = 'busy'


def add_job(job_payload):
    job = create_job(json.loads(job_payload))
    logger.info(f'ExecutorID {job.executor_id} | JobID {job.job_id} - Adding '
                f'{job.total_calls} tasks in the localhost worker')
    try:
        job_status_dict[job.job_key] = 0
        for call_id in job.call_ids:
            data = job.data.pop(0)
            work_queue.put((job, call_id, data))
        return True
    except Exception as e:
        logger.debug(e)
        return False


def extract_runtime_meta():
    logger.info('Requesting runtime metadata')
    try:
        runtime_meta = get_runtime_metadata()
        return json.dumps(runtime_meta)
    except Exception as e:
        logger.debug(e)
        return False


def stop_service():
    global server
    if server:
        logger.info('Shutting down the executor service')
        for process_runner in range(len(job_runners)):
            try:
                work_queue.put(ShutdownSentinel())
            except Exception:
                pass
        for runner in job_runners:
            runner.join()
        server.shutdown()
        server.server_close()


def check_inactivity():
    tasks_running = False
    last_usage_time = time.time()

    while True:
        if all(value == ProcessStatus.IDLE.value for value in worker_status_dict.values()):
            if tasks_running:
                tasks_running = False
                last_usage_time = time.time()
        else:
            tasks_running = True
            last_usage_time = time.time()

        time_since_last_usage = time.time() - last_usage_time

        if int(MAX_IDLE_TIMEOUT - time_since_last_usage) <= 0:
            stop_service()
            break

        log_file_stream.flush()
        time.sleep(5)


def task_initializer(pid, task):
    worker_status_dict[pid] = ProcessStatus.BUSY.value


def task_callback(pid: int, task: SimpleNamespace):
    worker_status_dict[pid] = ProcessStatus.IDLE.value

    with job_status_lock:
        job_status_dict[task.job_key] += 1

    if job_status_dict[task.job_key] == task.total_calls:
        logger.info(f'ExecutorID {task.executor_id} | JobID {task.job_id} - Execution Finished')
        job_status_dict[task.job_key] = 'done'


if __name__ == "__main__":
    logger.info('*'*60)
    logger.info('Starting Lithops localhost executor service')

    worker_processes = int(sys.argv[1]) if len(sys.argv) > 1 else mp.cpu_count()
    service_port = int(sys.argv[2]) if len(sys.argv) > 2 else utils.find_free_port()

    manager = SyncManager()
    manager.start()
    worker_status_dict = manager.dict()
    job_status_dict = manager.dict()
    work_queue = manager.Queue()
    job_status_lock = manager.Lock()

    server = SimpleXMLRPCServer(('0.0.0.0', service_port), logRequests=False)
    server.register_function(add_job, 'add_job')
    server.register_function(extract_runtime_meta, 'extract_runtime_meta')
    logger.info(f'Lithops localhost executor service is running on port {service_port}')

    # Start worker processes
    for pid in range(int(worker_processes)):
        worker_status_dict[pid] = ProcessStatus.IDLE.value
        p = mp.Process(target=python_queue_consumer, args=(pid, work_queue, task_initializer, task_callback))
        job_runners.append(p)
        p.start()

    # Start a thread to check for inactivity
    inactivity_thread = threading.Thread(target=check_inactivity)
    inactivity_thread.daemon = True
    inactivity_thread.start()

    server.serve_forever()

    manager.shutdown()
    log_file_stream.flush()
    logger.info('Lithops localhost executor service has been stopped')
    log_file_stream.close()
