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
import sys
import json
import lithops
import time
import logging
import shutil
import importlib
import subprocess
from shutil import copyfile

from lithops.config import TEMP, STORAGE_DIR, JOBS_PREFIX
from lithops.utils import ssh_run_remote_command, ssh_upload_local_file, ssh_upload_data_to_file
from lithops.serverless.utils import create_function_handler_zip

logger = logging.getLogger(__name__)
LOCAL_HANDLER_NAME = 'local_handler.py'
HANDLER_FILE = os.path.join(STORAGE_DIR, LOCAL_HANDLER_NAME)
LITHOPS_LOCATION = os.path.dirname(os.path.abspath(lithops.__file__))
FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_standalone.zip')
REMOTE_TMP_DIR = '~/lithops-data'
LOG_FILE = os.path.join(STORAGE_DIR, 'local_handler.log')


class StandaloneHandler:
    """
    A StandaloneHandler object is used by invokers and other components to access
    underlying standalone backend without exposing the implementation details.
    """

    def __init__(self, standalone_config):
        self.config = standalone_config
        self.backend_name = self.config['backend']
        self.runtime = self.config['runtime']

        self.cpu = self.config.get('cpu', 2)
        self.memory = self.config.get('memory', 4)
        self.instances = self.config.get('instances', 1)
        self.self_start_timeout = self.config.get('start_timeout', 300)

        self.auto_dismantle = self.config['auto_dismantle']
        self.hard_dismantle_timeout = self.config['hard_dismantle_timeout']
        self.soft_dismantle_timeout = self.config['soft_dismantle_timeout']

        try:
            module_location = 'lithops.standalone.backends.{}'.format(self.backend_name)
            sb_module = importlib.import_module(module_location)
            StandaloneBackend = getattr(sb_module, 'StandaloneBackend')
            self.backend = StandaloneBackend(self.config[self.backend_name])

        except Exception as e:
            logger.error("There was an error trying to create the {} standalone backend".format(self.backend_name))
            raise e

        self.ssh_credentials = self.backend.get_ssh_credentials()
        self.ip_address = self.backend.get_ip_address()

        if self.runtime is None:
            self.env = DefaultEnv(self.ssh_credentials)
            self.env_type = 'default'
        else:
            self.env = DockerEnv(self.ssh_credentials, self.runtime)
            self.env_type = 'docker'

    def _is_backend_ready(self):
        """
        Checks if the VM instance is ready to receive ssh connections
        """
        #try:
        #    cmd = 'nc -vzw 2 {} 22'.format(self.ip_address)
        #    subprocess.run(cmd, shell=True, check=True,
        #                   stdout=subprocess.DEVNULL,
        #                   stderr=subprocess.DEVNULL)
        #    return True
        #except Exception:
        #    False

        try:
            ssh_run_remote_command(self.ip_address,
                                   self.ssh_credentials,
                                   'id', timeout=2)
        except Exception:
            return False
        return True

    def _wait_backend_ready(self):
        """
        Waits until the VM instance is ready to receive ssh connections
        """
        logger.info('Waiting VM instance to become ready')
        # cmd = 'until nc -vzw 2 {} 22; do sleep 1; done;'.format(self.ip_address)
        # subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        start = time.time()
        while(time.time() - start < self.self_start_timeout):
            if self._is_backend_ready():
                return True
            time.sleep(1)

        raise Exception('VM readiness probe expired. Check your VM')

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        init_time = time.time()
        if not self._is_backend_ready():
            self.backend.start()
            self._wait_backend_ready()
            total_start_time = round(time.time()-init_time, 2)
            logger.info('VM instance ready in {} seconds'.format(total_start_time))

        runtime = job_payload['job_description']['runtime_name']
        exec_command = self.env.get_execution_cmd(runtime)

        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        storage_bucket = job_payload['config']['lithops']['storage_bucket']

        job_dir = os.path.join(STORAGE_DIR, storage_bucket,
                               JOBS_PREFIX, executor_id, job_id)
        dst_job = os.path.join(job_dir, 'job.json')

        cmd = 'rm -r {} > /dev/null 2>&1; '.format(STORAGE_DIR)
        cmd += 'ln -s {} {} > /dev/null 2>&1 '.format(REMOTE_TMP_DIR, STORAGE_DIR)
        cmd += '&& mkdir -p {}'.format(job_dir)
        ssh_run_remote_command(self.ip_address, self.ssh_credentials, cmd)

        ssh_upload_data_to_file(self.ip_address, self.ssh_credentials,
                                json.dumps(job_payload), dst_job)
        cmd = exec_command+' run '+dst_job+' >> {} &'.format(LOG_FILE)
        ssh_run_remote_command(self.ip_address, self.ssh_credentials, cmd)

    def create_runtime(self, runtime):
        """
        Extract the runtime metadata and preinstalled modules
        """
        ip_address = self.backend.start()
        self._wait_backend_ready(ip_address)

        self.env.setup(ip_address)
        exec_command = self.env.get_execution_cmd(runtime)
        runtime_meta = ssh_run_remote_command(ip_address, self.ssh_credentials,
                                              exec_command+' modules')
        return json.loads(runtime_meta)

    def get_runtime_key(self, runtime_name):
        """
        Generate the runtime key that identifies the runtime
        """
        runtime_key = os.path.join('standalone', self.backend_name,
                                   self.env_type, runtime_name.strip("/"))

        return runtime_key


class DockerEnv:
    def __init__(self, ssh_credentials, docker_image):
        self.ssh_credentials = ssh_credentials
        self.runtime = docker_image

    def setup(self, public_ip):
        os.makedirs(STORAGE_DIR, exist_ok=True)
        shutil.copytree(LITHOPS_LOCATION, os.path.join(STORAGE_DIR, 'lithops'))
        src_handler = os.path.join(LITHOPS_LOCATION, 'localhost', LOCAL_HANDLER_NAME)
        copyfile(src_handler, HANDLER_FILE)

    def get_execution_cmd(self, docker_image_name):
        cmd = ('docker run --user $(id -u):$(id -g) --rm -v {}:/tmp --entrypoint "python"'
               ' {} {}'.format(TEMP, docker_image_name, HANDLER_FILE))
        return cmd


class DefaultEnv:
    def __init__(self, ssh_credentials):
        self.ssh_credentials = ssh_credentials
        self.runtime = sys.executable

    def setup(self, ip_address):
        create_function_handler_zip(FH_ZIP_LOCATION, 'local_handler.py', __file__)
        ssh_upload_local_file(ip_address, self.ssh_credentials,
                              FH_ZIP_LOCATION, '/tmp/lithops_standalone.zip')

        cmd = 'apt-get update && apt-get install unzip python3-pip -y '
        cmd += '&& pip3 install -U lithops '
        cmd += '&& rm -R -f {} '.format(REMOTE_TMP_DIR)
        cmd += '&& mkdir -p {} '.format(REMOTE_TMP_DIR)
        cmd += '&& unzip /tmp/lithops_standalone.zip -d {} '.format(REMOTE_TMP_DIR)
        cmd += '&& rm /tmp/lithops_standalone.zip'
        ssh_run_remote_command(ip_address, self.ssh_credentials, cmd)

    def get_execution_cmd(self, runtime):
        cmd = '{} {}'.format('python3', HANDLER_FILE)
        return cmd
