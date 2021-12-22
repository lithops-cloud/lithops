#
# (C) Copyright IBM Corp. 2020
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
import shutil
from lithops.utils import version_str

DOCKER_PATH = shutil.which('docker')

RUNTIME_DEFAULT = {
    '3.5': 'lithopscloud/ibmcf-python-v35',
    '3.6': 'lithopscloud/ibmcf-python-v36',
    '3.7': 'lithopscloud/ibmcf-python-v37',
    '3.8': 'lithopscloud/ibmcf-python-v38',
    '3.9': 'lithopscloud/ibmcf-python-v39',
    '3.10': 'lithopscloud/ibmcf-python-v310'
}

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 600 seconds => 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 100,
    'worker_processes': 1,
    'invoke_pool_threads': 500,
}

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_openwhisk.zip')

REQ_PARAMS = ('endpoint', 'namespace', 'api_key')


def load_config(config_data):

    for param in REQ_PARAMS:
        if param not in config_data['openwhisk']:
            msg = "{} is mandatory in 'openwhisk' section of the configuration".format(REQ_PARAMS)
            raise Exception(msg)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['openwhisk']:
            config_data['openwhisk'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'runtime' not in config_data['openwhisk']:
        python_version = version_str(sys.version_info)
        try:
            config_data['openwhisk']['runtime'] = RUNTIME_DEFAULT[python_version]
        except KeyError:
            raise Exception('Unsupported Python version: {}'.format(python_version))
