#
# Copyright Cloudlab URV 2021
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
import shutil
import logging
import lithops

from lithops.utils import version_str
from lithops.constants import WORKER_PROCESSES_DEFAULT

logger = logging.getLogger(__name__)

DOCKER_PATH = shutil.which('docker')
DEFAULT_RUNTIME_NAME = 'default_runtime'

ENV_TYPES = {'EC2', 'SPOT', 'FARGATE', 'FARGATE_SPOT'}
DEFAULT_ENV_TYPE = 'FARGATE_SPOT'

ENV_MAX_CPUS_DEFAULT = 10

AVAILABLE_MEM_FARGATE = [512] + [1024 * i for i in range(1, 31)]
AVAILABLE_CPU_FARGATE = [0.25, 0.5, 1, 2, 4]

RUNTIME_TIMEOUT_DEFAULT = 180  # Default timeout: 180 s == 3 min
RUNTIME_TIMEOUT_MAX = 900  # Max. timeout: 900 s == 15 min
RUNTIME_MEMORY_DEFAULT = 256  # Default memory: 256 MB
RUNTIME_MEMORY_MAX = 10240  # Max. memory: 10240 MB

DOCKERFILE_DEFAULT = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        boto3 \
        pika \
        glob2 \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_aws_batch.zip .
RUN unzip lithops_aws_batch.zip && rm lithops_aws_batch.zip

ENTRYPOINT python entry_point.py
"""


def load_config(config_data):
    if 'aws' not in config_data or 'aws_batch' not in config_data:
        raise Exception("'aws' and 'aws_batch' sections are mandatory in the configuration")

    # Generic serverless config
    if 'runtime' not in config_data['aws_batch']:
        if not DOCKER_PATH:
            raise Exception('docker command not found. Install docker or use an already built runtime')
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in lithops.__version__ else lithops.__version__.replace('.', '')
        runtime_name = '{}-v{}:{}'.format(DEFAULT_RUNTIME_NAME, python_version, revision)
        config_data['aws_batch']['runtime'] = runtime_name
    if 'runtime_memory' not in config_data['aws_batch']:
        config_data['aws_batch']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if config_data['aws_batch']['runtime_memory'] > RUNTIME_MEMORY_MAX:
        logger.warning("Memory set to {} - {} exceeds "
                       "the maximum amount".format(RUNTIME_MEMORY_MAX, config_data['aws_batch']['runtime_memory']))
        config_data['aws_batch']['runtime_memory'] = RUNTIME_MEMORY_MAX
    if 'runtime_timeout' not in config_data['aws_batch']:
        config_data['aws_batch']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if config_data['aws_batch']['runtime_timeout'] > RUNTIME_MEMORY_MAX:
        logger.warning("Timeout set to {} - {} exceeds the "
                       "maximum amount".format(RUNTIME_TIMEOUT_MAX, config_data['aws_batch']['runtime_timeout']))
        config_data['aws_batch']['runtime_memory'] = RUNTIME_MEMORY_MAX
    if 'worker_processes' not in config_data['aws_batch']:
        config_data['aws_batch']['worker_processes'] = WORKER_PROCESSES_DEFAULT

    config_data['aws_batch']['max_workers'] = config_data['aws_batch']['env_max_cpus'] // config_data['aws_batch']['container_vcpus']

    if config_data['aws_batch']['env_type'] not in {'EC2', 'SPOT', 'FARGATE', 'FARGATE_SPOT'}:
        raise Exception('Unknown env type {}'.format(config_data['aws_batch']['env_type']))

    if 'env_type' not in config_data['aws_batch']:
        config_data['aws_batch']['env_type'] = DEFAULT_ENV_TYPE
    if config_data['aws_batch']['env_type'] not in ENV_TYPES:
        logger.error(config_data['aws_batch'])
        raise Exception(
            'AWS Batch env type must be one of {} (is {})'.format(ENV_TYPES, config_data['aws_batch']['env_type']))
    if config_data['aws_batch']['env_type'] in {'FARGATE, FARGATE_SPOT'}:
        if config_data['aws_batch']['container_vcpus'] not in AVAILABLE_CPU_FARGATE:
            raise Exception('{} container vcpus is not available for {} environment (choose one of {})'.format(
                config_data['aws_batch']['runtime_memory'], config_data['aws_batch']['env_type'],
                AVAILABLE_CPU_FARGATE
            ))
        if config_data['aws_batch']['runtime_memory'] not in AVAILABLE_MEM_FARGATE:
            raise Exception('{} runtime memory is not available for {} environment (choose one of {})'.format(
                config_data['aws_batch']['runtime_memory'], config_data['aws_batch']['env_type'],
                AVAILABLE_MEM_FARGATE
            ))
    if config_data['aws_batch']['env_type'] in {'EC2', 'SPOT'}:
        if 'instance_role' not in config_data['aws_batch']:
            raise Exception("'instance_role' mandatory for EC2 or SPOT environments")

    # Auth, role and region config
    if not {'access_key_id', 'secret_access_key'}.issubset(set(config_data['aws'])):
        raise Exception("'access_key_id' and 'secret_access_key' are mandatory under 'aws' section")

    if 'account_id' not in config_data['aws']:
        config_data['aws']['account_id'] = None

    if not {'execution_role', 'region_name'}.issubset(set(config_data['aws_batch'])):
        raise Exception("'execution_role' and 'region_name' are mandatory under 'aws_batch' section")
    if 'service_role' not in config_data['aws_batch']:
        config_data['aws_batch']['service_role'] = None

    # VPC config
    if 'subnets' not in config_data['aws_batch']:
        config_data['aws_batch']['subnets'] = []
    if 'assign_public_ip' not in config_data['aws_batch']:
        config_data['aws_batch']['assign_public_ip'] = True
    assert isinstance(config_data['aws_batch']['assign_public_ip'], bool)

    # Put credential keys to 'aws_batch' dict entry
    config_data['aws_batch'] = {**config_data['aws_batch'], **config_data['aws']}
