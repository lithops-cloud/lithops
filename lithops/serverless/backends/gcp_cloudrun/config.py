#
# (C) Copyright Cloudlab URV 2020
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
import logging
from os.path import exists, isfile


logger = logging.getLogger(__name__)

DEFAULT_RUNTIME_NAME = 'lithops-cloudrun'

RUNTIME_TIMEOUT_DEFAULT = 300  # 5 minutes
RUNTIME_MEMORY_DEFAULT = 256  # 256Mi
RUNTIME_CPU_DEFAULT = 1  # 1 vCPU
RUNTIME_CONTAINER_CONCURRENCY_DEFAULT = 1  # 1 request per container

MAX_CONCURRENT_WORKERS = 1000
MAX_RUNTIME_MEMORY = 8192  # 8 GiB
MAX_RUNTIME_TIMEOUT = 3600  # 1 hour

AVAILABLE_RUNTIME_CPUS = {1, 2, 4}

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_cloudrun.zip')


def load_config(config_data):
    if config_data is None:
        config_data = {}

    if 'runtime_memory' not in config_data['serverless']:
        config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['serverless']:
        config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['serverless']:
        config_data['serverless']['runtime'] = 'default'
    elif not config_data['serverless']['runtime'].contains('gcr'):
        raise Exception('Google Cloud Run requires container images to be deployed on Google Cloud Container Registry')

    if 'workers' not in config_data['lithops']:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS

    if config_data['serverless']['runtime_memory'] > MAX_RUNTIME_MEMORY:
        logger.warning('Runtime memory {} exceeds maximum - '
                       'Runtime memory set to {}'.format(config_data['serverless']['runtime_memory'],
                                                         MAX_RUNTIME_MEMORY))
        config_data['serverless']['runtime_memory'] = MAX_RUNTIME_MEMORY
    if config_data['serverless']['runtime_timeout'] > MAX_RUNTIME_TIMEOUT:
        logger.warning('Runtime timeout {} exceeds maximum - '
                       'Runtime timeout set to {}'.format(config_data['serverless']['runtime_memory'],
                                                          MAX_RUNTIME_TIMEOUT))
        config_data['serverless']['runtime_timeout'] = MAX_RUNTIME_TIMEOUT

    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    required_parameters = {'project_name', 'service_account', 'credentials_path', 'region'}
    if not required_parameters.issubset(set(config_data['gcp'])):
        raise Exception("'project_name', 'service_account', 'credentials_path' and 'region' "
                        "are mandatory under 'gcp' section")

    if not exists(config_data['gcp']['credentials_path']) or not isfile(config_data['gcp']['credentials_path']):
        raise Exception("Path {} must be service account "
                        "credential JSON file.".format(config_data['gcp']['credentials_path']))

    if 'gcp_cloudrun' not in config_data:
        config_data['gcp_cloudrun'] = {
            'runtime_cpus': RUNTIME_CPU_DEFAULT,
            'container_concurrency': RUNTIME_CONTAINER_CONCURRENCY_DEFAULT
        }

    if 'runtime_cpus' in config_data['gcp_cloudrun']:
        if config_data['gcp_cloudrun']['runtime_cpus'] not in AVAILABLE_RUNTIME_CPUS:
            raise Exception('{} vCPUs is not available - '
                            'choose one from {} vCPUs'.format(config_data['gcp_cloudrun']['runtime_cpus'],
                                                              AVAILABLE_RUNTIME_CPUS))
        if config_data['gcp_cloudrun']['runtime_cpus'] == 4 and config_data['serverless']['runtime_memory'] < 4096:
            raise Exception('For {} vCPUs, runtime memory '
                            'must be at least 4096 MiB'.format(config_data['gcp_cloudrun']['runtime_cpus']))
    else:
        config_data['gcp_cloudrun']['runtime_cpus'] = RUNTIME_CPU_DEFAULT

    if 'container_concurrency' not in config_data['gcp_cloudrun']:
        config_data['gcp_cloudrun']['container_concurrency'] = RUNTIME_CONTAINER_CONCURRENCY_DEFAULT

    config_data['gcp_cloudrun'].update(config_data['gcp'])
    print(config_data)

