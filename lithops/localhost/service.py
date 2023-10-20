import os
import json
import sys
import logging
import platform
import threading
import multiprocessing as mp
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

logging.basicConfig(stream=log_file_stream, level=logging.INFO, format=LOGGER_FORMAT)
logger = logging.getLogger('lithops.localhost.service')

# Change spawn method for MacOS
if platform.system() == 'Darwin':
    mp.set_start_method("fork")

# Initialize a global variable to hold the server
server = None

# Initialize a global variable to hold the queue
manager = SyncManager()
manager.start()
work_queue = manager.Queue()

# Initialize a global variable to hold the worker processes
job_runners = []

# Set Localhost backend to the env
os.environ['__LITHOPS_BACKEND'] = 'Localhost'


def add_job(job_payload):
    job = create_job(json.loads(job_payload))

    logger.debug(f'ExecutorID {job.executor_id} | JobID {job.job_id} - Adding '
                 f'{job.total_calls} activations in the localhost worker')

    try:
        for call_id in job.call_ids:
            data = job.data.pop(0)
            work_queue.put((job, call_id, data))
        return True
    except Exception as e:
        logger.debug(e)
        return False


def extract_runtime_meta():
    try:
        runtime_meta = get_runtime_metadata()
        return json.dumps(runtime_meta)
    except Exception as e:
        logger.debug(e)
        return False


def stop_service():
    global server
    if server:
        logger.info('Shutting down the service')
        server.shutdown()
        server.server_close()
        logger.info('Lithops localhost service has been stopped')
        log_file_stream.close()
        for process_runner in range(len(job_runners)):
            try:
                work_queue.put(ShutdownSentinel())
            except Exception:
                pass
        manager.shutdown()


def check_inactivity():
    for runner in job_runners:
        runner.join()
    stop_service()


if __name__ == "__main__":
    logger.info('Starting Lithops localhost service')

    worker_processes = int(sys.argv[1]) if len(sys.argv) > 1 else mp.cpu_count()
    service_port = int(sys.argv[2]) if len(sys.argv) > 2 else utils.find_free_port()

    server = SimpleXMLRPCServer(('0.0.0.0', service_port), logRequests=True)
    server.register_function(add_job, 'add_job')
    server.register_function(extract_runtime_meta, 'extract_runtime_meta')
    server.register_function(stop_service, 'stop_service')
    logger.info(f'Lithops localhost service is running on port {service_port}')

    # Start worker processes
    for pid in range(int(worker_processes)):
        p = mp.Process(target=python_queue_consumer, args=(pid, work_queue, 30))
        job_runners.append(p)
        p.start()

    # Start a thread to check for inactivity
    inactivity_thread = threading.Thread(target=check_inactivity)
    inactivity_thread.daemon = True
    inactivity_thread.start()

    server.serve_forever()
