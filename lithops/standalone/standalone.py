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
import logging
import importlib
import requests

from lithops.serverless.utils import create_function_handler_zip
from lithops.config import REMOTE_INSTALL_DIR


logger = logging.getLogger(__name__)
FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_standalone.zip')

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


class StandaloneHandler:
    """
    A StandaloneHandler object is used by invokers and other components to access
    underlying standalone backend without exposing the implementation details.
    """

    def __init__(self, standalone_config):
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.config = standalone_config
        self.backend_name = self.config['backend']
        self.runtime = self.config['runtime']

        self.start_timeout = self.config.get('start_timeout', 300)

        self.auto_dismantle = self.config.get('auto_dismantle')
        self.hard_dismantle_timeout = self.config.get('hard_dismantle_timeout')
        self.soft_dismantle_timeout = self.config.get('soft_dismantle_timeout')

        # self.cpu = self.config.get('cpu', 2)
        # self.memory = self.config.get('memory', 4)
        # self.instances = self.config.get('instances', 1)

        try:
            module_location = 'lithops.standalone.backends.{}'.format(self.backend_name)
            sb_module = importlib.import_module(module_location)
            StandaloneBackend = getattr(sb_module, 'StandaloneBackend')
            self.backend = StandaloneBackend(self.config[self.backend_name])

        except Exception as e:
            logger.error("There was an error trying to create the "
                         "{} standalone backend".format(self.backend_name))
            raise e

        self.ssh_credentials = self.backend.get_ssh_credentials()
        self.ip_address = self.backend.get_ip_address()

        from lithops.standalone.utils import SSHClient
        self.ssh_client = SSHClient(self.ssh_credentials)

        logger.debug("Standalone handler created successfully")

    def _is_backend_ready(self):
        """
        Checks if the VM instance is ready to receive ssh connections
        """
        try:
            self.ssh_client.run_remote_command(self.ip_address, 'id', timeout=2)
        except Exception:
            return False
        return True

    def _wait_backend_ready(self):
        """
        Waits until the VM instance is ready to receive ssh connections
        """
        logger.info('Waiting VM instance to become ready')

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_backend_ready():
                return True
            time.sleep(1)

        self.dismantle()
        raise Exception('VM readiness probe expired. Check your VM')

    def _is_proxy_ready(self):
        """
        Checks if the proxy is ready to receive http connections
        """
        try:
            url = "http://{}:{}/ping".format(self.ip_address, PROXY_SERVICE_PORT)
            r = requests.get(url, timeout=1)
            if r.status_code == 200:
                return True
            return False
        except Exception:
            return False

    def _wait_proxy_ready(self):
        """
        Waits until the proxy is ready to receive http connections
        """
        logger.info('Waiting Lithops proxy to become ready')

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_proxy_ready():
                return True
            time.sleep(1)

        self.dismantle()
        raise Exception('Proxy readiness probe expired. Check your VM')

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        if not self._is_proxy_ready():
            # The VM instance is stopped
            init_time = time.time()
            self.backend.start()
            self._wait_proxy_ready()
            total_start_time = round(time.time()-init_time, 2)
            logger.info('VM instance ready in {} seconds'.format(total_start_time))

        logger.info('ExecutorID: {} | JobID: {} - Running job'.
                    format(job_payload['executor_id'], job_payload['job_id']))
        url = "http://{}:{}/run".format(self.ip_address, PROXY_SERVICE_PORT)
        r = requests.post(url, data=json.dumps(job_payload))
        response = r.json()

        return response['activationId']

    def create_runtime(self, runtime):
        """
        Installs the proxy and extracts the runtime metadata and
        preinstalled modules
        """
        if not self._is_backend_ready():
            # The VM instance is stopped
            init_time = time.time()
            self.backend.start()
            self._wait_backend_ready()
            total_start_time = round(time.time()-init_time, 2)
            logger.info('VM instance ready in {} seconds'.format(total_start_time))

        self._setup_proxy()
        self._wait_proxy_ready()

        logger.info('Extracting runtime metadata information')
        payload = {'runtime': runtime}
        url = "http://{}:{}/preinstalls".format(self.ip_address, PROXY_SERVICE_PORT)
        r = requests.get(url, data=json.dumps(payload))
        runtime_meta = r.json()

        return runtime_meta

    def get_runtime_key(self, runtime_name):
        """
        Wrapper method that returns a formated string that represents the runtime key.
        Each backend has its own runtime key format. Used to store modules preinstalls
        into the storage
        """
        return self.backend.get_runtime_key(runtime_name)

    def dismantle(self):
        """
        Stop VM instance
        """
        self.backend.stop()

    def delete_all_runtimes(self):
        pass

    def _setup_proxy(self):
        logger.info('Installing Lithops proxy in the VM instance')
        logger.debug('Be patient, installation process can take up to 3 '
                     'minutes if this is the first time you use the VM instance')

        service_file = '/etc/systemd/system/{}'.format(PROXY_SERVICE_NAME)
        self.ssh_client.upload_data_to_file(self.ip_address, PROXY_SERVICE_FILE, service_file)

        cmd = 'mkdir -p {}; '.format(REMOTE_INSTALL_DIR)
        cmd += 'systemctl daemon-reload; systemctl stop {}; '.format(PROXY_SERVICE_NAME)
        self.ssh_client.run_remote_command(self.ip_address, cmd)

        config_file = os.path.join(REMOTE_INSTALL_DIR, 'config')
        self.ssh_client.upload_data_to_file(self.ip_address, json.dumps(self.config), config_file)

        src_proxy = os.path.join(os.path.dirname(__file__), 'proxy.py')
        create_function_handler_zip(FH_ZIP_LOCATION, src_proxy)
        self.ssh_client.upload_local_file(self.ip_address, FH_ZIP_LOCATION, '/tmp/lithops_standalone.zip')
        os.remove(FH_ZIP_LOCATION)

        cmd = 'apt-get update; apt-get install unzip python3-pip -y; '
        cmd += 'pip3 install flask gevent pika==0.13.1; '
        cmd += 'unzip -o /tmp/lithops_standalone.zip -d {} > /dev/null 2>&1; '.format(REMOTE_INSTALL_DIR)
        cmd += 'rm /tmp/lithops_standalone.zip; '
        cmd += 'chmod 644 {}; '.format(service_file)
        cmd += 'systemctl daemon-reload; '
        cmd += 'systemctl stop {}; '.format(PROXY_SERVICE_NAME)
        cmd += 'systemctl enable {}; '.format(PROXY_SERVICE_NAME)
        cmd += 'systemctl start {}; '.format(PROXY_SERVICE_NAME)
        self.ssh_client.run_remote_command(self.ip_address, cmd, background=True)
