#
# Copyright Cloudlab URV 2020
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
import uuid
import flask
import sys
import logging
import time
import json
from gevent.pywsgi import WSGIServer

from lithops.constants import LITHOPS_TEMP_DIR, SA_LOG_FILE,\
    STANDALONE_SERVICE_PORT, STANDALONE_CONFIG_FILE
from lithops.localhost.localhost import LocalhostHandler
from lithops.utils import verify_runtime_name, setup_lithops_logger
from lithops.standalone.keeper import BudgetKeeper

setup_lithops_logger(logging.DEBUG, filename=SA_LOG_FILE)
logger = logging.getLogger('lithops.standalone.worker')

proxy = flask.Flask('lithops.standalone.worker')

STANDALONE_CONFIG = None
BUDGET_KEEPER = None


def error(msg):
    response = flask.jsonify({'error': msg})
    response.status_code = 404
    return response


@proxy.route('/run', methods=['POST'])
def run():
    """
    Run a job
    """
    global BUDGET_KEEPER

    job_payload = flask.request.get_json(force=True, silent=True)
    if job_payload and not isinstance(job_payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime = job_payload['runtime_name']
        verify_runtime_name(runtime)
    except Exception as e:
        return error(str(e))

    BUDGET_KEEPER.last_usage_time = time.time()
    BUDGET_KEEPER.update_config(job_payload['config']['standalone'])
    BUDGET_KEEPER.jobs[job_payload['job_key']] = 'running'

    pull_runtime = STANDALONE_CONFIG.get('pull_runtime', False)
    localhost_handler = LocalhostHandler({'runtime': runtime, 'pull_runtime': pull_runtime})
    localhost_handler.run_job(job_payload)

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    response = flask.jsonify({'activationId': act_id})
    response.status_code = 202

    return response


@proxy.route('/ping', methods=['GET'])
def ping():
    response = flask.jsonify({'response': 'pong'})
    response.status_code = 200

    return response


@proxy.route('/preinstalls', methods=['GET'])
def preinstalls():

    message = flask.request.get_json(force=True, silent=True)
    if message and not isinstance(message, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime = message['runtime']
        verify_runtime_name(runtime)
    except Exception as e:
        return error(str(e))

    pull_runtime = STANDALONE_CONFIG.get('pull_runtime', False)
    localhost_handler = LocalhostHandler({'runtime': runtime, 'pull_runtime': pull_runtime})
    runtime_meta = localhost_handler.create_runtime(runtime)
    response = flask.jsonify(runtime_meta)
    response.status_code = 200

    return response


def main():
    global STANDALONE_CONFIG
    global BUDGET_KEEPER

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    with open(STANDALONE_CONFIG_FILE, 'r') as cf:
        STANDALONE_CONFIG = json.load(cf)

    with open(SA_LOG_FILE, 'a') as log_file:
        sys.stdout = log_file
        sys.stderr = log_file
        BUDGET_KEEPER = BudgetKeeper(STANDALONE_CONFIG)
        BUDGET_KEEPER.start()
        server = WSGIServer(('0.0.0.0', STANDALONE_SERVICE_PORT),
                            proxy, log=proxy.logger)
        server.serve_forever()


if __name__ == '__main__':
    main()
