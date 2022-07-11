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

import os

from lithops.constants import TEMP_DIR

FH_ZIP_LOCATION = os.path.join(TEMP_DIR, 'lithops_gcp_functions.zip')
SCOPES = ('https://www.googleapis.com/auth/cloud-platform',
          'https://www.googleapis.com/auth/pubsub')
FUNCTIONS_API_VERSION = 'v1'
PUBSUB_API_VERSION = 'v1'
AUDIENCE = "https://pubsub.googleapis.com/google.pubsub.v1.Publisher"

RUNTIME_MEMORY_MAX = 8192  # 8GB
RUNTIME_MEMORY_OPTIONS = {128, 256, 512, 1024, 2048, 4096, 8192}

RETRIES = 5
RETRY_SLEEP = 20

AVAILABLE_PY_RUNTIMES = {'3.7': 'python37', '3.8': 'python38', '3.9': 'python39'}

USER_RUNTIMES_PREFIX = 'lithops.user_runtimes'

REQ_PARAMS = ('region', )

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 5 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 1000,
    'worker_processes': 1,
    'invoke_pool_threads': 1000,
    'trigger': 'pub/sub'
}

REQUIREMENTS_FILE = """
numpy
scipy
scikit-learn
pandas
google-cloud
google-cloud-storage
google-cloud-pubsub
google-auth
google-api-python-client
certifi
chardet
docutils
httplib2
idna
jmespath
kafka-python
lxml
pika
redis
requests
six
urllib3
virtualenv
PyYAML
cloudpickle
ps-mem
tblib
"""


def load_config(config_data=None):
    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['gcp']:
            msg = f"{param} is mandatory under 'gcp' section of the configuration"
            raise Exception(msg)

    if 'credentials_path' not in config_data['gcp']:
        if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
            config_data['gcp']['credentials_path'] = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

    if 'credentials_path' in config_data['gcp']:
        config_data['gcp']['credentials_path'] = os.path.expanduser(config_data['gcp']['credentials_path'])

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['gcp_functions']:
            config_data['gcp_functions'][key] = DEFAULT_CONFIG_KEYS[key]

    if config_data['gcp_functions']['runtime_memory'] not in RUNTIME_MEMORY_OPTIONS:
        raise Exception('{} MB runtime is not available (Only one of {} MB is available)'.format(
            config_data['gcp_functions']['runtime_memory'], RUNTIME_MEMORY_OPTIONS))

    if config_data['gcp_functions']['runtime_memory'] > RUNTIME_MEMORY_MAX:
        config_data['gcp_functions']['runtime_memory'] = RUNTIME_MEMORY_MAX

    config_data['gcp_functions']['retries'] = RETRIES
    config_data['gcp_functions']['retry_sleep'] = RETRY_SLEEP

    config_data['gcp_functions'].update(config_data['gcp'])
