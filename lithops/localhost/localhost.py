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
import lithops
import logging
import subprocess
from shutil import copyfile

from lithops.localhost.environments import DefaultEnv, VirtualEnv, DockerEnv
from lithops.config import STORAGE_DIR, JOBS_PREFIX


logger = logging.getLogger(__name__)
LOCAL_HANDLER_NAME = 'local_handler.py'


class LocalhostHandler:
    """
    A localhostHandler object is used by invokers and other components to access
    underlying localhost backend without exposing the implementation details.
    """

    def __init__(self, localhost_config):
        self.config = localhost_config
        self.runtime = self.config['runtime']

        if self.runtime is None:
            self.env = DefaultEnv()
            self.env_type = 'default'
        elif '.zip' in self.runtime:
            self.env = VirtualEnv(self.runtime)
            self.env_type = 'virtualenv'
        else:
            self.env = DockerEnv(self.runtime)
            self.env_type = 'docker'

    def _create_local_handler(self):
        current_location = os.path.dirname(os.path.abspath(lithops.localhost.__file__))
        src_handler = os.path.join(current_location, LOCAL_HANDLER_NAME)
        dst_handler = os.path.join(STORAGE_DIR, LOCAL_HANDLER_NAME)
        copyfile(src_handler, dst_handler)

    def run_job(self, job_payload):
        """
        Run the job description agains the selected environemnt
        """
        self._create_local_handler()
        exec_command = self.env.get_execution_cmd()

        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        storage_bucket = job_payload['config']['lithops']['storage_bucket']

        job_dir = os.path.join(STORAGE_DIR, storage_bucket,
                               JOBS_PREFIX, executor_id, job_id)
        os.makedirs(job_dir, exist_ok=True)
        jobr_filename = os.path.join(job_dir, 'job.json')

        with open(jobr_filename, 'w') as jl:
            json.dump(job_payload, jl)

        handler_file = os.path.join(STORAGE_DIR, LOCAL_HANDLER_NAME)
        log_file = open(os.path.join(STORAGE_DIR, 'local_handler.log'), 'a')
        subprocess.Popen([exec_command, handler_file, 'run', jobr_filename],
                         stdout=log_file, universal_newlines=True)

    def create_runtime(self, runtime_name):
        """
        Extract the runtime metadata and preinstalled modules
        """
        self._create_local_handler()
        exec_command = self.env.get_execution_cmd()
        current_location = os.path.dirname(os.path.abspath(lithops.localhost.__file__))
        handler_file = os.path.join(STORAGE_DIR, LOCAL_HANDLER_NAME)
        process = subprocess.run([exec_command, handler_file, 'modules'], check=True,
                                 stdout=subprocess.PIPE, universal_newlines=True)
        runtime_meta = json.loads(process.stdout.strip())

        return runtime_meta

    def get_runtime_key(self, runtime_name):
        """
        Genereate the runtime key that identifies the runtime
        """
        runtime_key = os.path.join('localhost', self.env_type, runtime_name.strip("/"))

        return runtime_key
