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
from queue import Empty
from multiprocessing.managers import SyncManager
from xmlrpc.server import SimpleXMLRPCServer

from lithops import utils
from lithops.worker.utils import get_runtime_metadata
from lithops.worker.handler import (
    ShutdownSentinel,
    create_job,
    prepare_and_run_task
)
from lithops.constants import (
    CPU_COUNT,
    LITHOPS_TEMP_DIR,
    JOBS_DIR,
    LOCALHOST_SERVICE_CHECK_INTERVAL,
    LOCALHOST_SERVICE_IDLE_TIMEOUT,
    LOGS_DIR,
    SV_LOG_FILE,
    LOGGER_FORMAT
)

log_file_stream = open(SV_LOG_FILE, 'a')

os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(JOBS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(stream=log_file_stream, level=logging.DEBUG, format=LOGGER_FORMAT)
logger = logging.getLogger('lithops.localhost.service')

# Change spawn method for MacOS
if platform.system() == 'Darwin':
    mp.set_start_method("fork")

task_runners = []

# Set Localhost backend to the env
os.environ['__LITHOPS_BACKEND'] = 'Localhost'


class ProcessStatus(Enum):
    IDLE = 'idle'
    BUSY = 'busy'


class ServerThread(threading.Thread):

    def __init__(self, service_port, work_queue):
        super().__init__()

        self.server = SimpleXMLRPCServer(('0.0.0.0', service_port), logRequests=False)

        self.service_port = service_port
        self.work_queue = work_queue

        self.server.register_function(self.add_job, 'add_job')
        self.server.register_function(self.extract_runtime_meta, 'extract_runtime_meta')

    def add_job(self, job_payload):
        logger.info("Received new job")
        job = create_job(json.loads(job_payload))
        logger.info(f'ExecutorID {job.executor_id} | JobID {job.job_id} - Adding '
                    f'{job.total_calls} tasks in the localhost worker')
        try:
            job_status_dict[job.job_key] = 0
            for call_id in job.call_ids:
                data = job.data.pop(0)
                self.work_queue.put((job, call_id, data))
            return True
        except Exception as e:
            logger.debug(e)
            return False

    def extract_runtime_meta(self):
        logger.info('Requesting runtime metadata')
        try:
            runtime_meta = get_runtime_metadata()
            return json.dumps(runtime_meta)
        except Exception as e:
            logger.debug(e)
            return False

    def start(self):
        logger.info(f'Lithops localhost executor service started on port {self.service_port}')
        self.server.serve_forever()

    def stop(self):
        logger.info('Shutting down the executor service')
        for process_runner in range(len(task_runners)):
            try:
                self.work_queue.put(ShutdownSentinel())
            except Exception:
                pass
        for runner in task_runners:
            runner.join()
        self.server.shutdown()
        self.server.server_close()


def check_inactivity(server_thread, max_idle_timeout, check_interval):
    """
    A thread that checks if the service is inactive every 'check_interval'
    until 'max_idle_timeout,' where it automatically stops itself.
    """
    tasks_running = False
    last_usage_time = time.time()

    while True:
        time.sleep(check_interval)

        if all(value == ProcessStatus.IDLE.value for value in worker_status_dict.values()):
            if tasks_running:
                tasks_running = False
                last_usage_time = time.time()
        else:
            tasks_running = True
            last_usage_time = time.time()

        time_since_last_usage = time.time() - last_usage_time

        if int(max_idle_timeout - time_since_last_usage) <= 0:
            server_thread.stop()
            break


def process_event(
        event, pid,
        worker_status_dict
):
    """
    Processes the events received from the work queue
    """
    task, call_id, data = event
    task.call_id = call_id
    task.data = data

    worker_status_dict[pid] = ProcessStatus.BUSY.value

    prepare_and_run_task(task)

    worker_status_dict[pid] = ProcessStatus.IDLE.value

    # task_id = f'{task.job_key}-{task.call_id}'
    # Path(os.path.join(JOBS_DIR, f'{task_id}' + '.done')).touch()


def python_queue_consumer(
        pid,
        work_queue,
        worker_status_dict
):
    """
    Listens to the job_queue and executes the individual job tasks
    """
    logger.info(f'Worker process {pid} started')
    while True:
        try:
            event = work_queue.get(block=True)
        except Empty:
            break
        except BrokenPipeError:
            break

        if isinstance(event, ShutdownSentinel):
            break

        process_event(event, pid, worker_status_dict)

    logger.info(f'Worker process {pid} finished')


if __name__ == "__main__":
    logger.info('*' * 60)

    worker_processes = int(sys.argv[1]) if len(sys.argv) > 1 else CPU_COUNT
    service_port = int(sys.argv[2]) if len(sys.argv) > 2 else utils.find_free_port()
    max_idle_timeout = int(sys.argv[3]) if len(sys.argv) > 3 else LOCALHOST_SERVICE_IDLE_TIMEOUT
    check_interval = int(sys.argv[4]) if len(sys.argv) > 4 else LOCALHOST_SERVICE_CHECK_INTERVAL

    logger.info(f'Starting Lithops localhost executor service - Worker processes: {worker_processes}')

    manager = SyncManager()
    manager.start()
    work_queue = manager.Queue()
    worker_status_dict = manager.dict()
    job_status_dict = manager.dict()
    job_status_lock = manager.Lock()

    server_thread = ServerThread(service_port, work_queue)

    # Start worker processes
    for pid in range(int(worker_processes)):
        worker_status_dict[pid] = ProcessStatus.IDLE.value
        p = mp.Process(
            target=python_queue_consumer,
            args=(
                pid,
                work_queue,
                worker_status_dict
            )
        )
        task_runners.append(p)
        p.start()

    if max_idle_timeout >= 0:
        logger.info('Starting inactivity checker thread: Idle timeout: '
                    f'{max_idle_timeout} - Check interval {check_interval}')
        threading.Thread(
            target=check_inactivity,
            args=(server_thread, max_idle_timeout, check_interval),
            daemon=True
        ).start()
    else:
        logger.info('Inactivity checker thread is disabled because '
                    f'of: Idle timeout: {max_idle_timeout}')

    server_thread.start()

    manager.shutdown()
    log_file_stream.flush()
    logger.info('Lithops localhost executor service has been stopped')
    log_file_stream.close()
