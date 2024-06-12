#
# (C) Copyright Cloudlab URV 2024
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
import shutil

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_singularity.zip')

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 10 minutes
    'runtime_memory': 512,  # Default memory: 512 MB
    'max_workers': 100,
    'worker_processes': 1,
}


SINGULARITYFILE_DEFAULT = """
%post
    apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

    pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        boto3 \
        pika \
        flask \
        gevent \
        redis \
        requests \
        PyYAML \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        psutil

%files
    lithops_singularity.zip /lithops/lithops_singularity.zip

%post
    cd /lithops
    unzip lithops_singularity.zip && rm lithops_singularity.zip

%runscript
    python3 /lithops/lithopsentry.py $AMQP_URL
"""


def get_singularity_path():
    singularity_path = shutil.which('singularity')
    if not singularity_path:
        raise Exception('singularity command not found. Install singularity')
    return singularity_path


def load_config(config_data):
    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['singularity']:
            config_data['singularity'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'rabbitmq' not in config_data:
        raise Exception('RabbitMQ configuration is needed in this backend')
    else:
        config_data['singularity']['amqp_url'] = config_data['rabbitmq'].get('amqp_url', False)
