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

DOCKER_PATH = shutil.which('docker')


DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'runtime_cpu': 0.5,  # 0.5 vCPU
    'max_workers': 200,
    'worker_processes': 1
}

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
        pika \
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
          # imagePullPolicy: IfNotPresent
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
            - name: MASTER_POD_IP
              value: ''
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
          resources:
            requests:
              cpu: '0.2'
              memory: 128Mi
            limits:
              cpu: '0.2'
              memory: 128Mi
      imagePullSecrets:
        - name: lithops-regcred
"""


def load_config(config_data):
    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['k8s']:
            config_data['k8s'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'runtime' not in config_data['k8s']:
        if not DOCKER_PATH:
            raise Exception('docker command not found. Install docker or use '
                            'an already built runtime')
        if 'docker_user' not in config_data['k8s']:
            config_data['k8s']['docker_user'] = get_docker_username()
        if not config_data['k8s']['docker_user']:
            raise Exception('You must execute "docker login" or provide "docker_user" '
                            'param in config under "k8s" section')
        docker_user = config_data['k8s']['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = '{}/{}-v{}:{}'.format(docker_user, RUNTIME_NAME, python_version, revision)
        config_data['k8s']['runtime'] = runtime_name
