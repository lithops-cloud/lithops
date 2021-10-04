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
import os
from lithops.utils import version_str


DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 5 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 300,
    'worker_processes': 1,
    'invoke_pool_threads': 300,
}

CONNECTION_POOL_SIZE = 300

SERVICE_NAME = 'lithops'
RUNTIME_DEFAULT = 'python3'
HANDLER_FOLDER_LOCATION = os.path.join(os.getcwd(), 'lithops_handler_aliyun')

REQUIREMENTS_FILE = """
pika
tblib
cloudpickle
ps-mem
"""

REQ_PARAMS_1 = ('access_key_id', 'access_key_secret')
REQ_PARAMS_2 = ('public_endpoint', 'role_arn')


def load_config(config_data=None):

    if 'aliyun' not in config_data:
        raise Exception("'aliyun' section is mandatory in the configuration")

    if 'aliyun_fc' not in config_data:
        raise Exception("'aliyun_fc' section is mandatory in the configuration")

    for param in REQ_PARAMS_1:
        if param not in config_data['aliyun']:
            msg = f'"{param}" is mandatory in the "aliyun" section of the configuration'
            raise Exception(msg)

    for param in REQ_PARAMS_2:
        if param not in config_data['aliyun_fc']:
            msg = f'"{param}" is mandatory in the "aliyun_fc" section of the configuration'
            raise Exception(msg)

    this_version_str = version_str(sys.version_info)
    if this_version_str != '3.6':
        raise Exception('The functions backend Aliyun Function Compute currently'
                        ' only supports Python version 3.6 and the local Python'
                        'version is {}'.format(this_version_str))

    pe = config_data['aliyun_fc']['public_endpoint'].replace('https://', '')
    config_data['aliyun_fc']['public_endpoint'] = pe

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['aliyun_fc']:
            config_data['aliyun_fc'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'runtime' not in config_data['aliyun_fc']:
        config_data['aliyun_fc']['runtime'] = 'default'

    # Put credential keys to 'aliyun_fc' dict entry
    config_data['aliyun_fc'].update(config_data['aliyun'])
