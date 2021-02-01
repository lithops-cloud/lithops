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

RUNTIME_TIMEOUT_DEFAULT = 300  # 5 minutes
RUNTIME_MEMORY_DEFAULT = 256  # 256Mi
RUNTIME_CPU_DEFAULT = 1  # 1 vCPU
RUNTIME_CONTAINER_CONCURRENCY_DEFAULT = 1  # 1 request per container

MAX_CONCURRENT_WORKERS = 1000
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
        pika==0.13.1 \
        flask \
        gevent \
        glob2 \
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
    if config_data is None:
        config_data = {}

    if 'runtime_memory' not in config_data['serverless']:
        config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['serverless']:
        config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['serverless']:
        config_data['serverless']['runtime'] = DEFAULT_RUNTIME_NAME

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

    config_data['gcp_cloudrun']['workers'] = config_data['lithops']['workers']

    config_data['gcp_cloudrun'].update(config_data['gcp'])
