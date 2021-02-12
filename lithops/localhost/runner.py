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
import pkgutil
import logging
import uuid
from pathlib import Path

from lithops.utils import version_str
from lithops.worker import function_handler
from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DIR, LOGS_DIR,\
    RN_LOG_FILE, LOGGER_FORMAT

os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(JOBS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(filename=RN_LOG_FILE, level=logging.INFO,
                    format=LOGGER_FORMAT)
logger = logging.getLogger('lithops.localhost.runner')


def run():
    log_file_stream = open(RN_LOG_FILE, 'a')
    sys.stdout = log_file_stream
    sys.stderr = log_file_stream

    job_filename = sys.argv[2]
    logger.info('Got {} job file'.format(job_filename))

    with open(job_filename, 'rb') as jf:
        job_payload = json.load(jf)

    executor_id = job_payload['executor_id']
    job_id = job_payload['job_id']
    job_key = job_payload['job_key']

    logger.info('ExecutorID {} | JobID {} - Starting execution'
                .format(executor_id, job_id))

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    os.environ['__LITHOPS_ACTIVATION_ID'] = act_id
    function_handler(job_payload)

    done = os.path.join(JOBS_DIR, job_key+'.done')
    Path(done).touch()

    if os.path.exists(job_filename):
        os.remove(job_filename)

    logger.info('ExecutorID {} | JobID {} - Execution Finished'
                .format(executor_id, job_id))
    log_file_stream.close()


def extract_runtime_meta():
    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta["preinstalls"] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
    runtime_meta["python_ver"] = version_str(sys.version_info)

    print(json.dumps(runtime_meta))


if __name__ == "__main__":
    logger.info('Starting Localhost job runner')
    command = sys.argv[1]
    logger.info('Received command: {}'.format(command))

    switcher = {
        'preinstalls': extract_runtime_meta,
        'run': run
    }

    func = switcher.get(command, lambda: "Invalid command")
    func()
