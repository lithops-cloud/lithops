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

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 10 minutes
    'master_timeout': 600,  # Default: 10 minutes
    'runtime_memory': 512,  # Default memory: 512 MB
    'runtime_cpu': 1,  # 1 vCPU
    'max_workers': 100,
    'worker_processes': 1,
    'docker_server': 'docker.io'
}

DEFAULT_GROUP = "batch"
DEFAULT_VERSION = "v1"
MASTER_NAME = "lithops-master"
MASTER_PORT = 8080

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_k8s.zip')


DOCKERFILE_DEFAULT = """
RUN apt-get update && apt-get install -y \
        zip redis-server curl \
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
        flask \
        pika \
        boto3 \
        ibm-cloud-sdk-core \
        ibm-cos-sdk \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        psutil

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
  name: lithops-worker-name
  namespace: default
  labels:
    type: lithops-worker
    version: lithops_vX.X.X
    user: lithops-user
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
            - "$(DATA)"
          env:
            - name: ACTION
              value: ''
            - name: DATA
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

POD = """
apiVersion: v1
kind: Pod
metadata:
  name: lithops-worker
spec:
  containers:
    - name: "lithops-worker"
      image: "<INPUT>"
      command: ["python3"]
      args:
        - "/lithops/lithopsentry.py"
        - "--"
        - "--"
      resources:
        requests:
          cpu: '1'
          memory: '512Mi'
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

    if config_data['k8s'].get('rabbitmq_executor', False):
        config_data['k8s']['amqp_url'] = config_data['rabbitmq']['amqp_url']
