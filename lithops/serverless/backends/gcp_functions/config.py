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
from os.path import exists, isfile
from lithops.utils import version_str


DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 5 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 1000,
    'worker_processes': 1,
    'invoke_pool_threads': 1000,
}

RUNTIME_MEMORY_MAX = 2048  # 2048 MB
RUNTIME_MEMORY_OPTIONS = {128, 256, 512, 1024, 2048, 4096}

RETRIES = 15
RETRY_SLEEP = 45

DEFAULT_RUNTIMES = ['python3.7', 'python3.8']
USER_RUNTIMES_PREFIX = 'lithops.user_runtimes'

REQ_PARAMS = ('project_name', 'service_account', 'credentials_path', 'region')

DEFAULT_REQUIREMENTS = [
    'numpy',
    'scipy',
    'scikit-learn',
    'pandas',
    'google-cloud',
    'google-cloud-storage',
    'google-cloud-pubsub',
    'google-auth',
    'certifi',
    'chardet',
    'docutils',
    'httplib2',
    'idna',
    'jmespath',
    'kafka-python',
    'lxml',
    'pika',
    'redis',
    'requests',
    'six',
    'urllib3',
    'virtualenv',
    'PyYAML',
    'cloudpickle',
    'ps-mem',
    'tblib'
]


def load_config(config_data=None):
    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['gcp']:
            msg = "{} is mandatory under 'gcp' section of the configuration".format(REQ_PARAMS)
            raise Exception(msg)

    if not exists(config_data['gcp']['credentials_path']) or not isfile(config_data['gcp']['credentials_path']):
        raise Exception("Path {} must be credentials JSON file.".format(config_data['gcp']['credentials_path']))

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['gcp_functions']:
            config_data['gcp_functions'][key] = DEFAULT_CONFIG_KEYS[key]

    config_data['gcp_functions']['invoke_pool_threads'] = config_data['gcp_functions']['max_workers']

    if 'runtime' not in config_data['gcp_functions']:
        config_data['gcp_functions']['runtime'] = 'python' + version_str(sys.version_info)

    if config_data['gcp_functions']['runtime_memory'] not in RUNTIME_MEMORY_OPTIONS:
        raise Exception('{} MB runtime is not available (Only one of {} MB is available)'.format(
            config_data['gcp_functions']['runtime_memory'], RUNTIME_MEMORY_OPTIONS))

    if config_data['gcp_functions']['runtime_memory'] > RUNTIME_MEMORY_MAX:
        config_data['gcp_functions']['runtime_memory'] = RUNTIME_MEMORY_MAX

    config_data['gcp']['retries'] = RETRIES
    config_data['gcp']['retry_sleep'] = RETRY_SLEEP

    required_parameters = ('project_name',
                           'service_account',
                           'credentials_path')
    if not set(required_parameters) <= set(config_data['gcp']):
        raise Exception("'project_name', 'service_account' and 'credentials_path' are mandatory under 'gcp' section")

    config_data['gcp_functions'].update(config_data['gcp'])
