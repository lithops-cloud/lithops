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
from lithops import config as lithops_config

RUNTIME_TIMEOUT_DEFAULT = 540  # 540 s == 9 min
RUNTIME_MEMORY_DEFAULT = 256  # 256 MB
RUNTIME_MEMORY_MAX = 2048  # 2048 MB
RUNTIME_MEMORY_OPTIONS = {128, 256, 1024, 2048}

MAX_CONCURRENT_WORKERS = 1000

RETRIES = 15
RETRY_SLEEPS = [1, 2, 5, 10, 30]


def load_config(config_data=None):
    if config_data is None:
        config_data = {}

    if 'runtime_memory' not in config_data['lithops']:
        config_data['lithops']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['lithops']:
        config_data['lithops']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['lithops']:
        config_data['lithops']['runtime'] = 'python' + \
            version_str(sys.version_info)
    if 'workers' not in config_data['lithops']:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS

    if config_data['lithops']['runtime_memory'] not in RUNTIME_MEMORY_OPTIONS:
        raise Exception('{} MB runtime is not available (Only {} MB)'.format(
            config_data['lithops']['runtime_memory'], RUNTIME_MEMORY_OPTIONS))

    if config_data['lithops']['runtime_memory'] > RUNTIME_MEMORY_MAX:
        config_data['lithops']['runtime_memory'] = RUNTIME_MEMORY_MAX
    if config_data['lithops']['runtime_timeout'] > RUNTIME_TIMEOUT_DEFAULT:
        config_data['lithops']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    config_data['gcp']['retries'] = RETRIES
    config_data['gcp']['retry_sleeps'] = RETRY_SLEEPS

    # Put storage data into compute backend config dict entry
    storage_config = dict()
    storage_config['lithops'] = config_data['lithops'].copy()
    storage_config['gcp_storage'] = config_data['gcp'].copy()
    config_data['gcp']['storage'] = lithops_config.extract_storage_config(storage_config)

    required_parameters_0 = ('project_name',
                             'service_account',
                             'credentials_path')
    if not set(required_parameters_0) <= set(config_data['gcp']):
        raise Exception("'project_name', 'service_account' and 'credentials_path' \
        are mandatory under 'gcp' section")

    if not exists(config_data['gcp']['credentials_path']) or not isfile(config_data['gcp']['credentials_path']):
        raise Exception("Path {} must be credentials JSON file.".format(
            config_data['gcp']['credentials_path']))

    config_data['gcp_functions'] = config_data['gcp'].copy()
    if 'region' not in config_data['gcp_functions']:
        config_data['gcp_functions']['region'] = config_data['pywren']['compute_backend_region']
