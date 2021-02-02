import os
import sys
import time
import json
import logging
import copy
import requests
import subprocess as sp
from ssh_client import SSHClient
from concurrent.futures import ThreadPoolExecutor

PX_LOG_FILE = '/tmp/lithops/proxy.log'
LOGGER_FORMAT = "%(asctime)s [%(levelname)s] %(name)s -- %(message)s"
INSTALL_DIR = '/opt/lithops'

START_TIMEOUT = 300

PROXY_SERVICE_NAME = 'lithopsproxy.service'
PROXY_SERVICE_PORT = 8080
PROXY_SERVICE_FILE = """
[Unit]
Description=Lithops Proxy
After=network.target

[Service]
ExecStart=/usr/bin/python3 {}/proxy.py
Restart=always

[Install]
WantedBy=multi-user.target
""".format(INSTALL_DIR)

INTERNAL_SSH_CREDNTIALS = {'username': 'root', 'password': 'lithops'}
STANDALONE_CONFIG_FILE = os.path.join(INSTALL_DIR, 'config')
STANDALONE_CONFIG = json.loads(open(STANDALONE_CONFIG_FILE, 'r').read())

log_file_fd = open(PX_LOG_FILE, 'a')
sys.stdout = log_file_fd
sys.stderr = log_file_fd

logging.basicConfig(filename=PX_LOG_FILE, level=logging.INFO,
                    format=LOGGER_FORMAT)
logger = logging.getLogger('lithops.controller')
logging.getLogger('paramiko').setLevel(logging.CRITICAL)


def get_setup_cmd(instance_name=None, ip_address=None, instance_id=None, worker=True):

    service_file = '/etc/systemd/system/{}'.format(PROXY_SERVICE_NAME)
    cmd = "echo '{}' > {}; ".format(PROXY_SERVICE_FILE, service_file)

    if worker:
        # Create files and directories
        cmd += 'rm -R {0}; mkdir -p {0}; mkdir -p /tmp/lithops;'.format(INSTALL_DIR)
        cmd += "echo '{}' > {}; ".format(json.dumps(STANDALONE_CONFIG), STANDALONE_CONFIG_FILE)

    # Install dependencies (only if they are not installed)
    cmd += 'command -v unzip >/dev/null 2>&1 || { export INSTALL_LITHOPS_DEPS=true; }; '
    cmd += 'command -v pip3 >/dev/null 2>&1 || { export INSTALL_LITHOPS_DEPS=true; }; '
    cmd += 'command -v docker >/dev/null 2>&1 || { export INSTALL_LITHOPS_DEPS=true; }; '
    cmd += 'if [ "$INSTALL_LITHOPS_DEPS" = true ] ; then '
    cmd += 'rm /var/lib/apt/lists/* -vfR >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'apt-get clean >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'apt-get update >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'apt-get install unzip python3-pip apt-transport-https ca-certificates curl software-properties-common gnupg-agent -y >> /tmp/lithops/proxy.log 2>&1;'
    cmd += 'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add - >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'apt-get update >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'apt-get install unzip python3-pip docker-ce docker-ce-cli containerd.io -y >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'pip3 install -U flask gevent lithops >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'fi; '

    if worker:
        # Unzip lithops package
        cmd += 'touch {}/access.data; '.format(INSTALL_DIR)
        vsi_data = {'instance_name': instance_name, 'ip_address': ip_address, 'instance_id': instance_id}
        cmd += "echo '{}' > {}/access.data; ".format(json.dumps(vsi_data), INSTALL_DIR)
    cmd += 'unzip -o /tmp/lithops_standalone.zip -d {} > /dev/null 2>&1; '.format(INSTALL_DIR)

    # Start proxy service
    cmd += 'chmod 644 {}; '.format(service_file)
    cmd += 'systemctl daemon-reload; '
    cmd += 'systemctl stop {}; '.format(PROXY_SERVICE_NAME)
    cmd += 'systemctl enable {}; '.format(PROXY_SERVICE_NAME)
    cmd += 'systemctl start {}; '.format(PROXY_SERVICE_NAME)

    return cmd


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
    while(time.time() - start < START_TIMEOUT):
        if is_instance_ready(ssh_client):
            logger.info('VM instance {} ready in {}'
                        .format(ip_addr, round(time.time()-start, 2)))
            return True
        time.sleep(5)

    raise Exception('VM readiness {} probe expired. Check your master VM'.format(ip_addr))


