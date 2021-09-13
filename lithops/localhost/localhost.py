#
# (C) Copyright Cloudlab URV 2020
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
import time
import lithops
import logging
import shutil
import subprocess as sp
import requests
import atexit
from shutil import copyfile

from lithops.constants import TEMP, LITHOPS_TEMP_DIR, COMPUTE_CLI_MSG
from lithops.utils import is_unix_system

logger = logging.getLogger(__name__)

RUNNER = os.path.join(LITHOPS_TEMP_DIR, 'runner.py')
LITHOPS_LOCATION = os.path.dirname(os.path.abspath(lithops.__file__))


RUNNER_PORT = 51563


class LocalhostHandler:
    """
    A localhostHandler object is used by invokers and other components to access
    underlying localhost backend without exposing the implementation details.
    """

    def __init__(self, localhost_config):
        logger.debug('Creating Localhost compute client')
        self.config = localhost_config
        self.runtime = self.config['runtime']

        if '/' not in self.runtime:
            self.env = DefaultEnv()
            self.env_type = 'default'
        else:
            pull_runtime = self.config.get('pull_runtime', False)
            self.env = DockerEnv(self.runtime, pull_runtime)
            self.env_type = 'docker'

        self.jobs = {}  # dict to store executed jobs (job_keys) and PIDs

        atexit.register(self.env.stop)

        msg = COMPUTE_CLI_MSG.format('Localhost compute')
        logger.info("{}".format(msg))

    def init(self):
        """
        Init tasks for localhost
        """
        self.env.setup()

    def create_runtime(self, runtime_name, *args):
        """
        Extract the runtime metadata and preinstalled modules
        """
        logger.info(f"Extracting preinstalled Python modules from {runtime_name}")

        if not self.env.is_started():
            self.env.start()

        service_address = self.env.get_address()

        r = requests.get(f'{service_address}/preinstalls')
        assert r.status_code == 200, 'Failed to get preinstalled modules'
        runtime_metadata = r.json()

        return runtime_metadata

    def invoke(self, job_payload):
        """
        Run the job description against the selected environment
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        total_calls = len(job_payload['call_ids'])

        logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Going to '
                     f'run {total_calls} activations in the localhost worker')

        if not self.env.is_started():
            self.env.start()

        service_address = self.env.get_address()
        r = requests.post(f'{service_address}/submit', json=job_payload)
        assert r.status_code == 202, 'Failed to submit the job'

    def get_runtime_key(self, runtime_name, *args):
        """
        Generate the runtime key that identifies the runtime
        """
        runtime_key = os.path.join('localhost', self.env_type, runtime_name.strip("/"))

        return runtime_key

    def get_backend_type(self):
        """
        Wrapper method that returns the type of the backend (Batch or FaaS)
        """
        return 'batch'

    def clean(self):
        """
        Deletes all local runtimes
        """
        pass

    def clear(self, job_keys=None):
        """
        Kills all running jobs processes
        """
        service_address = self.env.get_address()
        r = requests.post(f'{service_address}/clear')
        assert r.status_code == 204, 'Failed to clear the jobs'


class BaseEnv():
    """
    Base environment class for shared methods
    """
    def is_started(self):
        if not self.runner_service:
            return False

        try:
            r = requests.get(f'{self.address}/ping')
            is_started = True if r.status_code == 200 else False
        except Exception:
            is_started = False

        return is_started

    def _copy_lithops_to_tmp(self):
        os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
        try:
            shutil.rmtree(os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        except FileNotFoundError:
            pass
        shutil.copytree(LITHOPS_LOCATION, os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        src_handler = os.path.join(LITHOPS_LOCATION, 'localhost', 'runner.py')
        copyfile(src_handler, RUNNER)

    def restart(self):
        self.stop()
        time.sleep(1)
        self.start()

    def stop(self):
        if self.runner_service:
            requests.post(f'{self.address}/shutdown')

    def get_address(self):
        return self.address


class DockerEnv(BaseEnv):
    """
    Docker environment uses a docker runtime image
    """
    def __init__(self, docker_image, pull_runtime):
        logger.debug(f'Setting DockerEnv for {docker_image}')
        self.runtime = docker_image
        self.pull_runtime = pull_runtime
        self.runner_service = None

    def setup(self):
        self._copy_lithops_to_tmp()
        if self.pull_runtime:
            logger.debug('Pulling Docker runtime {}'.format(self.runtime))
            sp.run('docker pull {}'.format(self.runtime), shell=True, check=True,
                   stdout=sp.PIPE, universal_newlines=True)

    def start(self):
        logger.debug(f'Starting runtime {self.runtime}')
        cmd = 'docker run -d '

        if is_unix_system():
            cmd += '--user $(id -u):$(id -g) '

        cmd += (f'--rm -v {TEMP}:/tmp -p {RUNNER_PORT}:8085 '
                f'--entrypoint "python3" {self.runtime} /tmp/lithops/runner.py 8085')

        self.runner_service = sp.run(cmd, shell=True, check=True, stdout=sp.DEVNULL)
        self.address = f'http://127.0.0.1:{RUNNER_PORT}'
        while True:
            try:
                r = requests.get(f'{self.address}/ping')
                if r.status_code == 200:
                    return
            except Exception:
                time.sleep(0.1)


class DefaultEnv(BaseEnv):
    """
    Default environment uses current python3 installation
    """
    def __init__(self):
        self.runtime = sys.executable
        logger.debug(f'Setting DefaultEnv for {self.runtime}')
        self.runner_service = None

    def setup(self):
        self._copy_lithops_to_tmp()

    def start(self):
        logger.debug(f'Starting runtime {self.runtime}')
        cmd = f'"{self.runtime}" "{RUNNER}" {RUNNER_PORT} &'
        self.runner_service = sp.run(cmd, shell=True)
        self.address = f'http://127.0.0.1:{RUNNER_PORT}'
        while True:
            try:
                r = requests.get(f'{self.address}/ping')
                if r.status_code == 200:
                    return
            except Exception:
                pass
