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
from lithops.utils import version_str

RUNTIME_DEFAULT = {'3.5': 'cactusone/lithops-code-engine-v3.5',
                   '3.6': 'cactusone/lithops-code-engine-v3.6',
                   '3.7': 'cactusone/lithops-code-engine-v3.7',
                   '3.8': 'cactusone/lithops-code-engine-v3.8'}

RUNTIME_TIMEOUT_DEFAULT = 600  # Default: 600 seconds => 10 minutes
RUNTIME_MEMORY_DEFAULT = 128  # Default memory: 256 MB
MAX_CONCURRENT_WORKERS = 1200
CPU_DEFAULT = 1 # default number of CPU

DEFAULT_API_VERSION = 'codeengine.cloud.ibm.com/v1beta1'
DEFAULT_GROUP = "codeengine.cloud.ibm.com"
DEFAULT_VERSION = "v1beta1"

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_codeengine.zip')

def load_config(config_data):
    if 'runtime_memory' not in config_data['lithops']:
        config_data['lithops']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['lithops']:
        config_data['lithops']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['lithops']:
        python_version = version_str(sys.version_info)
        try:
            config_data['lithops']['runtime'] = RUNTIME_DEFAULT[python_version]
        except KeyError:
            raise Exception('Unsupported Python version: {}'.format(python_version))
    if 'workers' not in config_data['lithops'] or \
       config_data['lithops']['workers'] > MAX_CONCURRENT_WORKERS:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS
    
    if 'code_engine' in config_data:
        if 'runtime_cpu' not in config_data['code_engine']:
            config_data['code_engine']['runtime_cpu'] = CPU_DEFAULT
        if 'api_version' not in config_data['code_engine']:
            config_data['code_engine']['api_version'] = DEFAULT_API_VERSION
        if 'group' not in config_data['code_engine']:
            config_data['code_engine']['group'] = DEFAULT_GROUP
        if 'version' not in config_data['code_engine']:
            config_data['code_engine']['version'] = DEFAULT_VERSION
