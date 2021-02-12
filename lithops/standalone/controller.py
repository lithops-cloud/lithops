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
import sys
import copy
import time
import json
import uuid
import flask
import logging
import requests
import threading
from gevent.pywsgi import WSGIServer
from concurrent.futures import ThreadPoolExecutor

from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DIR, \
    STANDALONE_INSTALL_DIR, SA_LOG_FILE, LOGGER_FORMAT,\
    STANDALONE_SERVICE_PORT, STANDALONE_CONFIG_FILE,\
    STANDALONE_SSH_CREDNTIALS
from lithops.localhost.localhost import LocalhostHandler
from lithops.standalone.standalone import StandaloneHandler
from lithops.utils import verify_runtime_name, iterchunks
from lithops.util.ssh_client import SSHClient
from lithops.standalone.utils import get_worker_setup_script

logging.basicConfig(filename=SA_LOG_FILE, level=logging.INFO,
                    format=LOGGER_FORMAT)
logger = logging.getLogger('lithops.controller')
logging.getLogger('paramiko').setLevel(logging.CRITICAL)

controller = flask.Flask('lithops.controller')

INSTANCE_START_TIMEOUT = 300
LAST_USAGE_TIME = time.time()
KEEPER = None
JOBS = {}
STANDALONE_HANDLER = None
STANDALONE_CONFIG = None


def budget_keeper():
    global LAST_USAGE_TIME
    global JOBS
    global STANDALONE_HANDLER

    jobs_running = False

    logger.info("BudgetKeeper started")

    if STANDALONE_HANDLER.auto_dismantle:
        logger.info('Auto dismantle activated - Soft timeout: {}s, Hard Timeout: {}s'
                    .format(STANDALONE_HANDLER.soft_dismantle_timeout,
                            STANDALONE_HANDLER.hard_dismantle_timeout))
    else:
        # If auto_dismantle is deactivated, the VM will be always automatically
        # stopped after hard_dismantle_timeout. This will prevent the VM
        # being started forever due a wrong configuration
        logger.info('Auto dismantle deactivated - Hard Timeout: {}s'
                    .format(STANDALONE_HANDLER.hard_dismantle_timeout))

    while True:
        time_since_last_usage = time.time() - LAST_USAGE_TIME
        check_interval = STANDALONE_HANDLER.soft_dismantle_timeout / 10
        for job_key in JOBS.keys():
            done = os.path.join(JOBS_DIR, job_key+'.done')
            if os.path.isfile(done):
                JOBS[job_key] = 'done'
        if len(JOBS) > 0 and all(value == 'done' for value in JOBS.values()) \
           and STANDALONE_HANDLER.auto_dismantle:

            # here we need to catch a moment when number of running JOBS become zero.
            # when it happens we reset countdown back to soft_dismantle_timeout
            if jobs_running:
                jobs_running = False
                LAST_USAGE_TIME = time.time()
                time_since_last_usage = time.time() - LAST_USAGE_TIME

            time_to_dismantle = int(STANDALONE_HANDLER.soft_dismantle_timeout - time_since_last_usage)
        else:
            time_to_dismantle = int(STANDALONE_HANDLER.hard_dismantle_timeout - time_since_last_usage)
            jobs_running = True

        if time_to_dismantle > 0:
            logger.info("Time to dismantle: {} seconds".format(time_to_dismantle))
            time.sleep(check_interval)
        else:
            logger.info("Dismantling setup")
            try:
                STANDALONE_HANDLER.dismantle()
            except Exception as e:
                logger.info("Dismantle error {}".format(e))


def init_keeper():
    global KEEPER
    global STANDALONE_HANDLER
    global STANDALONE_CONFIG

    access_data = os.path.join(STANDALONE_INSTALL_DIR, 'access.data')
    with open(access_data, 'r') as ad:
        vsi_details = json.load(ad)
        logger.info("Parsed self name: {}, IP: {} and instance ID: {}"
                    .format(vsi_details['instance_name'],
                            vsi_details['ip_address'],
                            vsi_details['instance_id']))

    STANDALONE_HANDLER = StandaloneHandler(STANDALONE_CONFIG)
    vsi = STANDALONE_HANDLER.backend.create_worker(vsi_details['instance_name'])
    vsi.ip_address = vsi_details['ip_address']
    vsi.instance_id = vsi_details['instance_id']
    vsi.delete_on_dismantle = False if 'master' in vsi_details['instance_name'] else True

    KEEPER = threading.Thread(target=budget_keeper)
    KEEPER.daemon = True
    KEEPER.start()


def is_instance_ready(ssh_client):
    """
    Checks if the VM instance is ready to receive ssh connections
    """
    try:
        ssh_client.run_remote_command('id')
    except Exception:
        ssh_client.close()
        return False
    return True


def wait_instance_ready(ssh_client):
    """
    Waits until the VM instance is ready to receive ssh connections
    """
    ip_addr = ssh_client.ip_address
    logger.info('Waiting VM instance {} to become ready'.format(ip_addr))

    start = time.time()
    while(time.time() - start < INSTANCE_START_TIMEOUT):
        if is_instance_ready(ssh_client):
            logger.info('VM instance {} ready in {} seconds'
                        .format(ip_addr, round(time.time()-start, 2)))
            return True
        time.sleep(5)

    raise Exception('VM readiness {} probe expired. Check your master VM'.format(ip_addr))


def is_proxy_ready(ip_addr):
    """
    Checks if the proxy is ready to receive http connections
    """
    try:
        url = "http://{}:{}/ping".format(ip_addr, STANDALONE_SERVICE_PORT)
        r = requests.get(url, timeout=1)
        if r.status_code == 200:
            return True
        return False
    except Exception:
        return False


def wait_proxy_ready(ip_addr):
    """
    Waits until the proxy is ready to receive http connections
    """

    logger.info('Waiting Lithops proxy to become ready on {}'.format(ip_addr))

    start = time.time()
    while(time.time() - start < INSTANCE_START_TIMEOUT):
        if is_proxy_ready(ip_addr):
            logger.info('Lithops proxy {} ready in {} seconds'
                        .format(ip_addr, round(time.time()-start, 2)))
            return True
        time.sleep(2)

    raise Exception('Proxy readiness probe expired on {}. Check your VM'.format(ip_addr))


def run_job_on_worker(worker_info, call_ids_range, job_payload):
    """
    Install all the Lithops dependencies into the worker.
    Runs the job
    """
    instance_name, ip_address, instance_id = worker_info
    logger.info('Going to setup {}, IP address {}'.format(instance_name, ip_address))

    ssh_client = SSHClient(ip_address, STANDALONE_SSH_CREDNTIALS)
    wait_instance_ready(ssh_client)

    # upload zip lithops package
    logger.info('Uploading lithops files to VM instance {}'.format(ip_address))
    ssh_client.upload_local_file('/opt/lithops/lithops_standalone.zip', '/tmp/lithops_standalone.zip')
    logger.info('Executing lithops installation process on VM instance {}'.format(ip_address))
    script = get_worker_setup_script(worker_info, STANDALONE_CONFIG)
    logger.info(script)
    ssh_client.run_remote_command(script, run_async=True)
    ssh_client.close()

    # Wait until the proxy is ready
    wait_proxy_ready(ip_address)

    dbr = job_payload['data_byte_ranges']
    job_payload['call_ids'] = call_ids_range
    job_payload['data_byte_ranges'] = [dbr[int(call_id)] for call_id in call_ids_range]

    url = "http://{}:{}/run".format(ip_address, STANDALONE_SERVICE_PORT)
    r = requests.post(url, data=json.dumps(job_payload))
    response = r.json()

    if 'activationId' in response:
        logger.info('Calls {} invoked. Activation ID: {}'
                    .format(', '.join(call_ids_range), response['activationId']))
    else:
        logger.error('calls {} failed invocation: {}'
                     .format(', '.join(call_ids_range), response['error']))


def error(msg):
    response = flask.jsonify({'error': msg})
    response.status_code = 404
    return response


@controller.route('/run-create', methods=['POST'])
def run_create():
    """
    Runs a given job remotely in workers, in create mode
    """
    global LAST_USAGE_TIME
    global STANDALONE_CONFIG
    global JOBS

    logger.info('Running job on worker VMs')

    job_payload = flask.request.get_json(force=True, silent=True)
    if job_payload and not isinstance(job_payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime = job_payload['runtime_name']
        verify_runtime_name(runtime)
    except Exception as e:
        return error(str(e))

    LAST_USAGE_TIME = time.time()

    STANDALONE_CONFIG.update(job_payload['config']['standalone'])

    call_ids = job_payload['call_ids']
    chunksize = job_payload['chunksize']
    workers = job_payload['woreker_instances']

    JOBS[job_payload['job_key']] = 'running'

    with ThreadPoolExecutor(len(workers)) as executor:
        for call_ids_range in iterchunks(call_ids, chunksize):
            worker_info = workers.pop(0)
            executor.submit(run_job_on_worker,
                            worker_info,
                            call_ids_range,
                            copy.deepcopy(job_payload))

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    response = flask.jsonify({'activationId': act_id})
    response.status_code = 202

    return response


@controller.route('/run', methods=['POST'])
def run():
    """
    Run a job locally, in consume mode
    """
    global LAST_USAGE_TIME
    global STANDALONE_HANDLER
    global JOBS

    job_payload = flask.request.get_json(force=True, silent=True)
    if job_payload and not isinstance(job_payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime = job_payload['runtime_name']
        verify_runtime_name(runtime)
    except Exception as e:
        return error(str(e))

    LAST_USAGE_TIME = time.time()

    STANDALONE_CONFIG.update(job_payload['config']['standalone'])
    STANDALONE_HANDLER.auto_dismantle = STANDALONE_CONFIG['auto_dismantle']
    STANDALONE_HANDLER.soft_dismantle_timeout = STANDALONE_CONFIG['soft_dismantle_timeout']
    STANDALONE_HANDLER.hard_dismantle_timeout = STANDALONE_CONFIG['hard_dismantle_timeout']

    JOBS[job_payload['job_key']] = 'running'

    pull_runtime = STANDALONE_CONFIG.get('pull_runtime', False)
    localhost_handler = LocalhostHandler({'runtime': runtime, 'pull_runtime': pull_runtime})
    localhost_handler.run_job(job_payload)

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    response = flask.jsonify({'activationId': act_id})
    response.status_code = 202

    return response


@controller.route('/ping', methods=['GET'])
def ping():
    response = flask.jsonify({'response': 'pong'})
    response.status_code = 200

    return response


@controller.route('/preinstalls', methods=['GET'])
def preinstalls():

    payload = flask.request.get_json(force=True, silent=True)
    if payload and not isinstance(payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime = payload['runtime']
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

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    with open(STANDALONE_CONFIG_FILE, 'r') as cf:
        STANDALONE_CONFIG = json.load(cf)

    with open(SA_LOG_FILE, 'a') as log_file:
        sys.stdout = log_file
        sys.stderr = log_file
        init_keeper()
        server = WSGIServer(('0.0.0.0', STANDALONE_SERVICE_PORT),
                            controller, log=controller.logger)
        server.serve_forever()


if __name__ == '__main__':
    main()