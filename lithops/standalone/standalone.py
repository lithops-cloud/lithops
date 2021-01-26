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
import json
import time
import select
import logging
import importlib
import requests
import copy
import shlex
from threading import Thread
from cryptography.fernet import Fernet
from concurrent.futures import ThreadPoolExecutor

from lithops.utils import is_lithops_worker, create_handler_zip
from lithops.constants import LOGS_DIR, REMOTE_INSTALL_DIR, FN_LOG_FILE
from lithops.storage.utils import create_job_key

logger = logging.getLogger(__name__)
FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_standalone.zip')
INVOKER_FILE = '{}/invoker.py'.format(REMOTE_INSTALL_DIR)

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
""".format(REMOTE_INSTALL_DIR)


class VitualMachineInstance:
    def __init__(self, backend, ip_address, ssh_client):
        self.backend = backend
        self.ip_address = ip_address
        self.ssh_client = ssh_client
        
        


class StandaloneHandler:
    """
    A StandaloneHandler object is used by invokers and other components to access
    underlying standalone backend without exposing the implementation details.
    """

    def __init__(self, standalone_config):
        self.config = standalone_config
        self.backend_name = self.config['backend']
        self.runtime = self.config['runtime']
        self.is_lithops_worker = is_lithops_worker()

        self.start_timeout = self.config.get('start_timeout', 300)
        self.auto_dismantle = self.config.get('auto_dismantle')
        self.hard_dismantle_timeout = self.config.get('hard_dismantle_timeout')
        self.soft_dismantle_timeout = self.config.get('soft_dismantle_timeout')
        self.pull_runtime = self.config.get('pull_runtime', False)

        module_location = 'lithops.standalone.backends.{}'.format(self.backend_name)
        sb_module = importlib.import_module(module_location)
        self.StandaloneInstance = getattr(sb_module, 'StandaloneInstance')

        self.exec_mode = self.config.get('exec_mode', 'consume')
        self.instances = []

        vsi = self.StandaloneInstance(self.config[self.backend_name], public_vsi=True)
        self.instances.append(vsi)

        logger.debug("Standalone handler created successfully")

    def _is_instance_ready(self, instance):
        """
        Checks if the VM instance is ready to receive ssh connections
        """
        try:
            if instance.is_ready():
                instance.get_ssh_client().run_remote_command(instance.get_ip_address(), 'id', timeout=2)
            else:
                return False
        except Exception:
            return False
        return True

    def _wait_instance_ready(self, instance):
        """
        Waits until the VM instance is ready to receive ssh connections
        """
        logger.debug('Waiting VM instance {} to become ready'.format(instance.get_ip_address()))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_instance_ready(instance):
                return True
            time.sleep(5)

        self.dismantle()
        raise Exception('VM readiness {} probe expired. Check your VM'.format(instance.get_ip_address()))

    def _is_proxy_ready(self, instance):
        """
        Checks if the proxy is ready to receive http connections
        """
        try:
            if self.is_lithops_worker:
                ip_addr = instance.get_ip_address() if self.use_http else '127.0.0.1'
                url = "http://{}:{}/ping".format(ip_addr, PROXY_SERVICE_PORT)
                r = requests.get(url, timeout=1, verify=True)
                if r.status_code == 200:
                    return True
                return False
            else:
                ip_addr = instance.get_ip_address()
                cmd = 'curl -X GET http://127.0.0.1:8080/ping'
                out = instance.get_ssh_client().run_remote_command(ip_addr, cmd, timeout=2)
                data = json.loads(out)
                if data['response'] == 'pong':
                    return True
        except Exception:
            return False

    def _wait_proxy_ready(self, instance):
        """
        Waits until the proxy is ready to receive http connections
        """
        ip_address = instance.get_ip_address()
        logger.info('Waiting Lithops proxy to become ready for {}'.format(ip_address))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_proxy_ready(instance):
                return True
            time.sleep(2)

        self.dismantle()
        raise Exception('Proxy readiness probe expired for {}. Check your VM'.format(ip_address))

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        total_calls = job_payload['job_description']['total_calls']

        if self.exec_mode == 'create':
            # First VSI (entry point instance) is already created in __init__
            vsi_to_create = total_calls - 1

            for vsi_n in range(vsi_to_create): 
                vsi = self.StandaloneInstance(self.config[self.backend_name])
                self.instances.append(vsi)

            with ThreadPoolExecutor(vsi_to_create) as executor:
                executor.map(lambda vsi: vsi.create(), self.instances)

        # Entry point instance
        ep_instance = self.instances[0]
        ip_address = ep_instance.get_ip_address()

        logger.debug("Check if entry point instance ready for {} ".format(ip_address))
        if not self._is_proxy_ready(ep_instance):
            logger.debug("Entry point instance not ready {} ".format(ip_address))
            # if entry point VSI is topped, this means all VSIs are stopped
            with ThreadPoolExecutor(total_calls) as executor:
                executor.map(lambda vsi: vsi.start(), self.instances)
            # Wait only for the entry point instance
            self._wait_instance_ready(ep_instance)
            if self.exec_mode == 'create':
                self._setup_lithops(ep_instance)

        cmd = 'python3 {} {}'.format(INVOKER_FILE, shlex.quote(json.dumps(job_payload)))
        out = ep_instance.get_ssh_client().run_remote_command(ip_address, cmd)
        logger.debug(out)
        response = json.loads(out)

        act_id = response['activationId']
        logger.debug('Job invoked on {}. Activation ID: {}'.format(ip_address, act_id))

        return act_id

    def create_runtime(self, runtime):
        """
        Installs the proxy and extracts the runtime metadata and
        preinstalled modules
        """
        ep_instance = self.instances[0]
        ep_instance.create()
        ep_instance.start()
        self._wait_instance_ready(ep_instance)
        self._setup_lithops(ep_instance)

        logger.debug('Extracting runtime metadata information')
        payload = {'runtime': runtime, 'pull_runtime': self.pull_runtime}
        cmd = 'python3 {} {}'.format(INVOKER_FILE, shlex.quote(json.dumps(payload)))
        out = ep_instance.get_ssh_client().run_remote_command(ep_instance.get_ip_address(), cmd)
        runtime_meta = json.loads(out)

        return runtime_meta

    def dismantle(self):
        """
        Stop all VM instances
        """
        logger.info("Entering dismantle for length {}".format(len(self.backends)))
        for instance in self.instances:
            logger.debug("Dismantle {} for {}".format(instance.get_instance_id(), instance.get_ip_address()))
            instance.stop()

    def clean(self):
        pass

    def clear(self):
        pass

    def get_runtime_key(self, runtime_name):
        """
        Wrapper method that returns a formated string that represents the
        runtime key. Each backend has its own runtime key format. Used to
        store modules preinstalls into the storage
        """
        return self.instances[0].get_runtime_key(runtime_name)

    def _setup_lithops(self, ep_instance):
        """
        Setup lithops necessary files and dirs in all VSIs using the entry point instance
        """
        ip_address = ep_instance.get_ip_address()
        logger.debug('Installing Lithops in VM instance {}'.format(ip_address))
        ssh_client = ep_instance.get_ssh_client()

        # Upload local lithops version to remote VM instance
        src_proxy = os.path.join(os.path.dirname(__file__), 'proxy.py')
        FH_ZIP_LOCATION_IP = os.path.join(os.getcwd(), ip_address.replace('.', 'a') + 'lithops_standalone.zip')
        create_handler_zip(FH_ZIP_LOCATION_IP, src_proxy)
        logger.debug('Upload zip file to {} - start'.format(ip_address))
        ssh_client.upload_local_file(ip_address, FH_ZIP_LOCATION_IP, '/tmp/lithops_standalone.zip')
        logger.debug('Upload zip file to {} - completed'.format(ip_address))
        os.remove(FH_ZIP_LOCATION_IP)
        
        exit()

        # Create files and directories
        cmd = 'systemctl daemon-reload; systemctl stop {}; '.format(PROXY_SERVICE_NAME)
        cmd += 'rm -R {}; mkdir -p {}; '.format(REMOTE_INSTALL_DIR, REMOTE_INSTALL_DIR)
        cmd += 'mkdir -p /tmp/lithops; '.format(REMOTE_INSTALL_DIR, REMOTE_INSTALL_DIR)
        service_file = '/etc/systemd/system/{}'.format(PROXY_SERVICE_NAME)
        cmd += "echo '{}' > {};".format(PROXY_SERVICE_FILE, service_file)
        config_file = os.path.join(REMOTE_INSTALL_DIR, 'config')
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
        cmd += 'touch {}/access.data; '.format(REMOTE_INSTALL_DIR)
        cmd += 'echo "{} {}" > {}/access.data; '.format(backend.get_ip_address(), backend.get_instance_id(), REMOTE_INSTALL_DIR)
        cmd += 'unzip -o /tmp/lithops_standalone.zip -d {} > /dev/null 2>&1; '.format(REMOTE_INSTALL_DIR)
        cmd += 'rm /tmp/lithops_standalone.zip; '

        # Start proxy service
        cmd += 'chmod 644 {}; '.format(service_file)
        cmd += 'systemctl daemon-reload; '
        cmd += 'systemctl stop {}; '.format(PROXY_SERVICE_NAME)
        cmd += 'systemctl enable {}; '.format(PROXY_SERVICE_NAME)
        cmd += 'systemctl start {}; '.format(PROXY_SERVICE_NAME)

        logger.debug('Executing main ssh command for Lithops proxy to VM instance {}'.format(ip_address))
        logger.debug('Be patient, initial installation process can take up to 5 minutes')

        if self.use_http:
            # Execute the command asynchronously, this way we can immediately close the ssh connection
            ssh_client.run_remote_command(ip_address, cmd, run_async=True)
            backend.ssh_client.close()
        else:
            ssh_client.run_remote_command(ip_address, cmd, timeout=300)
            logger.debug('Completed main ssh command for Lithops proxy to VM instance {}'.format(ip_address))
