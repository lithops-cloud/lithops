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
import shlex
from concurrent.futures import ThreadPoolExecutor

from lithops.utils import is_lithops_worker, create_handler_zip
from lithops.constants import REMOTE_INSTALL_DIR


logger = logging.getLogger(__name__)
LOCAL_FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_standalone.zip')
PROXY_SERVICE_PORT = 8080


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
        StandaloneBackend = getattr(sb_module, 'StandaloneBackend')
        self.backend = StandaloneBackend(self.config[self.backend_name])
        self.backend.init()
        self.backend.create_instance(master=True)

        self.exec_mode = self.config.get('exec_mode', 'consume')
        logger.debug("Standalone handler created successfully")

    def _is_instance_ready(self, instance):
        """
        Checks if the VM instance is ready to receive ssh connections
        """
        try:
            instance.get_ssh_client().run_remote_command('id')
        except Exception as e:
            print(e)
            return False
        return True

    def _wait_instance_ready(self, instance):
        """
        Waits until the VM instance is ready to receive ssh connections
        """
        ip_addr = instance.get_ip_address()
        logger.debug('Waiting master VM instance {} to become ready'.format(ip_addr))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_instance_ready(instance):
                logger.debug('Master VM instance {} ready in {}'.format(ip_addr, round(time.time()-start, 2)))
                return True
            time.sleep(5)

        self.dismantle()
        raise Exception('VM readiness {} probe expired. Check your master VM'.format(ip_addr))

    def _is_proxy_ready(self, instance):
        """
        Checks if the proxy is ready to receive http connections
        """
        try:
            if self.is_lithops_worker:
                url = "http://{}:{}/ping".format('127.0.0.1', PROXY_SERVICE_PORT)
                r = requests.get(url, timeout=1, verify=True)
                if r.status_code == 200:
                    return True
                return False
            else:
                cmd = 'curl -X GET http://127.0.0.1:8080/ping'
                out = instance.get_ssh_client().run_remote_command(cmd)
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
        logger.info('Waiting Lithops proxy to become ready on {}'.format(ip_address))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_proxy_ready(instance):
                return True
            time.sleep(2)

        self.dismantle()
        raise Exception('Proxy readiness probe expired on {}. Check your VM'.format(ip_address))

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        master_ip = self.backend.master.get_ip_address()
        total_calls = job_payload['job_description']['total_calls']

        if self.exec_mode == 'create':
            for vm_n in range(total_calls): 
                self.backend.create_instance()

            instances = self.backend.get_instances()
            with ThreadPoolExecutor(len(instances)) as executor:
                executor.map(lambda vm: vm.create(start=True), instances)

        logger.debug("Checking if Master VM instance {} is ready".format(master_ip))
        if not self._is_proxy_ready(self.backend.master):
            logger.debug("Master VM instance {} is not ready".format(master_ip))
            self.backend.master.start()
            # Wait only for the entry point instance
            self._wait_instance_ready(self.backend.master)
            if self.exec_mode == 'create':
                self._setup_lithops(self.backend.master)

        logger.debug('Master VM instance {} ready. Running job'.format(master_ip))
        cmd = 'python3 /opt/lithops/invoker.py {}'.format(shlex.quote(json.dumps(job_payload)))
        self.backend.master.get_ssh_client().run_remote_command(cmd)
        logger.debug('Job invoked on {}'.format(master_ip))

    def create_runtime(self, runtime):
        """
        Installs the proxy and extracts the runtime metadata and
        preinstalled modules
        """
        master_ip = self.backend.master.get_ip_address()

        logger.debug('Checking if  VM instance {} is ready'.format(master_ip))
        if not self._is_instance_ready(self.backend.master):
            logger.debug('Master VM instance {} not ready'.format(master_ip))
            self.backend.master.create(check_if_exists=True, start=True)
            self._wait_instance_ready(self.backend.master)

        self._setup_lithops(self.backend.master)
        self._wait_proxy_ready(self.backend.master)

        logger.debug('Extracting runtime metadata information')
        payload = {'runtime': runtime, 'pull_runtime': self.pull_runtime}
        cmd = ('curl http://127.0.0.1:8080/preinstalls -d {} '
               '-H \'Content-Type: application/json\' -X GET'
               .format(shlex.quote(json.dumps(payload))))
        out = self.backend.master.get_ssh_client().run_remote_command(cmd)
        runtime_meta = json.loads(out)

        return runtime_meta

    def dismantle(self):
        """
        Stop all VM instances
        """
        self.backend.dismantle()

    def clean(self):
        """
        Clan all the backend resources
        """
        self.backend.clean()

    def clear(self):
        """
        Clear all the backend resources
        """
        self.backend.clear()

    def get_runtime_key(self, runtime_name):
        """
        Wrapper method that returns a formated string that represents the
        runtime key. Each backend has its own runtime key format. Used to
        store modules preinstalls into the storage
        """
        return self.backend.get_runtime_key(runtime_name)

    def _setup_lithops(self, instance):
        """
        Setup lithops necessary files and dirs in all VSIs using the entry point instance
        """
        ip_address = instance.get_ip_address()
        logger.debug('Installing Lithops trough VM instance {}'.format(ip_address))
        ssh_client = instance.get_ssh_client()

        # Upload local lithops version to remote VM instance
        src_proxy = os.path.join(os.path.dirname(__file__), 'proxy.py')
        create_handler_zip(LOCAL_FH_ZIP_LOCATION, src_proxy)
        current_location = os.path.dirname(os.path.abspath(__file__))
        ssh_location = os.path.join(current_location, '..', 'util', 'ssh_client.py')
        setup_location = os.path.join(current_location, 'setup.py')

        logger.debug('Uploading lithops files to VM instance {}'.format(ip_address))
        files_to_upload = [(LOCAL_FH_ZIP_LOCATION, '/tmp/lithops_standalone.zip'),
                           (ssh_location, '/tmp/ssh_client.py'.format(REMOTE_INSTALL_DIR)),
                           (setup_location, '/tmp/setup.py'.format(REMOTE_INSTALL_DIR))]

        ssh_client.upload_multiple_local_files(files_to_upload)
        os.remove(LOCAL_FH_ZIP_LOCATION)

        # Create dirs and upload config
        cmd = 'rm -R {0}; mkdir -p {0}; mkdir -p /tmp/lithops; '.format(REMOTE_INSTALL_DIR)
        ep_vsi_data = {'ip_address': ip_address, 'instance_id': instance.get_instance_id()}
        cmd += "echo '{}' > {}/access.data; ".format(json.dumps(ep_vsi_data), REMOTE_INSTALL_DIR)
        cmd += "echo '{}' > {}/config; ".format(json.dumps(self.config), REMOTE_INSTALL_DIR)
        cmd += "mv /tmp/*.py '{}'; ".format(REMOTE_INSTALL_DIR)
        cmd += "apt-get install python3-paramiko -y >> /tmp/lithops/proxy.log 2>&1; ".format(REMOTE_INSTALL_DIR)
        # Run setup script
        cmd += 'python3 {}/setup.py; >> /tmp/lithops/proxy.log 2>&1; '.format(REMOTE_INSTALL_DIR)
        cmd += 'cp {0}/lithops/standalone/invoker.py {0}/invoker.py; '.format(REMOTE_INSTALL_DIR)

        logger.debug('Executing lithops installation process trough VM instance {}'.format(ip_address))
        logger.debug('Be patient, initial installation process may take up to 5 minutes')
        ssh_client.run_remote_command(cmd)
        logger.debug('Lithops installation process completed')
