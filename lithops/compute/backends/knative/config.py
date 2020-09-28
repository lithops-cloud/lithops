#
# (C) Copyright IBM Corp. 2019
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
from lithops.version import __version__
from lithops.utils import version_str

DOCKER_REPO_DEFAULT = 'docker.io'
RUNTIME_NAME_DEFAULT = 'lithops-knative'

BUILD_GIT_URL_DEFAULT = 'https://github.com/lithops-cloud/lithops'

RUNTIME_TIMEOUT_DEFAULT = 600  # 10 minutes
RUNTIME_MEMORY_DEFAULT = 256  # 256Mi
RUNTIME_CPU_DEFAULT = 1000  # 1 vCPU
CONCURRENT_WORKERS_DEFAULT = 100

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_knative.zip')

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
apiVersion: serving.knative.dev/v1alpha1
kind: Service
metadata:
  name: lithops-runtime
  #namespace: default
spec:
  template:
    metadata:
      labels:
        type: lithops-runtime
      #annotations:
        # Target 1 in-flight-requests per pod.
        #autoscaling.knative.dev/target: "1"
        #autoscaling.knative.dev/minScale: "0"
        #autoscaling.knative.dev/maxScale: "1000"
    spec:
      containerConcurrency: 1
      timeoutSeconds: TIMEOUT
      containers:
        - image: IMAGE
          resources:
            limits:
              memory: MEMORY
              #cpu: 1000m
"""


def load_config(config_data):
    if 'knative' not in config_data:
        raise Exception("knative section is mandatory in configuration")

    required_keys = ('docker_user',)
    if not set(required_keys) <= set(config_data['knative']):
        raise Exception('You must provide {} to access to Knative'.format(required_keys))

    if 'git_url' not in config_data['knative']:
        config_data['knative']['git_url'] = BUILD_GIT_URL_DEFAULT
    if 'git_rev' not in config_data['knative']:
        revision = 'master' if 'SNAPSHOT' in __version__ else __version__
        config_data['knative']['git_rev'] = revision

    if 'cpu' not in config_data['knative']:
        config_data['knative']['cpu'] = RUNTIME_CPU_DEFAULT

    if 'runtime_memory' not in config_data['lithops']:
        config_data['lithops']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['lithops']:
        config_data['lithops']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'docker_repo' not in config_data['knative']:
        config_data['knative']['docker_repo'] = DOCKER_REPO_DEFAULT

    if 'runtime' not in config_data['lithops']:
        docker_user = config_data['knative']['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'SNAPSHOT' in __version__ else __version__.replace('.', '')
        runtime_name = '{}/{}-v{}:{}'.format(docker_user, RUNTIME_NAME_DEFAULT, python_version, revision)
        config_data['lithops']['runtime'] = runtime_name

    if 'workers' not in config_data['lithops']:
        config_data['lithops']['workers'] = CONCURRENT_WORKERS_DEFAULT

    if 'ibm_cos' in config_data and 'private_endpoint' in config_data['ibm_cos']:
        del config_data['ibm_cos']['private_endpoint']
