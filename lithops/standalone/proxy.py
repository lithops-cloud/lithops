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
import subprocess as sp
from gevent.pywsgi import WSGIServer

from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DONE_DIR, \
    REMOTE_INSTALL_DIR, PX_LOG_FILE, LOGS_DIR
from lithops.storage.utils import create_job_key
from lithops.localhost.localhost import LocalhostHandler
from lithops.standalone.standalone import StandaloneHandler
from lithops import constants
from lithops.utils import verify_runtime_name


os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

log_file_fd = open(PX_LOG_FILE, 'a')
sys.stdout = log_file_fd
sys.stderr = log_file_fd

logging.basicConfig(filename=PX_LOG_FILE, level=logging.INFO,
                    format=constants.LOGGER_FORMAT)
logger = logging.getLogger('proxy')

proxy = flask.Flask(__name__)

last_usage_time = time.time()
keeper = None
jobs = {}
backend_handler = None


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
                backend_handler.backend.stop()
            except Exception as e:
                logger.info("Dismantle error {}".format(e))


def init_keeper():
    global keeper
    global backend_handler

    config_file = os.path.join(REMOTE_INSTALL_DIR, 'config')
    with open(config_file, 'r') as cf:
        standalone_config = json.load(cf)

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

    localhost_handler = LocalhostHandler({'runtime': runtime})
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
        return error()

    try:
        runtime = message['runtime']
        verify_runtime_name(runtime)
    except Exception as e:
        return error(str(e))

    localhost_handler = LocalhostHandler(message)
    runtime_meta = localhost_handler.create_runtime(runtime)
    response = flask.jsonify(runtime_meta)
    response.status_code = 200

    return response


def install_environment():
    """
    Install docker command and Python deps in case they are not installed.
    Only for Ubuntu-based OS
    """

    os_version = sp.check_output('uname -a', shell=True).decode()

    if 'Ubuntu' in os_version:
        try:
            sp.check_output('docker ps > /dev/null 2>&1', shell=True)
            docker_installed = True
            logger.info("Environment already installed")
        except Exception:
            logger.info("Environment not installed")
            docker_installed = False

        if not docker_installed:
            # If docker is not installed, nothing is installed, so lets install anything here
            cmd = 'apt-get remove docker docker-engine docker.io containerd runc -y; '
            cmd += 'apt-get update '
            cmd += '&& apt-get install apt-transport-https ca-certificates curl gnupg-agent software-properties-common -y '
            cmd += '&& curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add - > /dev/null 2>&1 '
            cmd += '&& add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" '
            cmd += '&& apt-get update '
            cmd += '&& apt-get install docker-ce docker-ce-cli containerd.io -y '
            try:
                logger.info("Installing Docker...")
                with open(PX_LOG_FILE, 'a') as lf:
                    sp.run(cmd, shell=True, stdout=lf, stderr=lf, universal_newlines=True)
                logger.info("Docker installed successfully")
            except Exception as e:
                logger.info("There was an error installing Docker: {}".format(e))

            cmd = 'pip3 install -U lithops'
            try:
                logger.info("Installing python packages...")
                with open(PX_LOG_FILE, 'a') as lf:
                    sp.run(cmd, shell=True, stdout=lf, stderr=lf, universal_newlines=True)
                logger.info("Python packages installed successfully")
            except Exception as e:
                logger.info("There was an error installing the python packages: {}".format(e))
    else:
        logger.info("Linux images different from Ubuntu do not support automatic environment installation")


def main():
    install_environment()
    init_keeper()
    port = int(os.getenv('PORT', 8080))
    server = WSGIServer(('127.0.0.1', port), proxy, log=proxy.logger)
    server.serve_forever()


if __name__ == '__main__':
    main()
