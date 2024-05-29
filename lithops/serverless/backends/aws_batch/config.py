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

# https://docs.aws.amazon.com/batch/latest/APIReference/API_ResourceRequirement.html
AVAILABLE_CPU_MEM_FARGATE = {
    0.25: [512, 1024, 2048],
    0.5: [1024, 2048, 3072, 4096],
    1: [2048, 3072, 4096, 5120, 6144, 7168, 8192],
    2: [4096, 5120, 6144, 7168, 8192, 9216, 10240, 11264, 12288, 13312, 14336, 15360, 16384],
    4: [8192 + 1024 * i for i in range(21)],  # Starts at 8192, increments by 1024 up to 30720
    8: [16384 + 4096 * i for i in range(12)],  # Starts at 16384, increments by 4096 up to 61440
    16: [32768 + 8192 * i for i in range(12)]  # Starts at 32768, increments by 8192 up to 122880
}

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 180,  # Default: 180 seconds => 3 minutes
    'runtime_memory': 1024,  # Default memory: 1GB
    'runtime_cpu': 0.5,
    'worker_processes': 1,
    'env_max_cpus': 10,
    'env_type': 'FARGATE_SPOT',
    'assign_public_ip': True,
    'subnets': []
}

REQ_PARAMS = ('execution_role', 'security_groups')

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
        tblib \
        psutil

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_aws_batch.zip .
RUN unzip lithops_aws_batch.zip && rm lithops_aws_batch.zip

ENTRYPOINT python entry_point.py
"""


def load_config(config_data):

    if 'aws_batch' not in config_data or not config_data['aws_batch']:
        raise Exception("'aws_batch' section is mandatory in the configuration")

    if 'aws' not in config_data:
        config_data['aws'] = {}

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

    if config_data['aws_batch']['env_type'] not in ENV_TYPES:
        raise Exception(
            f"AWS Batch env type must be one of {ENV_TYPES} "
            f"(is {config_data['aws_batch']['env_type']})"
        )

    # container_vcpus is deprectaded. To be removed in a future release
    if 'container_vcpus' in config_data['aws_batch']:
        config_data['aws_batch']['runtime_cpu'] = config_data['aws_batch'].pop('container_vcpus')

    if config_data['aws_batch']['env_type'] in {'FARGATE', 'FARGATE_SPOT'}:
        runtime_memory = config_data['aws_batch']['runtime_memory']
        runtime_cpu = config_data['aws_batch']['runtime_cpu']
        env_type = config_data['aws_batch']['env_type']
        cpu_keys = list(AVAILABLE_CPU_MEM_FARGATE.keys())
        if runtime_cpu not in cpu_keys:
            raise Exception(
                f"'{runtime_cpu}' runtime cpu is not available for the {env_type} environment "
                f"(choose one of {', '.join(map(str, cpu_keys))})"
            )
        mem_keys = AVAILABLE_CPU_MEM_FARGATE[runtime_cpu]
        if config_data['aws_batch']['runtime_memory'] not in mem_keys:
            raise Exception(
                f"'{runtime_memory}' runtime memory is not valid for {runtime_cpu} "
                f"vCPU and the {env_type} environment (for {runtime_cpu}vCPU "
                f"choose one of {', '.join(map(str, mem_keys))})"
            )

    if config_data['aws_batch']['env_type'] in {'EC2', 'SPOT'}:
        if 'instance_role' not in config_data['aws_batch']:
            raise Exception("'instance_role' mandatory for EC2 or SPOT environments")

    config_data['aws_batch']['max_workers'] = config_data['aws_batch']['env_max_cpus'] \
        // config_data['aws_batch']['runtime_cpu']

    assert isinstance(config_data['aws_batch']['assign_public_ip'], bool)

    if 'region_name' in config_data['aws_batch']:
        config_data['aws_batch']['region'] = config_data['aws_batch'].pop('region_name')

    if 'region' not in config_data['aws_batch']:
        raise Exception('"region" is mandatory under the "aws_batch" or "aws" section of the configuration')
    elif 'region' not in config_data['aws']:
        config_data['aws']['region'] = config_data['aws_batch']['region']
