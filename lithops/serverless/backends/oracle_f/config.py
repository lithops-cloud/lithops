# (C) Copyright Cloudlab URV 2023
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
import copy


DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 5 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 300,
    'worker_processes': 1,
    'invoke_pool_threads': 64,
}

CONNECTION_POOL_SIZE = 300

APP_NAME = 'lithops'
FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_oracle.zip')

DEFAULT_DOCKERFILE = """
RUN apt-get update \
    && apt-get install -y \
    zip \
    && rm -rf /var/lib/apt/lists/*

# Update pip
RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
    fn \
    fdk \
    redis \
    httplib2 \
    requests \
    numpy \
    scipy \
    pandas \
    pika \
    PyYAML \
    cloudpickle \
    ps-mem \
    tblib \
    oci \
    psutil

ARG FUNCTION_DIR="/function"

# Copy function code
RUN mkdir -p ${FUNCTION_DIR}
ENV FN_LISTENER=unix:/tmp/fn.sock
ENV FN_FORMAT=http-stream

WORKDIR ${FUNCTION_DIR}

COPY lithops_oracle.zip ${FUNCTION_DIR}
RUN unzip lithops_oracle.zip \
    && rm lithops_oracle.zip \
    && mkdir handler \
    && touch handler/__init__.py \
    && mv entry_point.py handler/


ENV PYTHONPATH "${PYTHONPATH}:${FUNCTION_DIR}"
ENTRYPOINT ["/usr/local/bin/fdk", "handler/entry_point.py", "handler"]
"""

AVAILABLE_PY_RUNTIMES = ['3.6', '3.7', '3.8', '3.9', '3.11']

REQ_PARAMS_1 = ('compartment_id', 'user', 'key_file', 'region', 'tenancy', 'fingerprint')
REQ_PARAMS_2 = ('subnet_id', )


def load_config(config_data=None):
    if 'oracle' not in config_data:
        raise Exception("'oracle' section is mandatory in the configuration")

    if 'oracle' not in config_data:
        raise Exception("'oracle_f' section is mandatory in the configuration")

    for param in REQ_PARAMS_1:
        if param not in config_data['oracle']:
            msg = f'"{param}" is mandatory in the "oracle" section of the configuration'
            raise Exception(msg)

    for param in REQ_PARAMS_2:
        if param not in config_data['oracle_f']:
            msg = f'"{param}" is mandatory in the "oracle_f" section of the configuration'
            raise Exception(msg)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['oracle_f']:
            config_data['oracle_f'][key] = DEFAULT_CONFIG_KEYS[key]

    temp = copy.deepcopy(config_data['oracle_f'])
    config_data['oracle_f'].update(config_data['oracle'])
    config_data['oracle_f'].update(temp)
