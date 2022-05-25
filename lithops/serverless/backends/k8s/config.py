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
from lithops.version import __version__

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'runtime_cpu': 0.5,  # 0.5 vCPU
    'max_workers': 200,
    'worker_processes': 1,
    'docker_server': 'docker.io'
}

DEFAULT_GROUP = "batch"
DEFAULT_VERSION = "v1"

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_k8s.zip')


DOCKERFILE_DEFAULT = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
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
  name: lithops-runtime-name
  namespace: default
  labels:
    type: lithops-runtime
    version: lithops_vX.X.X
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

    if 'runtime' in config_data['k8s']:
        runtime = config_data['k8s']['runtime']
        registry = config_data['k8s']['docker_server']
        if runtime.count('/') == 1 and registry not in runtime:
            config_data['k8s']['runtime'] = f'{registry}/{runtime}'
