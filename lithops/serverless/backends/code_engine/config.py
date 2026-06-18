#
# (C) Copyright IBM Corp. 2020
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

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'runtime_cpu': 0.125,  # 0.125 vCPU
    'max_workers': 1000,
    'worker_processes': 1,
    'docker_server': 'docker.io'
}

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_codeengine.zip')

REGISTRY_SECRET_NAME = 'lithops-regcred'
LITHOPS_RUNTIME_TYPE = 'lithops-runtime'
ENTRYPOINT_SCRIPT = '/lithops/lithopsentry.py'
PYTHON_BIN = '/usr/local/bin/python'
METADATA_JOBRUN_NAME = 'lithops-runtime-metadata'
JOB_RUN_POLL_INTERVAL = 2

# https://cloud.ibm.com/docs/codeengine?topic=codeengine-mem-cpu-combo
VALID_CPU_VALUES = [0.125, 0.25, 0.5, 1, 2, 4, 6, 8]
VALID_MEMORY_VALUES = [256, 512, 1024, 2048, 4096, 8192, 12288, 16384, 24576, 32768]
VALID_CPU_MEMORY = {
    0.125: (256, 8192),
    0.25: (512, 16384),
    0.5: (1024, 32768),
    1: (4096, 32768),
    2: (4096, 32768),
    4: (4096, 32768),
    6: (4096, 32768),
    8: (4096, 32768),
}

# https://cloud.ibm.com/docs/codeengine?topic=codeengine-regions
VALID_REGIONS = [
    'us-south', 'us-east', 'ca-tor', 'eu-de', 'eu-gb', 'eu-es',
    'jp-osa', 'jp-tok', 'br-sao', 'au-syd',
]

BASE_URL_V2 = 'https://api.{}.codeengine.cloud.ibm.com/v2'

REQ_PARAMS = ('iam_api_key', 'resource_group_id')

# Default runtime image for auto-built runtimes.
# CE jobs override the container command; the gunicorn CMD is kept for custom
# runtimes that start the container without JOB_INDEX (legacy Knative path).
DOCKERFILE_DEFAULT = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
        gunicorn \
        pika \
        flask \
        gevent \
        ibm-cos-sdk \
        ibm-cloud-sdk-core \
        ibm-vpc \
        ibm-code-engine-sdk \
        kubernetes \
        redis \
        requests \
        PyYAML \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        psutil

ENV PORT=8080
ENV CONCURRENCY=1
ENV TIMEOUT=600
ENV PYTHONUNBUFFERED=TRUE

ENV APP_HOME=/lithops
WORKDIR $APP_HOME

COPY lithops_codeengine.zip .
RUN unzip lithops_codeengine.zip && rm lithops_codeengine.zip

CMD ["sh", "-c", "exec gunicorn --bind :$PORT --workers $CONCURRENCY --timeout $TIMEOUT lithopsentry:proxy"]
"""


def _validate_cpu_memory(runtime_cpu, runtime_memory):
    """
    Validates that the CPU and memory pair is supported by Code Engine
    """
    min_memory, max_memory = VALID_CPU_MEMORY[runtime_cpu]
    if not min_memory <= runtime_memory <= max_memory:
        raise Exception(
            f'{runtime_memory} MB is not a valid memory value for {runtime_cpu} vCPU. '
            f'Use a value between {min_memory} and {max_memory} MB. '
            'See https://cloud.ibm.com/docs/codeengine?topic=codeengine-mem-cpu-combo'
        )


def load_config(config_data):
    """
    Loads and validates the Code Engine backend configuration
    """

    if 'ibm' not in config_data or config_data['ibm'] is None:
        raise Exception("'ibm' section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['ibm']:
            msg = f'"{param}" is mandatory in the "ibm" section of the configuration'
            raise Exception(msg)

    if not config_data.get('code_engine'):
        config_data['code_engine'] = {}

    temp = copy.deepcopy(config_data['code_engine'])
    config_data['code_engine'].update(config_data['ibm'])
    config_data['code_engine'].update(temp)

    if 'region' not in config_data['code_engine']:
        msg = (
            "'region' parameter is mandatory under the 'ibm' or "
            "'code_engine' section of the configuration"
        )
        raise Exception(msg)

    region = config_data['code_engine']['region']
    if region not in VALID_REGIONS:
        raise Exception(
            f'{region} is an invalid region name. Set one of: {VALID_REGIONS}'
        )

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['code_engine']:
            config_data['code_engine'][key] = DEFAULT_CONFIG_KEYS[key]

    runtime_cpu = config_data['code_engine']['runtime_cpu']
    if runtime_cpu not in VALID_CPU_VALUES:
        raise Exception(
            f'{runtime_cpu} is an invalid runtime cpu value. Set one of: {VALID_CPU_VALUES}'
        )

    runtime_memory = config_data['code_engine']['runtime_memory']
    if runtime_memory not in VALID_MEMORY_VALUES:
        raise Exception(
            f'{runtime_memory} is an invalid runtime memory value in MB. '
            f'Set one of: {VALID_MEMORY_VALUES}'
        )

    _validate_cpu_memory(runtime_cpu, runtime_memory)

    if 'runtime' in config_data['code_engine']:
        runtime = config_data['code_engine']['runtime']
        registry = config_data['code_engine']['docker_server']
        if runtime.count('/') == 1 and registry not in runtime:
            config_data['code_engine']['runtime'] = f'{registry}/{runtime}'

    if region and 'region' not in config_data['ibm']:
        config_data['ibm']['region'] = config_data['code_engine']['region']
