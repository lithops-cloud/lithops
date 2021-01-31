import os
import sys
import json
import logging
import requests

from lithops.constants import REMOTE_INSTALL_DIR, \
    PX_LOG_FILE, LOGGER_FORMAT, PROXY_SERVICE_PORT

STANDALONE_CONFIG_FILE = os.path.join(REMOTE_INSTALL_DIR, 'config')

logging.basicConfig(filename=PX_LOG_FILE, level=logging.INFO, format=LOGGER_FORMAT)
logger = logging.getLogger('invoker')

log_file_fd = open(PX_LOG_FILE, 'a')
sys.stdout = log_file_fd
sys.stderr = log_file_fd


if __name__ == "__main__":

    job_payload = json.loads(sys.argv[1])
    logger.info(job_payload)

    with open(STANDALONE_CONFIG_FILE, 'r') as sc:
        standalone_config = json.load(sc)

    if 'exec_mode' in standalone_config and \
       standalone_config['exec_mode'] == 'create':
        # Run the job on the worker VM instances
        vm_instances = json.loads(sys.argv[2])
        logger.info(vm_instances)

    else:
        # Run the job in the local Vm instance
        url = "http://{}:{}/run".format('127.0.0.1', PROXY_SERVICE_PORT)
        requests.post(url, data=json.dumps(job_payload), verify=True)
