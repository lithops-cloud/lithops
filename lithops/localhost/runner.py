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
import json
import flask
import platform
import logging
import uuid
import multiprocessing as mp
from multiprocessing.managers import SyncManager
from pathlib import Path

from lithops.worker import function_handler
from lithops.worker.utils import get_runtime_preinstalls
from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DIR, LOGS_DIR,\
    RN_LOG_FILE, LOGGER_FORMAT
from gevent.pywsgi import WSGIServer

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


app = flask.Flask(__name__)


RUNNER_PROCESS = None
JOB_QUEUE = None
SERVER = None
RECEIVED_JOBS = {}


def error(msg):
    response = flask.jsonify({'error': msg})
    response.status_code = 404
    return response


@app.route('/submit', methods=['POST'])
def submit_job():
    """
    Submits a job
    """
    job_payload = flask.request.get_json(force=True, silent=True)
    if job_payload and not isinstance(job_payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    JOB_QUEUE.put(job_payload)

    return ('', 202)


@app.route('/preinstalls', methods=['GET'])
def preinstalls():
    """
    Generates runtime preinstalled modules dictionary
    """
    runtime_meta = get_runtime_preinstalls()

    return json.dumps(runtime_meta)


@app.route('/ping', methods=['GET'])
def ping():
    """
    Pings the current service to chek if it is alive
    """
    response = flask.jsonify({'response': 'pong'})
    response.status_code = 200
    return response


@app.route('/clear', methods=['POST'])
def clear():
    """
    Stops received jobs
    """
    global RECEIVED_JOBS

    return ('', 204)


@app.route('/shutdown', methods=['POST'])
def shutdown():
    """
    Shutdowns the current proxy server
    """
    global RUNER_PROCESS
    global SERVER

    RUNER_PROCESS.kill()

    SERVER.stop()
    SERVER.close()

    return ('', 204)


def run():
    sys.stdout = log_file_stream
    sys.stderr = log_file_stream

    while True:
        job_payload = JOB_QUEUE.get()

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
    global RUNER_PROCESS
    global JOB_QUEUE
    global SERVER

    manager = SyncManager()
    manager.start()
    JOB_QUEUE = manager.Queue()

    RUNER_PROCESS = mp.Process(target=run)
    RUNER_PROCESS.start()

    port = int(sys.argv[1])
    SERVER = WSGIServer(('127.0.0.1', port), app, log=app.logger)
    SERVER.serve_forever()


if __name__ == '__main__':
    main()
