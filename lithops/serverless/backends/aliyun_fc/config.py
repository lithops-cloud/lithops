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

import copy
import os
from lithops.constants import TEMP_DIR


DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 5 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 300,
    'worker_processes': 1,
    'invoke_pool_threads': 64,
    'deploy_mode': 'runtime',  # 'runtime' or 'custom-container'
    'docker_server': 'docker.io',
}

# FC custom-container HTTP port (fixed by Alibaba Cloud; do not change).
CA_PORT = 9000

BUILD_DIR = os.path.join(TEMP_DIR, 'AliyunRuntimeBuild')
FH_ZIP_LOCATION = os.path.join(TEMP_DIR, 'lithops_aliyun_fc.zip')

DEFAULT_DOCKERFILE = """
RUN apt-get update && apt-get install -y zip && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools \
    && pip install --no-cache-dir \
        gunicorn flask gevent six pika redis requests PyYAML oss2 \
        cloudpickle ps-mem tblib psutil

ENV APP_HOME=/function
WORKDIR ${APP_HOME}

COPY lithops_aliyun_fc.zip .
RUN unzip lithops_aliyun_fc.zip && rm lithops_aliyun_fc.zip

ENV CAPort=9000
CMD exec gunicorn --bind 0.0.0.0:${CAPort} --workers 1 --timeout 600 --keep-alive 95 container_entry_point:app
"""

AVAILABLE_PY_RUNTIMES = {
    '3.9': 'python3.9',
    '3.10': 'python3.10',
    '3.12': 'python3.12',
}

REQUIREMENTS_FILE = """
six
pika
tblib
cloudpickle
ps-mem
psutil
"""

REQ_PARAMS_1 = ('account_id', 'access_key_id', 'access_key_secret')
REQ_PARAMS_2 = ('role_arn', )

ENDPOINT = "{0}.{1}.fc.aliyuncs.com"


def load_config(config_data=None):

    if 'aliyun' not in config_data:
        raise Exception("'aliyun' section is mandatory in the configuration")

    if not config_data['aliyun_fc']:
        raise Exception("'aliyun_fc' section is mandatory in the configuration")

    for param in REQ_PARAMS_1:
        if param not in config_data['aliyun']:
            msg = f'"{param}" is mandatory in the "aliyun" section of the configuration'
            raise Exception(msg)

    for param in REQ_PARAMS_2:
        if param not in config_data['aliyun_fc']:
            msg = f'"{param}" is mandatory in the "aliyun_fc" section of the configuration'
            raise Exception(msg)

    temp = copy.deepcopy(config_data['aliyun_fc'])
    config_data['aliyun_fc'].update(config_data['aliyun'])
    config_data['aliyun_fc'].update(temp)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['aliyun_fc']:
            config_data['aliyun_fc'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'region' not in config_data['aliyun_fc']:
        raise Exception('"region" is mandatory under the "aliyun_fc" or "aliyun" section of the configuration')
    elif 'region' not in config_data['aliyun']:
        config_data['aliyun']['region'] = config_data['aliyun_fc']['region']

    account_id = config_data['aliyun_fc']['account_id']
    region = config_data['aliyun_fc']['region']
    config_data['aliyun_fc']['public_endpoint'] = ENDPOINT.format(account_id, region)

    deploy_mode = config_data['aliyun_fc'].get('deploy_mode', 'runtime')
    if deploy_mode not in ('runtime', 'custom-container'):
        raise Exception(
            "aliyun_fc.deploy_mode must be 'runtime' or 'custom-container'"
        )
    config_data['aliyun_fc']['deploy_mode'] = deploy_mode

    if deploy_mode == 'custom-container' and not config_data['aliyun_fc'].get('docker_user'):
        raise Exception(
            "aliyun_fc.docker_user is required when deploy_mode is 'custom-container' "
            '(Docker Hub namespace for pushing images to docker.io)'
        )
