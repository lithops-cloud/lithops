#
# (C) Copyright Cloudlab URV 2020
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

RUNTIME_NAME = 'lithops-k8sjob'

CONTAINER_REGISTRY = 'docker.io'
DOCKER_PATH = shutil.which('docker')

RUNTIME_TIMEOUT = 600  # Default: 600 seconds => 10 minutes
RUNTIME_MEMORY = 256  # Default memory: 256 MB
RUNTIME_CPU = 1  # 1 vCPU
MAX_CONCURRENT_WORKERS = 1000
INVOKE_POOL_THREADS_DEFAULT = 4

DEFAULT_GROUP = "batch"
DEFAULT_VERSION = "v1"

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_k8s.zip')


DOCKERFILE_DEFAULT = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        flask \
        pika==0.13.1 \
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

ENV PYTHONUNBUFFERED TRUE

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_k8s.zip .
RUN unzip lithops_k8s.zip && rm lithops_k8s.zip
"""

JOB_DEFAULT = """
apiVersion: batch/v1
kind: Job
metadata:
  name: "<INPUT>"
  labels:
    type: lithops-runtime
spec:
  activeDeadlineSeconds: 600
  ttlSecondsAfterFinished: 60
  parallelism: 1
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: "lithops"
        image: "<INPUT>"
        command: ["python3"]
        args:
        - "/lithops/lithopsentry.py"
        - "$(ACTION)"
        - "$(PAYLOAD)"
        env:
        - name: ACTION
          value: ''
        - name: PAYLOAD
          value: ''
        - name: IDGIVER_POD_IP
          value: ''
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        resources:
          requests:
            cpu: '0.2'
            memory: 128Mi
"""


def load_config(config_data):
    if 'k8s' not in config_data:
        config_data['k8s'] = {}

    if 'cpu' not in config_data['k8s']:
        config_data['k8s']['cpu'] = RUNTIME_CPU

    if 'container_registry' not in config_data['k8s']:
        config_data['k8s']['container_registry'] = CONTAINER_REGISTRY

    if 'runtime_memory' not in config_data['serverless']:
        config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY
    if 'runtime_timeout' not in config_data['serverless']:
        config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT

    if 'runtime' in config_data['k8s']:
        config_data['serverless']['runtime'] = config_data['k8s']['runtime']
    if 'runtime' not in config_data['serverless']:
        if not DOCKER_PATH:
            raise Exception('docker command not found. Install docker or use '
                            'an already built runtime')
        if 'docker_user' not in config_data['k8s']:
            config_data['k8s']['docker_user'] = get_docker_username()
        if not config_data['k8s']['docker_user']:
            raise Exception('You must provide "docker_user" param in config '
                            'or execute "docker login"')
        docker_user = config_data['k8s']['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = '{}/{}-v{}:{}'.format(docker_user, RUNTIME_NAME, python_version, revision)
        config_data['serverless']['runtime'] = runtime_name

    else:
        if config_data['serverless']['runtime'].count('/') > 1:
            # container registry is in the provided runtime name
            cr, rn = config_data['serverless']['runtime'].split('/', 1)
            config_data['k8s']['container_registry'] = cr
            config_data['serverless']['runtime'] = rn

    config_data['serverless']['remote_invoker'] = True

    if 'workers' not in config_data['lithops'] or \
       config_data['lithops']['workers'] > MAX_CONCURRENT_WORKERS:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS

    if 'invoke_pool_threads' not in config_data['k8s']:
        config_data['k8s']['invoke_pool_threads'] = INVOKE_POOL_THREADS_DEFAULT
    config_data['serverless']['invoke_pool_threads'] = config_data['k8s']['invoke_pool_threads']
