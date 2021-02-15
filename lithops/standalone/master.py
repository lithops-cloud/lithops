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
from pathlib import Path
from gevent.pywsgi import WSGIServer
from concurrent.futures import ThreadPoolExecutor

from lithops.constants import LITHOPS_TEMP_DIR, STANDALONE_LOG_FILE, JOBS_DIR,\
    STANDALONE_SSH_CREDNTIALS, STANDALONE_SERVICE_PORT, STANDALONE_CONFIG_FILE
from lithops.localhost.localhost import LocalhostHandler
from lithops.utils import verify_runtime_name, iterchunks, setup_lithops_logger
from lithops.util.ssh_client import SSHClient
from lithops.standalone.utils import get_worker_setup_script
from lithops.standalone.keeper import BudgetKeeper


setup_lithops_logger(logging.DEBUG, filename=STANDALONE_LOG_FILE)
logger = logging.getLogger('lithops.standalone.master')

controller = flask.Flask('lithops.standalone.master')

INSTANCE_START_TIMEOUT = 300
STANDALONE_CONFIG = None
BUDGET_KEEPER = None


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

    vm_data = {'instance_name': instance_name,
               'ip_address': ip_address,
               'instance_id': instance_id}

    script = get_worker_setup_script(STANDALONE_CONFIG, vm_data)
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
    global BUDGET_KEEPER

    logger.info('Running job on worker VMs')

    job_payload = flask.request.get_json(force=True, silent=True)
    if job_payload and not isinstance(job_payload, dict):
        return error('The action did not receive a dictionary as an argument.')

    try:
        runtime = job_payload['runtime_name']
        verify_runtime_name(runtime)
    except Exception as e:
        return error(str(e))

    job_key = job_payload['job_key']
    call_ids = job_payload['call_ids']
    chunksize = job_payload['chunksize']
    workers = job_payload['woreker_instances']

    BUDGET_KEEPER.last_usage_time = time.time()
    BUDGET_KEEPER.update_config(job_payload['config']['standalone'])
    BUDGET_KEEPER.jobs[job_key] = 'running'

    with ThreadPoolExecutor(len(workers)) as executor:
        for call_ids_range in iterchunks(call_ids, chunksize):
            worker_info = workers.pop(0)
            executor.submit(run_job_on_worker,
                            worker_info,
                            call_ids_range,
                            copy.deepcopy(job_payload))

    done = os.path.join(JOBS_DIR, job_key+'.done')
    Path(done).touch()

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    response = flask.jsonify({'activationId': act_id})
    response.status_code = 202

    return response


@controller.route('/run', methods=['POST'])
def run():
    """
    Run a job locally, in consume mode
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
    global BUDGET_KEEPER

    os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)

    with open(STANDALONE_CONFIG_FILE, 'r') as cf:
        STANDALONE_CONFIG = json.load(cf)

    with open(STANDALONE_LOG_FILE, 'a') as log_file:
        sys.stdout = log_file
        sys.stderr = log_file
        BUDGET_KEEPER = BudgetKeeper(STANDALONE_CONFIG)
        BUDGET_KEEPER.start()
        server = WSGIServer(('0.0.0.0', STANDALONE_SERVICE_PORT),
                            controller, log=controller.logger)
        server.serve_forever()


if __name__ == '__main__':
    main()
