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

import os
import sys
import shutil

from lithops.utils import version_str, get_docker_username
from lithops.version import __version__

RUNTIME_NAME = 'lithops-codeengine'

DOCKER_PATH = shutil.which('docker')

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'runtime_cpu': 0.125,  # 0.125 vCPU
    'max_workers': 1000,
    'worker_processes': 1
}

DEFAULT_GROUP = "codeengine.cloud.ibm.com"
DEFAULT_VERSION = "v1beta1"

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_codeengine.zip')

VALID_CPU_VALUES = [0.125, 0.25, 0.5, 1, 2, 4, 6, 8]
VALID_MEMORY_VALUES = [256, 512, 1024, 2048, 4096, 8192, 12288, 16384, 24576, 32768]
VALID_REGIONS = ['us-south', 'ca-tor', 'eu-de', 'eu-gb', 'jp-osa', 'jp-tok']

CLUSTER_URL = 'https://proxy.{}.codeengine.cloud.ibm.com'

DOCKERFILE_DEFAULT = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        gunicorn \
        pika \
        flask \
        gevent \
        ibm-cos-sdk \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib

ENV PORT 8080
ENV CONCURRENCY 1
ENV TIMEOUT 600
ENV PYTHONUNBUFFERED TRUE

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_codeengine.zip .
RUN unzip lithops_codeengine.zip && rm lithops_codeengine.zip

CMD exec gunicorn --bind :$PORT --workers $CONCURRENCY --timeout $TIMEOUT lithopsentry:proxy
"""

JOBDEF_DEFAULT = """
apiVersion: codeengine.cloud.ibm.com/v1beta1
kind: JobDefinition
metadata:
  name: "<INPUT>"
  labels:
    type: lithops-runtime
spec:
  arraySpec: '0'
  maxExecutionTime: 7200
  retryLimit: 3
  template:
    containers:
    - image: "<INPUT>"
      name: "<INPUT>"
      command:
      - "/usr/local/bin/python"
      args:
      - "/lithops/lithopsentry.py"
      - "$(ACTION)"
      - "$(PAYLOAD)"
      env:
      - name: ACTION
        value: ''
      - name: PAYLOAD
        valueFrom:
          configMapKeyRef:
             key: 'lithops.payload'
             name : NAME
      resources:
        requests:
          cpu: '1'
          memory: 128Mi
    imagePullSecrets:
      - name: lithops-regcred
"""


JOBRUN_DEFAULT = """
apiVersion: codeengine.cloud.ibm.com/v1beta1
kind: JobRun
metadata:
  name: "<INPUT>"
spec:
  jobDefinitionRef: "<REF>"
  jobDefinitionSpec:
    arraySpec: '1'
    maxExecutionTime: 7200
    retryLimit: 2
    template:
      containers:
      - name: "<INPUT>"
        env:
        - name: ACTION
          value: ''
        - name: PAYLOAD
          valueFrom:
            configMapKeyRef:
              key: 'lithops.payload'
              name : ''
        resources:
          requests:
            cpu: '1'
            memory: 128Mi
"""


def load_config(config_data):

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data['code_engine'].update(config_data['ibm'])

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['code_engine']:
            config_data['code_engine'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'runtime' not in config_data['code_engine']:
        if not DOCKER_PATH:
            raise Exception('docker command not found. Install docker or use '
                            'an already built runtime')
        if 'docker_user' not in config_data['code_engine']:
            config_data['code_engine']['docker_user'] = get_docker_username()
        if not config_data['code_engine']['docker_user']:
            raise Exception('You must execute "docker login" or provide "docker_user" '
                            'param in config under "code_engine" section')
        docker_user = config_data['code_engine']['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = '{}/{}-v{}:{}'.format(docker_user, RUNTIME_NAME, python_version, revision)
        config_data['code_engine']['runtime'] = runtime_name

    runtime_cpu = config_data['code_engine']['runtime_cpu']
    if runtime_cpu not in VALID_CPU_VALUES:
        raise Exception('{} is an invalid runtime cpu value. Set one of: '
                        '{}'.format(runtime_cpu, VALID_CPU_VALUES))

    runtime_memory = config_data['code_engine']['runtime_memory']
    if runtime_memory not in VALID_MEMORY_VALUES:
        raise Exception('{} is an invalid runtime memory value in MB. Set one of: '
                        '{}'.format(runtime_memory, VALID_MEMORY_VALUES))

    region = config_data['code_engine'].get('region')
    if region and region not in VALID_REGIONS:
        raise Exception('{} is an invalid region name. Set one of: '
                        '{}'.format(region, VALID_REGIONS))
