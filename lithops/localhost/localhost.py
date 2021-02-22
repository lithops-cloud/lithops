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
import json
import lithops
import logging
import shutil
import subprocess as sp
from shutil import copyfile

from lithops.constants import TEMP, LITHOPS_TEMP_DIR, JOBS_PREFIX,\
    RN_LOG_FILE, COMPUTE_CLI_MSG
from lithops.utils import is_unix_system

logger = logging.getLogger(__name__)

RUNNER = os.path.join(LITHOPS_TEMP_DIR, 'runner.py')
LITHOPS_LOCATION = os.path.dirname(os.path.abspath(lithops.__file__))


class LocalhostHandler:
    """
    A localhostHandler object is used by invokers and other components to access
    underlying localhost backend without exposing the implementation details.
    """

    def __init__(self, localhost_config):
        logger.info('Creating Localhost compute client')
        self.config = localhost_config
        self.runtime = self.config['runtime']

        if '/' not in self.runtime:
            self.env = DefaultEnv()
            self.env_type = 'default'
        else:
            pull_runtime = self.config.get('pull_runtime', False)
            self.env = DockerEnv(self.runtime, pull_runtime)
            self.env_type = 'docker'

        msg = COMPUTE_CLI_MSG.format('Localhost compute')
        logger.info("{}".format(msg))

    def init(self):
        """
        Init taks for localhost
        """
        pass

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        job_key = job_payload['job_key']
        runtime = job_payload['runtime_name']
        storage_bucket = job_payload['config']['lithops']['storage_bucket']
        total_calls = len(job_payload['call_ids'])

        logger.debug('ExecutorID {} | JobID {} - Going '
                     'to run {} activations in localhost'
                     .format(executor_id, job_id, total_calls))

        if not os.path.isfile(RUNNER):
            self.env.setup(runtime)

        local_job_dir = os.path.join(LITHOPS_TEMP_DIR, storage_bucket, JOBS_PREFIX)
        docker_job_dir = '/tmp/lithops/{}/{}'.format(storage_bucket, JOBS_PREFIX)
        job_file = '{}-job.json'.format(job_key)

        os.makedirs(local_job_dir, exist_ok=True)
        local_job_filename = os.path.join(local_job_dir, job_file)

        with open(local_job_filename, 'w') as jl:
            json.dump(job_payload, jl, default=str)

        if self.env_type == 'docker':
            job_filename = '{}/{}'.format(docker_job_dir, job_file)
        else:
            job_filename = local_job_filename

        exec_command = self.env.get_execution_cmd(runtime)
        logger.debug('cmd: '+exec_command+' run '+job_filename)
        with open(RN_LOG_FILE, 'a') as log_file:
            sp.Popen(exec_command+' run '+job_filename, shell=True,
                     stdout=log_file, stderr=log_file, universal_newlines=True)

    def create_runtime(self, runtime):
        """
        Extract the runtime metadata and preinstalled modules
        """
        logger.info("Extracting preinstalled Python modules from {}".format(runtime))
        self.env.setup(runtime)
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

    def clear(self):
        pass


class DockerEnv:
    def __init__(self, docker_image, pull_runtime):
        logger.info('Setting DockerEnv for {}'.format(docker_image, pull_runtime))
        self.runtime = docker_image
        self.pull_runtime = pull_runtime

    def setup(self, runtime):
        os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
        try:
            shutil.rmtree(os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        except FileNotFoundError:
            pass
        shutil.copytree(LITHOPS_LOCATION, os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        src_handler = os.path.join(LITHOPS_LOCATION, 'localhost', 'runner.py')
        copyfile(src_handler, RUNNER)
        if self.pull_runtime:
            logger.info('Pulling Docker runtime {}'.format(self.runtime))
            sp.run('docker pull {}'.format(self.runtime), shell=True, check=True,
                   stdout=sp.PIPE, universal_newlines=True)

    def get_execution_cmd(self, runtime):
        if is_unix_system():
            cmd = ('docker run --user $(id -u):$(id -g) --rm -v {}:/tmp --entrypoint '
                   '"python3" {} /tmp/lithops/runner.py'.format(TEMP, self.runtime))
        else:
            cmd = ('docker run --rm -v {}:/tmp --entrypoint "python3" {} '
                   '/tmp/lithops/runner.py'.format(TEMP, self.runtime))
        return cmd


class DefaultEnv:
    def __init__(self):
        self.runtime = sys.executable
        logger.info('Setting DefaultEnv for {}'.format(self.runtime))

    def setup(self, runtime):
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
