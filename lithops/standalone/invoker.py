import os
import sys
import copy
import json
import shlex
import logging
import requests
from concurrent.futures import ThreadPoolExecutor

from lithops.constants import REMOTE_INSTALL_DIR, \
    PX_LOG_FILE, LOGGER_FORMAT, PROXY_SERVICE_PORT
from lithops.storage.utils import create_job_key

STANDALONE_CONFIG_FILE = os.path.join(REMOTE_INSTALL_DIR, 'config')

logging.basicConfig(filename=PX_LOG_FILE, level=logging.DEBUG, format=LOGGER_FORMAT)
logger = logging.getLogger('invoker')

log_file_fd = open(PX_LOG_FILE, 'a')
sys.stdout = log_file_fd
sys.stderr = log_file_fd


def invoke(ip_address, call_id, job_payload):
    """
    Invokes the function against the remote VM instance
    """
    job_payload['job_description']['call_id'] = call_id

    executor_id = job_payload['job_description']['executor_id']
    job_id = job_payload['job_description']['job_id']
    job_key = create_job_key(executor_id, job_id)
    call_key = '-'.join([job_key, call_id])

    url = "http://{}:{}/run".format(ip_address, PROXY_SERVICE_PORT)
    logger.info('Making {} invocation on {}'.format(call_key, ip_address))
    r = requests.post(url, data=json.dumps(job_payload))
    response = r.json()

    if 'activationId' in response:
        logger.info('Invocation {} done. Invocation ID: {}'.format(call_key, response['activationId']))
    else:
        logger.error('Invocation {} failed: {}'.format(call_key, response['error']))


if __name__ == "__main__":
    job_payload = json.loads(sys.argv[1])

    with open(STANDALONE_CONFIG_FILE, 'r') as sc:
        standalone_config = json.load(sc)

    if 'exec_mode' in standalone_config and \
       standalone_config['exec_mode'] == 'create':
        # Run the job on the worker VM instances
        vm_instances = json.loads(sys.argv[2])

        total_calls = job_payload['job_description']['total_calls']
        with ThreadPoolExecutor(total_calls) as executor:
            for i in range(total_calls):
                call_id = "{:05d}".format(i)
                ip_address = vm_instances[call_id]
                executor.submit(invoke, ip_address, call_id, copy.deepcopy(job_payload))
    else:
        # Run the job in the local Vm instance
        url = "http://{}:{}/run".format('127.0.0.1', PROXY_SERVICE_PORT)
        requests.post(url, data=json.dumps(job_payload), verify=True)
