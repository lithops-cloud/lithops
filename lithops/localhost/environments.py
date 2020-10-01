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

import sys
import subprocess
from lithops.config import TEMP


class VirtualEnv:
    def __init__(self, virtualenv):
        self.runtime = virtualenv

        # unpakage virtual env

    def get_execution_cmd(self, runtime):
        return self.runtime


class DockerEnv:
    def __init__(self, docker_image):
        self.runtime = docker_image

    def get_execution_cmd(self, docker_image_name):
        p = subprocess.run("id -u $USER", shell=True,
                           check=True, stdout=subprocess.PIPE)
        uid = p.stdout.strip()

        name = self._format_runtime_name(docker_image_name)

        cmd = cmd = ('docker run -d --name {} --user {} -v {}:/tmp'
                     ' --entrypoint "python" {} /tmp/local_handler.py'
                     .format(name, uid, TEMP, 
                             docker_image_name, DOCKER_BASE_FOLDER))

class DefaultEnv:
    def __init__(self):
        self.runtime = sys.executable

    def get_execution_cmd(self, runtime):
        return self.runtime
