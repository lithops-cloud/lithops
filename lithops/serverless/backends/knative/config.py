#
# (C) Copyright IBM Corp. 2019
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
from lithops.version import __version__
from lithops.utils import version_str, get_docker_username

RUNTIME_NAME = 'lithops-knative'

DEFAULT_GROUP = "serving.knative.dev"
DEFAULT_VERSION = "v1"

BUILD_GIT_URL = 'https://github.com/lithops-cloud/lithops'
DOCKER_PATH = shutil.which('docker')

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 600 seconds => 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'runtime_cpu': 0.5,  # 0.125 vCPU
    'max_workers': 250,
    'worker_processes': 1,
    'invoke_pool_threads': 250,
}

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_knative.zip')

DEFAULT_DOCKERFILE = """
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
        google-cloud-storage \
        google-cloud-pubsub \
        azure-storage-blob \
        azure-storage-queue \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        paramiko \
        ps-mem \
        tblib

ENV PORT 8080
ENV CONCURRENCY 4
ENV TIMEOUT 600
ENV PYTHONUNBUFFERED TRUE

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_knative.zip .
RUN unzip lithops_knative.zip && rm lithops_knative.zip

CMD exec gunicorn --bind :$PORT --workers $CONCURRENCY --timeout $TIMEOUT lithopsproxy:proxy
"""

secret_res = """
apiVersion: v1
kind: Secret
metadata:
  name: dockerhub-user-token
  annotations:
    tekton.dev/docker-0: https://index.docker.io
type: kubernetes.io/basic-auth
stringData:
  username: USER
  password: TOKEN
"""

account_res = """
apiVersion: v1
kind: ServiceAccount
metadata:
  name: lithops-build-pipeline
secrets:
- name: dockerhub-user-token
"""

git_res = """
apiVersion: tekton.dev/v1alpha1
kind: PipelineResource
metadata:
  name: lithops-git
spec:
  type: git
  params:
    - name: revision
      value: master
    - name: url
      value: https://github.com/lithops-cloud/lithops
"""

task_def = """
apiVersion: tekton.dev/v1alpha1
kind: Task
metadata:
  name: git-source-to-image
spec:
  inputs:
    resources:
      - name: git-source
        type: git
    params:
      - name: pathToContext
        description: Path to build context, within the workspace used by Kaniko
        default: /workspace/git-source/
      - name: pathToDockerFile
        description: Relative to the context
        default: Dockerfile
      - name: imageUrl
      - name: imageTag
  steps:
    - name: build-and-push
      image: gcr.io/kaniko-project/executor:v0.15.0
      env:
        - name: "DOCKER_CONFIG"
          value: "/tekton/home/.docker/"
      command:
        - /kaniko/executor
      args:
        - --dockerfile=$(inputs.params.pathToDockerFile)
        - --destination=$(inputs.params.imageUrl):$(inputs.params.imageTag)
        - --context=$(inputs.params.pathToContext)
"""

task_run = """
apiVersion: tekton.dev/v1alpha1
kind: TaskRun
metadata:
  name: lithops-runtime-from-git
spec:
  serviceAccountName: lithops-build-pipeline
  taskRef:
    name: git-source-to-image
  inputs:
    resources:
      - name: git-source
        resourceRef:
          name: lithops-git
    params:
      - name: pathToDockerFile
        value: lithops/compute/backends/knative/tekton/Dockerfile.python36
      - name: imageUrl
        value: docker.io/jsampe/lithops-knative-v36
      - name: imageTag
        value: latest
"""


service_res = """
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: lithops-runtime
  #namespace: default
spec:
  template:
    metadata:
      labels:
        type: lithops-runtime
      annotations:
        autoscaling.knative.dev/target: "1"
        autoscaling.knative.dev/minScale: "0"
        autoscaling.knative.dev/maxScale: "0"
        autoscaling.knative.dev/scaleDownDelay: "5m"
    spec:
      containerConcurrency: 1
      timeoutSeconds: 600
      containers:
        - image: IMAGE
          env:
            - name: CONCURRENCY
              value: "1"
            - name: TIMEOUT
              value: "600"
          resources:
            limits:
              memory: "256Mi"
              cpu: "1"
            requests:
              memory: "256Mi"
              cpu: "1"
      imagePullSecrets:
        - name: lithops-regcred
"""


def load_config(config_data):
    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['knative']:
            config_data['knative'][key] = DEFAULT_CONFIG_KEYS[key]

    config_data['knative']['invoke_pool_threads'] = config_data['knative']['max_workers']

    if 'git_url' not in config_data['knative']:
        config_data['knative']['git_url'] = BUILD_GIT_URL
    if 'git_rev' not in config_data['knative']:
        revision = 'master' if 'dev' in __version__ else __version__
        config_data['knative']['git_rev'] = revision

    if 'runtime' not in config_data['knative']:
        if not DOCKER_PATH:
            raise Exception('docker command not found. Install docker or use '
                            'an already built runtime')
        if 'docker_user' not in config_data['knative']:
            config_data['knative']['docker_user'] = get_docker_username()
        if not config_data['knative']['docker_user']:
            raise Exception('You must provide "docker_user" param in config '
                            'or execute "docker login"')
        docker_user = config_data['knative']['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = '{}/{}-v{}:{}'.format(docker_user, RUNTIME_NAME, python_version, revision)
        config_data['knative']['runtime'] = runtime_name
