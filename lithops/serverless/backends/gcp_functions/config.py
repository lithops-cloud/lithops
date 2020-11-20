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

RUNTIME_TIMEOUT_DEFAULT = 540  # 540 s == 9 min
RUNTIME_MEMORY_DEFAULT = 256  # 256 MB
RUNTIME_MEMORY_MAX = 2048  # 2048 MB
RUNTIME_MEMORY_OPTIONS = {128, 256, 512, 1024, 2048, 4096}

MAX_CONCURRENT_WORKERS = 1000

RETRIES = 15
RETRY_SLEEP = 45

DEFAULT_RUNTIMES = ['python3.7', 'python3.8']
USER_RUNTIMES_PREFIX = 'lithops.user_runtimes'

DEFAULT_REQUIREMENTS = [
    'numpy',
    'scikit-learn',
    'scipy',
    'pandas',
    'google-cloud',
    'google-cloud-storage',
    'google-cloud-pubsub',
    'certifi',
    'chardet',
    'docutils',
    'httplib2',
    'idna',
    'jmespath',
    'kafka-python',
    'lxml',
    'pika==0.13.0',
    'python-dateutil',
    'redis',
    'requests',
    'simplejson',
    'six',
    'urllib3',
    'virtualenv',
    'PyYAML'
]


def load_config(config_data=None):
    if config_data is None:
        config_data = {}

    if 'runtime_memory' not in config_data['serverless']:
        config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['serverless']:
        config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['serverless']:
        config_data['serverless']['runtime'] = 'python' + \
                                               version_str(sys.version_info)

    if 'workers' not in config_data['lithops']:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS

    if config_data['serverless']['runtime_memory'] not in RUNTIME_MEMORY_OPTIONS:
        raise Exception('{} MB runtime is not available (Only one of {} MB is available)'.format(
            config_data['serverless']['runtime_memory'], RUNTIME_MEMORY_OPTIONS))

    if config_data['serverless']['runtime_memory'] > RUNTIME_MEMORY_MAX:
        config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY_MAX
    if config_data['serverless']['runtime_timeout'] > RUNTIME_TIMEOUT_DEFAULT:
        config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    config_data['gcp']['retries'] = RETRIES
    config_data['gcp']['retry_sleep'] = RETRY_SLEEP

    required_parameters = ('project_name',
                           'service_account',
                           'credentials_path')
    if not set(required_parameters) <= set(config_data['gcp']):
        raise Exception("'project_name', 'service_account' and 'credentials_path' are mandatory under 'gcp' section")

    if not exists(config_data['gcp']['credentials_path']) or not isfile(config_data['gcp']['credentials_path']):
        raise Exception("Path {} must be credentials JSON file.".format(config_data['gcp']['credentials_path']))

    config_data['gcp_functions'] = config_data['gcp'].copy()
    if 'region' not in config_data['gcp_functions']:
        config_data['gcp_functions']['region'] = config_data['pywren']['compute_backend_region']