def is_proxy_ready(ip_addr):
    """
    Checks if the proxy is ready to receive http connections
    """
    try:
        url = "http://{}:{}/ping".format(ip_addr, PROXY_SERVICE_PORT)
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
    while(time.time() - start < START_TIMEOUT):
        if is_proxy_ready(ip_addr):
            logger.info('Lithops proxy ready on {}'.format(ip_addr))
            return True
        time.sleep(2)

    raise Exception('Proxy readiness probe expired on {}. Check your VM'.format(ip_addr))


def run_job_on_worker(worek_info, call_id, job_payload):
    """
    Install all the Lithops dependencies into the worker.
    Runs the job
    """
    instance_name, ip_address, instance_id = worek_info
    logger.info('Going to setup {}, IP address {}'.format(instance_name, ip_address))

    ssh_client = SSHClient(ip_address, INTERNAL_SSH_CREDNTIALS)
    wait_instance_ready(ssh_client)

    # upload zip lithops package
    logger.info('Uploading lithops files to VM instance {}'.format(ip_address))
    ssh_client.upload_local_file('/opt/lithops/lithops_standalone.zip', '/tmp/lithops_standalone.zip')
    logger.info('Executing lithops installation process on VM instance {}'.format(ip_address))
    cmd = get_setup_cmd(instance_name, ip_address, instance_id)
    ssh_client.run_remote_command(cmd, run_async=True)
    ssh_client.close()

    # Wait until the proxy is ready
    wait_proxy_ready(ip_address)

    job_payload['job_description']['call_id'] = call_id

    executor_id = job_payload['job_description']['executor_id']
    job_id = job_payload['job_description']['job_id']
    call_key = '-'.join([executor_id, job_id, call_id])

    url = "http://{}:{}/run".format(ip_address, PROXY_SERVICE_PORT)
    logger.info('Making {} invocation on {}'.format(call_key, ip_address))
    r = requests.post(url, data=json.dumps(job_payload))
    response = r.json()

    if 'activationId' in response:
        logger.info('Invocation {} done. Activation ID: {}'.format(call_key, response['activationId']))
    else:
        logger.error('Invocation {} failed: {}'.format(call_key, response['error']))


def run_job():
    """
    Runs a given job
    """
    global STANDALONE_CONFIG

    job_payload = json.loads(sys.argv[2])

    STANDALONE_CONFIG.update(job_payload['config']['standalone'])

    total_calls = job_payload['job_description']['total_calls']
    exec_mode = job_payload['config']['standalone'].get('exec_mode', 'consume')

    if exec_mode == 'create':
        workers = json.loads(sys.argv[3])
        with ThreadPoolExecutor(total_calls) as executor:
            for i in range(total_calls):
                call_id = "{:05d}".format(i)
                worek_info = workers[call_id]
                executor.submit(run_job_on_worker, worek_info, call_id,
                                copy.deepcopy(job_payload))
    else:
        # Run the job in the local Vm instance
        url = "http://{}:{}/run".format('127.0.0.1', PROXY_SERVICE_PORT)
        requests.post(url, data=json.dumps(job_payload))


def setup_master():
    """
    Setup master VM
    """
    cmd = get_setup_cmd(worker=False)
    log_file = open(PX_LOG_FILE, 'a')
    sp.run(cmd, shell=True, check=True, stdout=log_file,
           stderr=log_file, universal_newlines=True)


if __name__ == "__main__":
    logger.info('Starting Master VM Controller service')
    command = sys.argv[1]
    logger.info('Received command: {}'.format(command))

    switcher = {
        'setup': setup_master,
        'run': run_job
    }

    func = switcher.get(command, lambda: "Invalid command")
    func()
