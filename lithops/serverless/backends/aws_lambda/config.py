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
import shutil
import logging

from lithops.utils import version_str

logger = logging.getLogger(__name__)

DEFAULT_REQUIREMENTS = [
    'requests',
    'redis',
    'pika',
    'cloudpickle',
    'ps-mem',
    'tblib'
]

DOCKER_PATH = shutil.which('docker')

LAMBDA_PYTHON_VER_KEY = 'python{}'.format(version_str(sys.version_info))
DEFAULT_RUNTIME = LAMBDA_PYTHON_VER_KEY.replace('.', '')
AVAILABLE_RUNTIMES = ['python36', 'python37', 'python38']

USER_RUNTIME_PREFIX = 'lithops.user_runtimes'

RUNTIME_TIMEOUT_DEFAULT = 180  # Default timeout: 180 s == 3 min
RUNTIME_TIMEOUT_MAX = 900  # Max. timeout: 900 s == 15 min
RUNTIME_MEMORY_DEFAULT = 256  # Default memory: 256 MB
RUNTIME_MEMORY_MAX = 10240  # Max. memory: 10240 MB

MAX_CONCURRENT_WORKERS = 1000
INVOKE_POOL_THREADS_DEFAULT = 64


def load_config(config_data):

    if 'aws' not in config_data and 'aws_lambda' not in config_data:
        raise Exception("'aws' and 'aws_lambda' sections are mandatory in the configuration")

    # Generic serverless config
    if 'invoke_pool_threads' not in config_data['aws_lambda']:
        config_data['aws_lambda']['invoke_pool_threads'] = INVOKE_POOL_THREADS_DEFAULT
    if 'runtime_memory' not in config_data['aws_lambda']:
        config_data['aws_lambda']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if config_data['aws_lambda']['runtime_memory'] % 64 != 0:     # Adjust 64 MB memory increments restriction
        mem = config_data['aws_lambda']['runtime_memory']
        config_data['aws_lambda']['runtime_memory'] = (mem + (64 - (mem % 64)))
    if config_data['aws_lambda']['runtime_memory'] > RUNTIME_MEMORY_MAX:
        logger.warning("Memory set to {} - {} exceeds "
                       "the maximum amount".format(RUNTIME_MEMORY_MAX, config_data['aws_lambda']['runtime_memory']))
        config_data['aws_lambda']['runtime_memory'] = RUNTIME_MEMORY_MAX

    if 'runtime_timeout' not in config_data['aws_lambda']:
        config_data['aws_lambda']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if config_data['aws_lambda']['runtime_timeout'] > RUNTIME_MEMORY_MAX:
        logger.warning("Timeout set to {} - {} exceeds the "
                       "maximum amount".format(RUNTIME_TIMEOUT_MAX, config_data['aws_lambda']['runtime_timeout']))
        config_data['aws_lambda']['runtime_memory'] = RUNTIME_MEMORY_MAX

    if 'runtime' not in config_data['aws_lambda']:
        if DEFAULT_RUNTIME not in AVAILABLE_RUNTIMES:
            raise Exception('Python version "{}" is not available for AWS Lambda, '
                            'please use one of {}'.format(LAMBDA_PYTHON_VER_KEY, AVAILABLE_RUNTIMES))
        config_data['aws_lambda']['runtime'] = DEFAULT_RUNTIME

    if 'workers' not in config_data['lithops']:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS

    # Auth, role and region config
    if not {'access_key_id', 'secret_access_key'}.issubset(set(config_data['aws'])):
        raise Exception("'access_key_id' and 'secret_access_key' are mandatory under 'aws' section")

    if 'account_id' not in config_data['aws']:
        config_data['aws']['account_id'] = None

    if not {'execution_role', 'region_name'}.issubset(set(config_data['aws_lambda'])):
        raise Exception("'execution_role' and 'region_name' are mandatory under 'aws_lambda' section")

    # VPC config
    if 'vpc' not in config_data['aws_lambda']:
        config_data['aws_lambda']['vpc'] = {'subnets': [], 'security_groups': []}

    if not {'subnets', 'security_groups'}.issubset(set(config_data['aws_lambda']['vpc'])):
        raise Exception("'subnets' and 'security_groups' are mandatory sections under 'aws_lambda/vpc'")

    if not isinstance(config_data['aws_lambda']['vpc']['subnets'], list):
        raise Exception("Unknown type {} for 'aws_lambda/"
                        "vpc/subnet' section".format(type(config_data['aws_lambda']['vpc']['subnets'])))

    if not isinstance(config_data['aws_lambda']['vpc']['security_groups'], list):
        raise Exception("Unknown type {} for 'aws_lambda/"
                        "vpc/security_groups' section".format(type(config_data['aws_lambda']['vpc']['security_groups'])))

    # EFS config
    if 'efs' not in config_data['aws_lambda']:
        config_data['aws_lambda']['efs'] = []

    if not isinstance(config_data['aws_lambda']['efs'], list):
        raise Exception("Unknown type {} for "
                        "'aws_lambda/efs' section".format(type(config_data['aws_lambda']['vpc']['security_groups'])))

    if not all(['access_point' in efs_conf and 'mount_path' in efs_conf for efs_conf in config_data['aws_lambda']['efs']]):
        raise Exception("List of 'access_point' and 'mount_path' mandatory in 'aws_lambda/efs section'")

    if not all([efs_conf['mount_path'].startswith('/mnt') for efs_conf in config_data['aws_lambda']['efs']]):
        raise Exception("All mount paths must start with '/mnt' on 'aws_lambda/efs/*/mount_path' section")

    # Put credential keys to 'aws_lambda' dict entry
    config_data['aws_lambda'].update(config_data['aws'])
