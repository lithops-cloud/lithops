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
import re
import sys
from enum import Enum


DEFAULT_CONFIG_KEYS = {
    'runtime': os.path.basename(sys.executable),
    'worker_processes': os.cpu_count(),
}

LOCALHOST_EXECUTION_TIMEOUT = 3600


class LocvalhostEnvironment(Enum):
    DEFAULT = "default"
    CONTAINER = "container"


def get_environment(runtime_name):

    windows_path_pattern = re.compile(r'^[A-Za-z]:\\.*$')
    if runtime_name.startswith(('python', '/')) \
       or windows_path_pattern.match(runtime_name) is not None:
        environment = LocvalhostEnvironment.DEFAULT
    else:
        environment = LocvalhostEnvironment.CONTAINER

    return environment


def load_config(config_data):

    if 'localhost' not in config_data or not config_data['localhost']:
        config_data['localhost'] = {}

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['localhost']:
            config_data['localhost'][key] = DEFAULT_CONFIG_KEYS[key]

    config_data['localhost']['max_workers'] = 1

    if 'execution_timeout' not in config_data['lithops']:
        config_data['lithops']['execution_timeout'] = LOCALHOST_EXECUTION_TIMEOUT

    if 'storage' not in config_data['lithops']:
        config_data['lithops']['storage'] = 'localhost'
