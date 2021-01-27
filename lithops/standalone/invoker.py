import os
import sys
import json
import logging
import requests

INSTALL_DIR = '/opt/lithops'
PX_LOG_FILE = '/tmp/lithops/proxy.log'
LOGGER_FORMAT = "%(asctime)s [%(levelname)s] %(name)s -- %(message)s"
PROXY_SERVICE_PORT = 8080

STANDALONE_CONFIG_FILE = os.path.join(INSTALL_DIR, 'config')
STANDALONE_CONFIG = json.loads(open(STANDALONE_CONFIG_FILE, 'r').read())

logging.basicConfig(filename=PX_LOG_FILE, level=logging.INFO, format=LOGGER_FORMAT)
logger = logging.getLogger('setup')


if __name__ == "__main__":

    job_payload = json.loads(sys.argv[1])

    if 'exec_mode' in STANDALONE_CONFIG and \
       STANDALONE_CONFIG['mode'] == 'create':
        with open('/opt/lithops/cluster.data', 'r') as cip:
            vis_ips = json.load(cip)
    else:
        url = "http://{}:{}/run".format('127.0.0.1', PROXY_SERVICE_PORT)
        r = requests.post(url, data=json.dumps(job_payload), verify=True)
        print(r.text)
