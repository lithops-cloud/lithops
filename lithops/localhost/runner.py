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
import multiprocessing as mp
from multiprocessing.connection import Listener

from lithops.worker import function_handler
from lithops.worker.utils import get_runtime_preinstalls
from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DIR, LOGS_DIR,\
    RN_LOG_FILE, LOGGER_FORMAT


log_file_stream = open(RN_LOG_FILE, 'a')

os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(JOBS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(stream=log_file_stream,
                    level=logging.INFO,
                    format=LOGGER_FORMAT)
logger = logging.getLogger('lithops.localhost.runner')


# Change spawn method for MacOS
if platform.system() == 'Darwin':
    mp.set_start_method("fork")


def run(job_queue):
    sys.stdout = log_file_stream
    sys.stderr = log_file_stream

    while True:
        job_payload = job_queue.get()

        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        job_key = job_payload['job_key']

        logger.info('ExecutorID {} | JobID {} - Starting execution'
                    .format(executor_id, job_id))

        act_id = str(uuid.uuid4()).replace('-', '')[:12]
        os.environ['__LITHOPS_ACTIVATION_ID'] = act_id
        os.environ['__LITHOPS_BACKEND'] = 'Localhost'

        try:
            function_handler(job_payload)
        except KeyboardInterrupt:
            pass

        done = os.path.join(JOBS_DIR, job_key+'.done')
        Path(done).touch()

        logger.info('ExecutorID {} | JobID {} - Execution Finished'
                    .format(executor_id, job_id))


def main():
    job_queue = mp.Queue()

    runner_process = mp.Process(target=run, args=(job_queue, ))
    runner_process.start()

    listener = Listener(('localhost', int(sys.argv[1])))
    running = True
    while running:
        conn = listener.accept()
        logger.debug('connection accepted from', listener.last_accepted)
        while True:
            msg = conn.recv()
            logger.debug(f'Received command: {msg}')
            if msg == 'run':
                logger.debug('Received new job payload')
                job_payload = conn.recv()
                job_queue.put(job_payload)
            if msg == 'preinstalls':
                logger.debug('Extracting python preinstalled modules')
                runtime_meta = get_runtime_preinstalls()
                conn.send(runtime_meta)
            if msg == 'ping':
                logger.debug('Pinging service')
                conn.send('pong')
            if msg == 'close':
                logger.debug('Closing client connection')
                conn.close()
                break
            if msg == 'shutdown':
                logger.debug('Shutting down service')
                conn.close()
                running = False
                break

    listener.close()
    runner_process.kill()


if __name__ == '__main__':
    main()
