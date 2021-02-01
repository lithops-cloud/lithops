import os
import sys
import time
import json
import logging
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
logger = logging.getLogger('setup')
logging.getLogger('paramiko').setLevel(logging.CRITICAL)


def get_setup_cmd(instance_name=None, ip_address=None, instance_id=None, remote=True):

    service_file = '/etc/systemd/system/{}'.format(PROXY_SERVICE_NAME)
    cmd = "echo '{}' > {}; ".format(PROXY_SERVICE_FILE, service_file)

    if remote:
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

    if remote:
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


def is_instance_ready(ip_addr):
    """
    Checks if the VM instance is ready to receive ssh connections
    """
    try:
        ssh_client = SSHClient(ip_addr, INTERNAL_SSH_CREDNTIALS)
        ssh_client.run_remote_command('id')
    except Exception:
        return False
    return True


def wait_instance_ready(ip_addr):
    """
    Waits until the VM instance is ready to receive ssh connections
    """

    logger.info('Waiting VM instance {} to become ready'.format(ip_addr))

    start = time.time()
    while(time.time() - start < START_TIMEOUT):
        if is_instance_ready(ip_addr):
            logger.info('VM instance {} ready in {}'.format(ip_addr, round(time.time()-start, 2)))
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


def setup_worker(instance_info):
    """
    Install all the Lithops dependencies into the worker
    """

    instance_name, ip_address, instance_id = instance_info
    logger.info('Going to setup {}, IP address {}'.format(instance_name, ip_address))
    wait_instance_ready(ip_address)

    ssh_client = SSHClient(ip_address, INTERNAL_SSH_CREDNTIALS)
    # upload zip lithops package
    logger.info('Uploading lithops files to VM instance {}'.format(ip_address))
    ssh_client.upload_local_file('/opt/lithops/lithops_standalone.zip', '/tmp/lithops_standalone.zip')
    logger.info('Executing lithops installation process on VM instance {}'.format(ip_address))
    cmd = get_setup_cmd(instance_name, ip_address, instance_id)
    ssh_client.run_remote_command(cmd, run_async=True)
    # Wait until the proxy is ready
    wait_proxy_ready(ip_address)


if __name__ == "__main__":
    if 'exec_mode' in STANDALONE_CONFIG and \
      STANDALONE_CONFIG['exec_mode'] == 'create' \
      and len(sys.argv) > 1:
        vm_instances = json.loads(sys.argv[1])
        with ThreadPoolExecutor(len(vm_instances)) as executor:
            executor.map(setup_worker, vm_instances)

    else:
        cmd = get_setup_cmd(remote=False)
        log_file = open(PX_LOG_FILE, 'a')
        sp.run(cmd, shell=True, check=True, stdout=log_file,
               stderr=log_file, universal_newlines=True)
