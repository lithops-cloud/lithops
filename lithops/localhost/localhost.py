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
import logging
import shutil
import subprocess as sp
from shutil import copyfile

from lithops.constants import TEMP, LITHOPS_TEMP_DIR, JOBS_PREFIX,\
    RN_LOG_FILE, LOGS_DIR
from lithops.storage.utils import create_job_key
from lithops.version import __version__

logger = logging.getLogger(__name__)

RUNNER = os.path.join(LITHOPS_TEMP_DIR, 'runner.py')
LITHOPS_LOCATION = os.path.dirname(os.path.abspath(lithops.__file__))


class LocalhostHandler:
    """
    A localhostHandler object is used by invokers and other components to access
    underlying localhost backend without exposing the implementation details.
    """

    def __init__(self, localhost_config):
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.config = localhost_config
        self.runtime = self.config['runtime']

        if self.runtime == 'python3':
            self.env = DefaultEnv()
            self.env_type = 'default'
        else:
            self.env = DockerEnv(self.runtime)
            self.env_type = 'docker'

        log_msg = ('Lithops v{} init for Localhost'.format(__version__))
        if not self.log_active:
            print(log_msg)
        logger.info("Localhost handler created successfully")

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        runtime = job_payload['job_description']['runtime_name']

        job_key = create_job_key(executor_id, job_id)
        log_file = os.path.join(LOGS_DIR, job_key+'.log')
        logger.info("Running job in {}. View execution logs at {}"
                    .format(runtime, log_file))

        if not os.path.isfile(RUNNER):
            self.env.setup()

        exec_command = self.env.get_execution_cmd(runtime)

        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        storage_bucket = job_payload['config']['lithops']['storage_bucket']

        job_dir = os.path.join(LITHOPS_TEMP_DIR, storage_bucket, JOBS_PREFIX)
        os.makedirs(job_dir, exist_ok=True)
        jobr_filename = os.path.join(job_dir, '{}-job.json'.format(job_key))

        with open(jobr_filename, 'w') as jl:
            json.dump(job_payload, jl)

        log_file = open(RN_LOG_FILE, 'a')
        sp.Popen(exec_command+' run '+jobr_filename, shell=True,
                 stdout=log_file, stderr=log_file, universal_newlines=True)

    def create_runtime(self, runtime):
        """
        Extract the runtime metadata and preinstalled modules
        """
        logger.info("Extracting preinstalled Python modules from {}".format(runtime))
        self.env.setup()
        exec_command = self.env.get_execution_cmd(runtime)
        process = sp.run(exec_command+' preinstalls', shell=True, check=True,
                         stdout=sp.PIPE, universal_newlines=True)
        runtime_meta = json.loads(process.stdout.strip())

        return runtime_meta

    def get_runtime_key(self, runtime_name):
        """
        Generate the runtime key that identifies the runtime
        """
        runtime_key = os.path.join('localhost', self.env_type, runtime_name.strip("/"))

        return runtime_key

    def clean(self):
        pass


class DockerEnv:
    def __init__(self, docker_image):
        self.runtime = docker_image

    def setup(self):
        os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
        try:
            shutil.rmtree(os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        except FileNotFoundError:
            pass
        shutil.copytree(LITHOPS_LOCATION, os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        src_handler = os.path.join(LITHOPS_LOCATION, 'localhost', 'runner.py')
        copyfile(src_handler, RUNNER)

    def get_execution_cmd(self, docker_image_name):
        cmd = ('docker pull {} > /dev/null 2>&1; docker run '
               '--user $(id -u):$(id -g) --rm -v {}:/tmp --entrypoint '
               '"python" {} /tmp/lithops/runner.py'
               .format(docker_image_name, TEMP, docker_image_name))
        return cmd


class DefaultEnv:
    def __init__(self):
        self.runtime = sys.executable

    def setup(self):
        os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
        try:
            shutil.rmtree(os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        except FileNotFoundError:
            pass
        shutil.copytree(LITHOPS_LOCATION, os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        src_handler = os.path.join(LITHOPS_LOCATION, 'localhost', 'runner.py')
        copyfile(src_handler, RUNNER)

    def get_execution_cmd(self, runtime):
        cmd = '{} {}'.format(self.runtime, RUNNER)
        return cmd
