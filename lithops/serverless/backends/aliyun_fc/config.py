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

import copy
import os
from lithops.constants import TEMP_DIR


DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 5 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 300,
    'worker_processes': 1,
    'invoke_pool_threads': 64,
}

CONNECTION_POOL_SIZE = 300

SERVICE_NAME = 'lithops'
BUILD_DIR = os.path.join(TEMP_DIR, 'AliyunRuntimeBuild')

AVAILABLE_PY_RUNTIMES = {
    '3.6': 'python3',
    '3.9': 'python3.9',
    '3.10': 'python3.10'
}

REQUIREMENTS_FILE = """
pika
tblib
cloudpickle
ps-mem
"""

REQ_PARAMS_1 = ('account_id', 'access_key_id', 'access_key_secret')
REQ_PARAMS_2 = ('role_arn', )

ENDPOINT = "{0}.{1}.fc.aliyuncs.com"


def load_config(config_data=None):

    if 'aliyun' not in config_data:
        raise Exception("'aliyun' section is mandatory in the configuration")

    if not config_data['aliyun_fc']:
        raise Exception("'aliyun_fc' section is mandatory in the configuration")

    for param in REQ_PARAMS_1:
        if param not in config_data['aliyun']:
            msg = f'"{param}" is mandatory in the "aliyun" section of the configuration'
            raise Exception(msg)

    for param in REQ_PARAMS_2:
        if param not in config_data['aliyun_fc']:
            msg = f'"{param}" is mandatory in the "aliyun_fc" section of the configuration'
            raise Exception(msg)

    temp = copy.deepcopy(config_data['aliyun_fc'])
    config_data['aliyun_fc'].update(config_data['aliyun'])
    config_data['aliyun_fc'].update(temp)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['aliyun_fc']:
            config_data['aliyun_fc'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'region' not in config_data['aliyun_fc']:
        raise Exception('"region" is mandatory under the "aliyun_fc" or "aliyun" section of the configuration')
    elif 'region' not in config_data['aliyun']:
        config_data['aliyun']['region'] = config_data['aliyun_fc']['region']

    account_id = config_data['aliyun_fc']['account_id']
    region = config_data['aliyun_fc']['region']
    config_data['aliyun_fc']['public_endpoint'] = ENDPOINT.format(account_id, region)
