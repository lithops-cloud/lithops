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


RUNTIME_TIMEOUT_DEFAULT = 300    # Default: 5 minutes
RUNTIME_TIMEOUT_MAX = 600        # Platform 10 min. maximum
RUNTIME_MEMORY_DEFAULT = 256
RUNTIME_MEMORY_MAX = 3072
MAX_CONCURRENT_WORKERS = 300
INVOKE_POOL_THREADS_DEFAULT = 300

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

    if 'invoke_pool_threads' not in config_data['aliyun_fc']:
        config_data['aliyun_fc']['invoke_pool_threads'] = INVOKE_POOL_THREADS_DEFAULT

    if 'runtime' not in config_data['aliyun_fc']:
        config_data['aliyun_fc']['runtime'] = 'default'

    if 'runtime_memory' in config_data['aliyun_fc']:
        if config_data['aliyun_fc']['runtime_memory'] > RUNTIME_MEMORY_MAX:
            config_data['aliyun_fc']['runtime_memory'] = RUNTIME_MEMORY_MAX
    else:
        config_data['aliyun_fc']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT

    if 'runtime_timeout' in config_data['aliyun_fc']:
        if config_data['aliyun_fc']['runtime_timeout'] > RUNTIME_TIMEOUT_MAX:
            config_data['aliyun_fc']['runtime_timeout'] = RUNTIME_TIMEOUT_MAX
    else:
        config_data['aliyun_fc']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'workers' in config_data['lithops']:
        if config_data['lithops']['workers'] > MAX_CONCURRENT_WORKERS:
            config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS
    else:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS

    # Put credential keys to 'aws_lambda' dict entry
    config_data['aliyun_fc'].update(config_data['aliyun'])
