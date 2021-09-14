#
# (C) Copyright Cloudlab URV 2021
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
import sys
import platform
import logging
import uuid
from pathlib import Path
from threading import Thread
import multiprocessing as mp
from multiprocessing.connection import Listener

from lithops.worker import function_handler
from lithops.worker.utils import get_runtime_preinstalls
from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DIR, LOGS_DIR,\
    LOGGER_FORMAT, RN_LOG_FILE

os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(JOBS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

log_file_stream = open(RN_LOG_FILE, 'a')
logging.basicConfig(stream=log_file_stream,
                    level=logging.INFO,
                    format=LOGGER_FORMAT)
logger = logging.getLogger('lithops.localhost.runner')


# Change spawn method for MacOS
if platform.system() == 'Darwin':
    mp.set_start_method("fork")


class ShutdownSentinel:
    """Put an instance of this class on the queue to shut it down"""
    pass


SHOULD_RUN = True


def service(job_queue):
    global SHOULD_RUN

    port = sys.argv[1]
    ip_address = '0.0.0.0' if 'IS_DOCKER_CONTAINER' in os.environ else '127.0.0.1'
    logger.info(f'Starting runner service on {ip_address}:{port}')

    listener = Listener((ip_address, int(port)))

    while SHOULD_RUN:
        conn = listener.accept()
        logger.info(f'connection accepted from {listener.last_accepted}')
        while True:
            command = conn.recv()
            logger.info(f'Received command: {command}')

            if command == 'run':
                logger.info('Receiving new job payload')
                job_payload = conn.recv()
                job_queue.put(job_payload)

            elif command == 'preinstalls':
                logger.info('Extracting python preinstalled modules')
                runtime_meta = get_runtime_preinstalls()
                conn.send(runtime_meta)

            elif command == 'ping':
                logger.info('Signaling service')
                conn.send('pong')

            elif command == 'close':
                logger.info('Closing client connection')
                conn.close()
                break

            elif command == 'shutdown':
                logger.info('Stopping runner service')
                conn.close()
                SHOULD_RUN = False
                job_queue.put(ShutdownSentinel())
                break

    listener.close()
    logger.info('Runner service stopped')


def run(job_queue):
    """
    Wrapper function that reads jobs from the queue and executes them
    """
    while SHOULD_RUN:
        event = job_queue.get()

        if isinstance(event, ShutdownSentinel):
            break

        executor_id = event['executor_id']
        job_id = event['job_id']
        job_key = event['job_key']

        logger.info('ExecutorID {} | JobID {} - Starting execution'
                    .format(executor_id, job_id))

        act_id = str(uuid.uuid4()).replace('-', '')[:12]
        os.environ['__LITHOPS_ACTIVATION_ID'] = act_id
        os.environ['__LITHOPS_BACKEND'] = 'Localhost'

        function_handler(event)

        done = os.path.join(JOBS_DIR, job_key+'.done')
        Path(done).touch()

        logger.info('ExecutorID {} | JobID {} - Execution Finished'
                    .format(executor_id, job_id))


def main():
    """
    The runner service is a super-lightweight, low-level, service that acts as
    an interface/wrapper (or entry_point) to the actual lithops execution.
    """
    logger.info('Starting main service')
    job_queue = mp.Queue()
    service_process = Thread(target=service, args=(job_queue, ), daemon=True)
    service_process.start()
    run(job_queue)
    logger.info('Exiting main service')


if __name__ == '__main__':
    main()
