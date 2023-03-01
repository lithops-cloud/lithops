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

import copy
import logging

logger = logging.getLogger(__name__)

ENV_TYPES = {'EC2', 'SPOT', 'FARGATE', 'FARGATE_SPOT'}
RUNTIME_ZIP = 'lithops_aws_batch.zip'

AVAILABLE_MEM_FARGATE = [512] + [1024 * i for i in range(1, 31)]
AVAILABLE_CPU_FARGATE = [0.25, 0.5, 1, 2, 4]

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 180,  # Default: 180 seconds => 3 minutes
    'runtime_memory': 1024,  # Default memory: 1GB
    'worker_processes': 1,
    'container_vcpus': 0.5,
    'env_max_cpus': 10,
    'env_type': 'FARGATE_SPOT',
    'assign_public_ip': True,
    'subnets': []
}

RUNTIME_TIMEOUT_MAX = 7200  # Max. timeout: 7200s == 2h
RUNTIME_MEMORY_MAX = 30720  # Max. memory: 30720 MB

REQ_PARAMS = ('execution_role', 'instance_role', 'security_groups')

DOCKERFILE_DEFAULT = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
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

    if 'aws' not in config_data:
        raise Exception("'aws' section is mandatory in the configuration")

    if not {'access_key_id', 'secret_access_key'}.issubset(set(config_data['aws'])):
        raise Exception("'access_key_id' and 'secret_access_key' are mandatory under the 'aws' section of the configuration")

    if not config_data['aws_batch']:
        raise Exception("'aws_batch' section is mandatory in the configuration")

    temp = copy.deepcopy(config_data['aws_batch'])
    config_data['aws_batch'].update(config_data['aws'])
    config_data['aws_batch'].update(temp)

    for param in REQ_PARAMS:
        if param not in config_data['aws_batch']:
            msg = f'"{param}" is mandatory in the "aws_batch" section of the configuration'
            raise Exception(msg)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['aws_batch']:
            config_data['aws_batch'][key] = DEFAULT_CONFIG_KEYS[key]

    if config_data['aws_batch']['runtime_memory'] > RUNTIME_MEMORY_MAX:
        logger.warning("Memory set to {} - {} exceeds "
                       "the maximum amount".format(RUNTIME_MEMORY_MAX, config_data['aws_batch']['runtime_memory']))
        config_data['aws_batch']['runtime_memory'] = RUNTIME_MEMORY_MAX

    if config_data['aws_batch']['runtime_timeout'] > RUNTIME_TIMEOUT_MAX:
        logger.warning("Timeout set to {} - {} exceeds the "
                       "maximum amount".format(RUNTIME_TIMEOUT_MAX, config_data['aws_batch']['runtime_timeout']))
        config_data['aws_batch']['runtime_timeout'] = RUNTIME_TIMEOUT_MAX

    config_data['aws_batch']['max_workers'] = config_data['aws_batch']['env_max_cpus'] // config_data['aws_batch']['container_vcpus']

    if config_data['aws_batch']['env_type'] not in ENV_TYPES:
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

    assert isinstance(config_data['aws_batch']['assign_public_ip'], bool)

    if 'region_name' in config_data['aws_batch']:
        config_data['aws_batch']['region'] = config_data['aws_batch'].pop('region_name')

    if 'region' not in config_data['aws_batch']:
        raise Exception('"region" is mandatory under the "aws_batch" or "aws" section of the configuration')
    elif 'region' not in config_data['aws']:
        config_data['aws']['region'] = config_data['aws_batch']['region']
