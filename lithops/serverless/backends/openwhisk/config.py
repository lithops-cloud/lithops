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

AVAILABLE_PY_RUNTIMES = {
    '3.6': 'docker.io/lithopscloud/ibmcf-python-v36',
    '3.7': 'docker.io/lithopscloud/ibmcf-python-v37',
    '3.8': 'docker.io/lithopscloud/ibmcf-python-v38',
    '3.9': 'docker.io/lithopscloud/ibmcf-python-v39',
    '3.10': 'docker.io/lithopscloud/ibmcf-python-v310',
    '3.11': 'docker.io/lithopscloud/ibmcf-python-v311'
}

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 300 seconds => 5 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 100,
    'worker_processes': 1,
    'invoke_pool_threads': 500,
    'docker_server': 'docker.io'
}

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_openwhisk.zip')

REQ_PARAMS = ('endpoint', 'namespace', 'api_key')


def load_config(config_data):

    if not config_data['openwhisk']:
        raise Exception("'openwhisk' section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['openwhisk']:
            msg = f"{param} is mandatory under 'openwhisk' section of the configuration"
            raise Exception(msg)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['openwhisk']:
            config_data['openwhisk'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'runtime' in config_data['openwhisk']:
        runtime = config_data['openwhisk']['runtime']
        registry = config_data['openwhisk']['docker_server']
        if runtime.count('/') == 1 and registry not in runtime:
            config_data['openwhisk']['runtime'] = f'{registry}/{runtime}'
