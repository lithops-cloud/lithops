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


PYTHON_RUNTIME = 'python3'
RUNTIME_TIMEOUT_DEFAULT = 600    # Default: 600 s => 10 minutes
RUNTIME_TIMEOUT_MAX = 600        # Platform maximum
RUNTIME_MEMORY_DEFAULT = 256
RUNTIME_MEMORY_MAX = 3072
MAX_CONCURRENT_WORKERS = 300     

SERVICE_NAME = 'lithops-runtime'
HANDLER_FOLDER_LOCATION = os.path.join(os.getcwd(), 'lithops_handler_aliyun')


def load_config(config_data=None):

    this_version_str = version_str(sys.version_info)
    if this_version_str != '3.6':
        raise Exception('The functions backend Aliyun Function Compute currently'
                        ' only supports Python version 3.6.X and the local Python'
                        'version is {}'.format(this_version_str))

    if 'runtime' not in config_data['lithops']:
        config_data['lithops']['runtime'] = 'default'

    if 'runtime_memory' in config_data['lithops']:
        if config_data['lithops']['runtime_memory'] > RUNTIME_MEMORY_MAX:
            config_data['lithops']['runtime_memory'] = RUNTIME_MEMORY_MAX
    else:
        config_data['lithops']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT

    if 'runtime_timeout' in config_data['lithops']:
        if config_data['lithops']['runtime_timeout'] > RUNTIME_TIMEOUT_MAX:
            config_data['lithops']['runtime_timeout'] = RUNTIME_TIMEOUT_MAX
    else:
        config_data['lithops']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'workers' in config_data['lithops']:
        if config_data['lithops']['workers'] > MAX_CONCURRENT_WORKERS:
            config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS
    else:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS


    if 'aliyun_fc' not in config_data:
        raise Exception("aliyun_fc section is mandatory in the configuration")

    required_parameters = ('public_endpoint', 'access_key_id', 'access_key_secret')

    if set(required_parameters) > set(config_data['aliyun_fc']):
        raise Exception('You must provide {} to access to Aliyun Function Compute '\
                        .format(required_parameters))
