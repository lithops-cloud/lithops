#
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
import sys
import json
import logging
import uuid

from lithops.worker import function_handler
from lithops.utils import log_prefix
from lithops.constants import RN_LOG_FILE, LITHOPS_TEMP_DIR, LOGGER_FORMAT

logger = logging.getLogger('lithops.standalone.runner')


def _configure_runner_logging():
    """
    Sends everything this process logs to the runner log, which is the only
    place a task failure can be read from in a standalone worker
    """
    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
    log_file_stream = open(RN_LOG_FILE, 'a')
    logging.basicConfig(
        stream=log_file_stream,
        level=logging.INFO,
        format=LOGGER_FORMAT,
    )
    return log_file_stream


def run_job(backend: str, task_filename: str) -> None:
    """
    Runs the single task described by a task file. The worker service starts
    one of these per task, so the handler always runs one activation
    """
    logger.info(f'Got {task_filename} job file')

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
    os.environ['__LITHOPS_BACKEND'] = backend.replace("_", " ").upper()

    task_payload['worker_processes'] = 1
    function_handler(task_payload)

    logger.info(
        f'{log_prefix(executor_id, job_id, call_id)} - Execution Finished'
    )


def main() -> None:
    """Entry point of the task runner, called by the worker service"""
    log_file_stream = _configure_runner_logging()
    try:
        sys.stdout = log_file_stream
        sys.stderr = log_file_stream
        logger.info('Starting Standalone task runner')
        backend = sys.argv[1]
        task_filename = sys.argv[2]
        run_job(backend, task_filename)
    finally:
        log_file_stream.close()


if __name__ == "__main__":
    main()
