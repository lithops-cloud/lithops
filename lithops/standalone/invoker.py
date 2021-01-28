import os
import sys
import json
import logging
import requests

from lithops.constants import REMOTE_INSTALL_DIR, \
    PX_LOG_FILE, LOGGER_FORMAT, PROXY_SERVICE_PORT

STANDALONE_CONFIG_FILE = os.path.join(REMOTE_INSTALL_DIR, 'config')

logging.basicConfig(filename=PX_LOG_FILE, level=logging.INFO, format=LOGGER_FORMAT)
logger = logging.getLogger('setup')

log_file_fd = open(PX_LOG_FILE, 'a')
sys.stdout = log_file_fd
sys.stderr = log_file_fd


if __name__ == "__main__":

    job_payload = json.loads(sys.argv[1])

    with open(STANDALONE_CONFIG_FILE, 'r') as sc:
        standalone_config = json.load(sc)

    if 'exec_mode' in standalone_config and \
       standalone_config['mode'] == 'create':
        with open('/opt/lithops/cluster.data', 'r') as cip:
            vis_ips = json.load(cip)
    else:
        url = "http://{}:{}/run".format('127.0.0.1', PROXY_SERVICE_PORT)
        requests.post(url, data=json.dumps(job_payload), verify=True)
