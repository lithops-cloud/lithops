#
# (C) Copyright Cloudlab URV 2020
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
import json
import platform
import logging
import uuid
import traceback
import multiprocessing as mp

from lithops.worker import function_handler
from lithops.worker.utils import get_runtime_metadata
from lithops.utils import log_prefix
from lithops.constants import (
    LITHOPS_TEMP_DIR,
    JOBS_DIR,
    LOGS_DIR,
    LOGGER_FORMAT,
    RN_LOG_FILE,
)

logger = logging.getLogger('lithops.localhost.runner')


def _configure_runner_logging():
    """
    Sends the runner logs to the runner log file, and returns the stream so
    that the caller can also redirect the task output to it
    """
    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
    os.makedirs(JOBS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file_stream = open(RN_LOG_FILE, 'a')
    logging.basicConfig(
        stream=log_file_stream,
        level=logging.DEBUG,
        format=LOGGER_FORMAT,
    )
    return log_file_stream


def _set_fork_start_method():
    """
    Forces fork, which Lithops relies on for its workers to inherit the task.
    Python 3.14 defaults to forkserver on Linux
    """
    if platform.system() == 'Windows':
        return
    try:
        mp.set_start_method('fork')
    except RuntimeError:
        # Already set by an earlier call in this interpreter
        pass


def run_job(log_file_stream):
    """
    Runs the single task described by the task file given as the second
    argument
    """
    # This process has no console: anything printed goes to the runner log
    sys.stdout = log_file_stream
    sys.stderr = log_file_stream

    task_filename = sys.argv[2]
    logger.info(f'Got {task_filename} file')

    with open(task_filename, 'r') as task_file:
        task_payload = json.load(task_file)

    executor_id = task_payload['executor_id']
    job_id = task_payload['job_id']
    call_id = task_payload['call_ids'][0]

    logger.info(
        f'{log_prefix(executor_id, job_id, call_id)} - Starting execution'
    )

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    os.environ['__LITHOPS_ACTIVATION_ID'] = act_id
    os.environ['__LITHOPS_BACKEND'] = 'Localhost'

    try:
        # The environment already starts one runner per task, so the handler
        # must not fork any further worker process
        task_payload['worker_processes'] = 1
        function_handler(task_payload)
    except KeyboardInterrupt:
        pass

    logger.info(
        f'{log_prefix(executor_id, job_id, call_id)} - Execution Finished'
    )


def extract_runtime_meta():
    """Prints the metadata of this runtime, which the client reads back"""
    print(json.dumps(get_runtime_metadata()))


def main():
    """Entry point of the runner subprocess, dispatching the argv command"""
    _set_fork_start_method()
    log_file_stream = _configure_runner_logging()
    try:
        logger.info('Starting Localhost task runner')
        command = sys.argv[1]
        logger.info(f'Received command: {command}')

        handlers = {
            'get_metadata': extract_runtime_meta,
            'run_job': lambda: run_job(log_file_stream),
        }
        handler = handlers.get(command)
        if handler is None:
            logger.error(f'Invalid command: {command}')
            sys.exit(1)
        handler()
    except Exception:
        logger.exception('Localhost task runner failed')
        traceback.print_exc(file=sys.__stderr__)
        sys.exit(1)
    finally:
        log_file_stream.close()


if __name__ == "__main__":
    main()
