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
import subprocess as sp

from lithops.utils import version_str
from lithops.version import __version__

RUNTIME_NAME = 'lithops-codeengine'

CONTAINER_REGISTRY = 'docker.io'
DOCKER_PATH = shutil.which('docker')

RUNTIME_TIMEOUT = 600  # Default: 600 seconds => 10 minutes
RUNTIME_MEMORY = 256  # Default memory: 256 MB
RUNTIME_CPU = 1  # 1 vCPU
MAX_CONCURRENT_WORKERS = 1000

DEFAULT_GROUP = "codeengine.cloud.ibm.com"
DEFAULT_VERSION = "v1beta1"

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_codeengine.zip')


DOCKERFILE_DEFAULT = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        gunicorn \
        pika==0.13.1 \
        flask \
        gevent \
        glob2 \
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
ENV CONCURRENCY 4
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
    if 'code_engine' not in config_data:
        config_data['code_engine'] = {}

    if 'cpu' not in config_data['code_engine']:
        config_data['code_engine']['cpu'] = RUNTIME_CPU

    if 'container_registry' not in config_data['code_engine']:
        config_data['code_engine']['container_registry'] = CONTAINER_REGISTRY

    if 'runtime_memory' not in config_data['serverless']:
        config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY
    if 'runtime_timeout' not in config_data['serverless']:
        config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT

    if 'runtime' not in config_data['serverless']:
        if not DOCKER_PATH:
            raise Exception('docker command not found. Install docker or use '
                            'an already built runtime')
        if 'docker_user' not in config_data['code_engine']:
            cmd = "{} info".format(DOCKER_PATH)
            docker_user_info = sp.check_output(cmd, shell=True, encoding='UTF-8',
                                               stderr=sp.STDOUT)
            for line in docker_user_info.splitlines():
                if 'Username' in line:
                    _, useranme = line.strip().split(':')
                    config_data['code_engine']['docker_user'] = useranme.strip()
                    break

        if 'docker_user' not in config_data['code_engine']:
            raise Exception('You must provide "docker_user" param in config '
                            'or execute "docker login"')

        docker_user = config_data['code_engine']['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = '{}/{}-v{}:{}'.format(docker_user, RUNTIME_NAME, python_version, revision)
        config_data['serverless']['runtime'] = runtime_name

    else:
        if config_data['serverless']['runtime'].count('/') > 1:
            # container registry is in the provided runtime name
            cr, rn = config_data['serverless']['runtime'].split('/', 1)
            config_data['code_engine']['container_registry'] = cr
            config_data['serverless']['runtime'] = rn

    config_data['serverless']['remote_invoker'] = True

    if 'workers' not in config_data['lithops'] or \
       config_data['lithops']['workers'] > MAX_CONCURRENT_WORKERS:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS
