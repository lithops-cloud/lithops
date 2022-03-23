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
import sys
from os.path import exists, isfile

from ....utils import version_str


logger = logging.getLogger(__name__)

DEFAULT_RUNTIME_NAME = 'python' + version_str(sys.version_info)

REQ_PARAMS = ('project_name', 'service_account', 'credentials_path', 'region')

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 600 seconds => 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'runtime_cpu': 1,  # 0.125 vCPU
    'max_workers': 1000,
    'worker_processes': 1,
    'invoke_pool_threads': 100,
}

MAX_RUNTIME_MEMORY = 8192  # 8 GiB
MAX_RUNTIME_TIMEOUT = 3600  # 1 hour

AVAILABLE_RUNTIME_CPUS = {1, 2, 4}

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_cloudrun.zip')

DEFAULT_DOCKERFILE = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        wheel \
        gunicorn \
        pika \
        flask \
        gevent \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        namegenerator \
        cryptography \
        httplib2 \
        google-cloud-storage \
        google-api-python-client \
        gcsfs \
        google-auth

ENV PORT 8080
ENV PYTHONUNBUFFERED TRUE

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_knative.zip .
RUN unzip lithops_knative.zip && rm lithops_knative.zip

CMD exec gunicorn --bind :$PORT lithopsproxy:proxy
"""


def load_config(config_data):
    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['gcp']:
            msg = "{} is mandatory under 'gcp' section of the configuration".format(REQ_PARAMS)
            raise Exception(msg)

    if not exists(config_data['gcp']['credentials_path']) or not isfile(config_data['gcp']['credentials_path']):
        raise Exception("Path {} must be service account "
                        "credential JSON file.".format(config_data['gcp']['credentials_path']))

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['gcp_cloudrun']:
            config_data['gcp_cloudrun'][key] = DEFAULT_CONFIG_KEYS[key]

    config_data['gcp_cloudrun']['invoke_pool_threads'] = config_data['gcp_cloudrun']['max_workers']

    if 'runtime' not in config_data['gcp_cloudrun']:
        config_data['gcp_cloudrun']['runtime'] = DEFAULT_RUNTIME_NAME

    if config_data['gcp_cloudrun']['runtime_memory'] > MAX_RUNTIME_MEMORY:
        logger.warning('Runtime memory {} exceeds maximum - '
                       'Runtime memory set to {}'.format(config_data['gcp_cloudrun']['runtime_memory'],
                                                         MAX_RUNTIME_MEMORY))
        config_data['gcp_cloudrun']['runtime_memory'] = MAX_RUNTIME_MEMORY

    if config_data['gcp_cloudrun']['runtime_timeout'] > MAX_RUNTIME_TIMEOUT:
        logger.warning('Runtime timeout {} exceeds maximum - '
                       'Runtime timeout set to {}'.format(config_data['gcp_cloudrun']['runtime_memory'],
                                                          MAX_RUNTIME_TIMEOUT))
        config_data['gcp_cloudrun']['runtime_timeout'] = MAX_RUNTIME_TIMEOUT

    if config_data['gcp_cloudrun']['runtime_cpu'] not in AVAILABLE_RUNTIME_CPUS:
        raise Exception('{} vCPUs is not available - '
                        'choose one from {} vCPUs'.format(config_data['gcp_cloudrun']['runtime_cpu'],
                                                          AVAILABLE_RUNTIME_CPUS))
    if config_data['gcp_cloudrun']['runtime_cpu'] == 4 and config_data['gcp_cloudrun']['runtime_memory'] < 4096:
        raise Exception('For {} vCPUs, runtime memory must be at least 4096 MiB'
                        .format(config_data['gcp_cloudrun']['runtime_cpu']))

    config_data['gcp_cloudrun'].update(config_data['gcp'])
