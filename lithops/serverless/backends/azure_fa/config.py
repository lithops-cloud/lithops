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

ACTION_MODULES_DIR = os.path.join('.python_packages', 'lib', 'site-packages')

RUNTIME_DEFAULT_36 = 'lithops-runtime'
FUNCTIONS_VERSION_DEFAULT = 2
RUNTIME_TIMEOUT_DEFAULT = 300000    # Default: 300000 ms => 10 minutes
RUNTIME_TIMEOUT_MAX = 600000        # Platform maximum
RUNTIME_MEMORY_DEFAULT = 1500       # Default memory: 1.5 GB
MAX_CONCURRENT_WORKERS = 2000


def load_config(config_data=None):

    this_version_str = version_str(sys.version_info)
    if this_version_str != '3.6':
        raise Exception('The functions backend Azure Function Apps currently'
                        ' only supports Python version 3.6.X and the local Python'
                        'version is {}'.format(this_version_str))

    if 'runtime' in config_data['serverless']:
        print("Ignoring user specified '{}'. The current Azure compute backend"
              " does not support custom runtimes.".format('runtime'))
    config_data['serverless']['runtime'] = RUNTIME_DEFAULT_36

    if 'runtime_memory' in config_data['serverless']:
        print("Ignoring user specified '{}'. The current Azure compute backend"
              " does not support custom runtimes.".format('runtime_memory'))
        print('Default runtime memory: {}MB'.format(RUNTIME_MEMORY_DEFAULT))
    config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT

    if 'runtime_timeout' in config_data['serverless']:
        print("Ignoring user specified '{}'. The current Azure compute backend"
              " does not support custom runtimes.".format('runtime_timeout'))
        print('Default runtime timeout: {}ms'.format(RUNTIME_TIMEOUT_DEFAULT))
    config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'workers' not in config_data['lithops']:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS

    if 'azure_fa' not in config_data:
        raise Exception("azure_fa section is mandatory in the configuration")

    required_parameters = ('resource_group', 'location', 'account_name', 'account_key')

    if set(required_parameters) > set(config_data['azure_fa']):
        raise Exception('You must provide {} to access to Azure Function App '\
                        .format(required_parameters))
    
    if 'functions_version' not in config_data['azure_fa']:
        config_data['lithops']['functions_version'] = FUNCTIONS_VERSION_DEFAULT
    elif config_data['azure_fa']['functions_version'] not in (2, 3):
        raise Exception('You must provide a valid Azure Functions App version {}'\
                        .format((2, 3)))
