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
import threading
import json
from gevent.pywsgi import WSGIServer

from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DONE_DIR, \
    REMOTE_INSTALL_DIR, PX_LOG_FILE, LOGS_DIR, LOGGER_FORMAT, \
    PROXY_SERVICE_PORT
from lithops.storage.utils import create_job_key
from lithops.localhost.localhost import LocalhostHandler
from lithops.standalone.standalone import StandaloneHandler
from lithops.utils import verify_runtime_name


os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

log_file_fd = open(PX_LOG_FILE, 'a')
sys.stdout = log_file_fd
sys.stderr = log_file_fd

logging.basicConfig(filename=PX_LOG_FILE, level=logging.INFO,
                    format=LOGGER_FORMAT)
logger = logging.getLogger('proxy')

proxy = flask.Flask(__name__)

last_usage_time = time.time()
keeper = None
jobs = {}
backend_handler = None


config_file = os.path.join(REMOTE_INSTALL_DIR, 'config')
with open(config_file, 'r') as cf:
    standalone_config = json.load(cf)


def budget_keeper():
    global last_usage_time
    global jobs
    global backend_handler

    jobs_running = False

    logger.info("BudgetKeeper started")

    if backend_handler.auto_dismantle:
        logger.info('Auto dismantle activated - Soft timeout: {}s, Hard Timeout: {}s'
                    .format(backend_handler.soft_dismantle_timeout,
                            backend_handler.hard_dismantle_timeout))
    else:
        # If auto_dismantle is deactivated, the VM will be always automatically
        # stopped after hard_dismantle_timeout. This will prevent the VM
        # being started forever due a wrong configuration
        logger.info('Auto dismantle deactivated - Hard Timeout: {}s'
                    .format(backend_handler.hard_dismantle_timeout))
    logger.info("Jobs keys are {}".format(jobs.keys()))

    while True:
        time_since_last_usage = time.time() - last_usage_time
        check_interval = backend_handler.soft_dismantle_timeout / 10
        for job_key in jobs.keys():
            done = os.path.join(JOBS_DONE_DIR, job_key+'.done')
            if os.path.isfile(done):
                jobs[job_key] = 'done'
        if len(jobs) > 0 and all(value == 'done' for value in jobs.values()) \
           and backend_handler.auto_dismantle:

            # here we need to catch a moment when number of running jobs become zero.
            # when it happens we reset countdown back to soft_dismantle_timeout
            if jobs_running:
                jobs_running = False
                last_usage_time = time.time()
                time_since_last_usage = time.time() - last_usage_time

            time_to_dismantle = int(backend_handler.soft_dismantle_timeout - time_since_last_usage)
        else:
            time_to_dismantle = int(backend_handler.hard_dismantle_timeout - time_since_last_usage)
            jobs_running = True

        if time_to_dismantle > 0:
            logger.info("Time to dismantle: {} seconds".format(time_to_dismantle))
            time.sleep(check_interval)
        else:
            logger.info("Dismantling setup")
            try:
                backend_handler.dismantle()
            except Exception as e:
                logger.info("Dismantle error {}".format(e))


def init_keeper():
    global keeper
    global backend_handler
    global standalone_config

    access_data = os.path.join(REMOTE_INSTALL_DIR, 'access.data')
    with open(access_data, 'r') as ad:
        vsi_details = json.load(ad)
        logger.info("Parsed self IP {} and instance ID {}"
                    .format(vsi_details['ip_address'],
                            vsi_details['instance_id']))

    backend = standalone_config['backend']
    standalone_config[backend].update(vsi_details)
    backend_handler = StandaloneHandler(standalone_config)

    keeper = threading.Thread(target=budget_keeper)
    keeper.daemon = True
    keeper.start()


def error(msg):
    response = flask.jsonify({'error': msg})
    response.status_code = 404
    return response


@proxy.route('/run', methods=['POST'])
def run():
    """
    Run a job
    """
    global last_usage_time
    global backend_handler
    global jobs

    message = flask.request.get_json(force=True, silent=True)
    if message and not isinstance(message, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime = message['job_description']['runtime_name']
        verify_runtime_name(runtime)
    except Exception as e:
        return error(str(e))

    last_usage_time = time.time()

    standalone_config = message['config']['standalone']
    backend_handler.auto_dismantle = standalone_config['auto_dismantle']
    backend_handler.soft_dismantle_timeout = standalone_config['soft_dismantle_timeout']
    backend_handler.hard_dismantle_timeout = standalone_config['hard_dismantle_timeout']

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    executor_id = message['executor_id']
    job_id = message['job_id']
    job_key = create_job_key(executor_id, job_id)
    jobs[job_key] = 'running'

    pull_runtime = standalone_config.get('pull_runtime', False)
    localhost_handler = LocalhostHandler({'runtime': runtime, 'pull_runtime': pull_runtime})
    localhost_handler.run_job(message)

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

    pull_runtime = standalone_config.get('pull_runtime', False)
    localhost_handler = LocalhostHandler({'runtime': runtime, 'pull_runtime': pull_runtime})
    runtime_meta = localhost_handler.create_runtime(runtime)
    response = flask.jsonify(runtime_meta)
    response.status_code = 200

    return response


def main():
    init_keeper()
    port = int(os.getenv('PORT', PROXY_SERVICE_PORT))
    server = WSGIServer(('0.0.0.0', port), proxy, log=proxy.logger)
    server.serve_forever()


if __name__ == '__main__':
    main()
