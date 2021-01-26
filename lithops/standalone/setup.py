import json
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


def setup_proxy(ip_address):
    
    logger.debug('Upload zip file to {} - start'.format(ip_address))
    ssh_client.upload_local_file(ip_address, LOCAL_FH_ZIP_LOCATION, '/tmp/lithops_standalone.zip')
    logger.debug('Upload zip file to {} - completed'.format(ip_address))
    
    ssh_client.upload_local_file(ip_address, '/tmp/lithops_standalone.zip', '/tmp/lithops_standalone.zip')
    logger.debug('Upload zip file to {} - completed'.format(ip_address))
    
    # Create files and directories
    cmd = 'systemctl daemon-reload; systemctl stop {}; '.format(PROXY_SERVICE_NAME)
    cmd += 'rm -R {}; mkdir -p {}; '.format(INSTALL_DIR, INSTALL_DIR)
    cmd += 'mkdir -p /tmp/lithops; '.format(INSTALL_DIR, INSTALL_DIR)
    service_file = '/etc/systemd/system/{}'.format(PROXY_SERVICE_NAME)
    cmd += "echo '{}' > {};".format(PROXY_SERVICE_FILE, service_file)
    config_file = os.path.join(INSTALL_DIR, 'config')
    cmd += "echo '{}' > {};".format(json.dumps(self.config), config_file)

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
    vsi_data = {'ip_address': ip_address, 'instance_id': ep_instance.get_instance_id()}
    cmd += "echo '{}' > {}/access.data; ".format(json.dumps(vsi_data), INSTALL_DIR)
    cmd += 'unzip -o /tmp/lithops_standalone.zip -d {} > /dev/null 2>&1; '.format(INSTALL_DIR)
    cmd += 'rm /tmp/lithops_standalone.zip; '

    # Start proxy service
    cmd += 'chmod 644 {}; '.format(service_file)
    cmd += 'systemctl daemon-reload; '
    cmd += 'systemctl stop {}; '.format(PROXY_SERVICE_NAME)
    cmd += 'systemctl enable {}; '.format(PROXY_SERVICE_NAME)
    cmd += 'systemctl start {}; '.format(PROXY_SERVICE_NAME)


if __name__ == "__main__":

    with open('cluster.ips', 'r') as cip:
        vis_ips = json.load(cip)

