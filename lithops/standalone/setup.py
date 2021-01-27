import os
import json
import logging
import subprocess as sp
from lithops.util.ssh_client import SSHClient

INSTALL_DIR = '/opt/lithops'
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


logger = logging.getLogger(__name__)


def get_setup_cmd(ip_address, instance_id):
    # Create files and directories
    cmd = 'systemctl daemon-reload; systemctl stop {}; '.format(PROXY_SERVICE_NAME)
    cmd += 'rm -R {0}; mkdir -p {0}; '.format(INSTALL_DIR)
    cmd += 'mkdir -p /tmp/lithops; '
    service_file = '/etc/systemd/system/{}'.format(PROXY_SERVICE_NAME)
    cmd += "echo '{}' > {};".format(PROXY_SERVICE_FILE, service_file)
    cmd += "echo '{}' > {};".format(json.dumps(STANDALONE_CONFIG), STANDALONE_CONFIG_FILE)

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
    cmd += 'apt-get install docker-ce docker-ce-cli containerd.io -y >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'pip3 install -U flask gevent lithops paramiko >> /tmp/lithops/proxy.log 2>&1; '
    cmd += 'fi; '

    # Unzip lithops package
    cmd += 'touch {}/access.data; '.format(INSTALL_DIR)
    vsi_data = {'ip_address': ip_address, 'instance_id': instance_id}
    cmd += "echo '{}' > {}/access.data; ".format(json.dumps(vsi_data), INSTALL_DIR)
    cmd += 'unzip -o /tmp/lithops_standalone.zip -d {} > /dev/null 2>&1; '.format(INSTALL_DIR)
    cmd += 'rm /tmp/lithops_standalone.zip; '

    # Start proxy service
    cmd += 'chmod 644 {}; '.format(service_file)
    cmd += 'systemctl daemon-reload; '
    cmd += 'systemctl stop {}; '.format(PROXY_SERVICE_NAME)
    cmd += 'systemctl enable {}; '.format(PROXY_SERVICE_NAME)
    cmd += 'systemctl start {}; '.format(PROXY_SERVICE_NAME)

    return cmd


def setup_proxy(ip_address):

    ssh_client = SSHClient(ip_address, INTERNAL_SSH_CREDNTIALS)

    # upload zip lithops package
    ssh_client.upload_local_file('/tmp/lithops_standalone.zip', '/tmp/lithops_standalone.zip')
    cmd = get_setup_cmd(ip_address)
    out = ssh_client.run_remote_command(cmd)
    print(out)


if __name__ == "__main__":
    if 'exec_mode' in STANDALONE_CONFIG and \
      STANDALONE_CONFIG['mode'] == 'create':
        with open('/opt/lithops/cluster.data', 'r') as cip:
            vis_ips = json.load(cip)
    else:
        with open('/opt/lithops/access.data', 'r') as ca:
            vsi_data = json.load(ca)
        cmd = get_setup_cmd(vsi_data['ip_address'], vsi_data['instance_id'])
        print(cmd)
        sp.run(cmd, shell=True, check=True, stdout=sp.PIPE, universal_newlines=True)
