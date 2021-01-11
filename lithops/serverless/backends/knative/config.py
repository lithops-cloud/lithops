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
import subprocess as sp
from lithops.version import __version__
from lithops.utils import version_str

CONTAINER_REGISTRY = 'docker.io'
RUNTIME_NAME = 'lithops-knative'

DEFAULT_GROUP = "serving.knative.dev"
DEFAULT_VERSION = "v1"

BUILD_GIT_URL = 'https://github.com/lithops-cloud/lithops'
DOCKER_PATH = shutil.which('docker')
RUNTIME_TIMEOUT = 600  # 10 minutes
RUNTIME_MEMORY = 256  # 256Mi
RUNTIME_CPU = 1  # 1 vCPU
RUNTIME_MIN_INSTANCES = 0
RUNTIME_MAX_INSTANCES = 250
RUNTIME_CONCURRENCY = 1

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_knative.zip')

DEFAULT_DOCKERFILE = """
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
        autoscaling.knative.dev/maxScale: "250"
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
"""


def load_config(config_data):
    if 'knative' not in config_data or not config_data['knative']:
        config_data['knative'] = {}

    if 'git_url' not in config_data['knative']:
        config_data['knative']['git_url'] = BUILD_GIT_URL
    if 'git_rev' not in config_data['knative']:
        revision = 'master' if 'dev' in __version__ else __version__
        config_data['knative']['git_rev'] = revision
    if 'container_registry' not in config_data['knative']:
        config_data['knative']['container_registry'] = CONTAINER_REGISTRY

    if 'cpu' not in config_data['knative']:
        config_data['knative']['cpu'] = RUNTIME_CPU
    if 'concurrency' not in config_data['knative']:
        config_data['knative']['concurrency'] = RUNTIME_CONCURRENCY
    if 'min_instances' not in config_data['knative']:
        config_data['knative']['min_instances'] = RUNTIME_MIN_INSTANCES
    if 'max_instances' not in config_data['knative']:
        config_data['knative']['max_instances'] = RUNTIME_MAX_INSTANCES

    if 'runtime_memory' not in config_data['serverless']:
        config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY
    if 'runtime_timeout' not in config_data['serverless']:
        config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT

    if 'runtime' not in config_data['serverless']:
        if 'docker_user' not in config_data['knative']:
            cmd = "{} info".format(DOCKER_PATH)
            docker_user_info = sp.check_output(cmd, shell=True, encoding='UTF-8',
                                               stderr=sp.STDOUT)
            for line in docker_user_info.splitlines():
                if 'Username' in line:
                    _, useranme = line.strip().split(':')
                    config_data['knative']['docker_user'] = useranme.strip()
                    break

        if 'docker_user' not in config_data['knative']:
            raise Exception('You must provide "docker_user" param in config '
                            'or execute "docker login"')

        docker_user = config_data['knative']['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = '{}/{}-v{}:{}'.format(docker_user, RUNTIME_NAME, python_version, revision)
        config_data['serverless']['runtime'] = runtime_name
    else:
        if config_data['serverless']['runtime'].count('/') > 1:
            # container registry is in the provided runtime name
            cr, rn = config_data['serverless']['runtime'].split('/', 1)
            config_data['knative']['container_registry'] = cr
            config_data['serverless']['runtime'] = rn

    if 'workers' not in config_data['lithops']:
        max_instances = config_data['knative']['max_instances']
        concurrency = config_data['knative']['concurrency']
        config_data['lithops']['workers'] = int(max_instances * concurrency)
