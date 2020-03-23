import os
import sys
from pywren_ibm_cloud.version import __version__
from pywren_ibm_cloud.utils import version_str

DOCKER_REPO_DEFAULT = 'docker.io'
RUNTIME_NAME_DEFAULT = 'pywren-knative'

BUILD_GIT_URL_DEFAULT = 'https://github.com/pywren/pywren-ibm-cloud'

RUNTIME_TIMEOUT_DEFAULT = 600  # 10 minutes
RUNTIME_MEMORY_DEFAULT = 256  # 256Mi
CONCURRENT_WORKERS_DEFAULT = 100

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'pywren_knative.zip')

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
  name: pywren-build-pipeline
secrets:
- name: dockerhub-user-token
"""

git_res = """
apiVersion: tekton.dev/v1alpha1
kind: PipelineResource
metadata:
  name: pywren-git
spec:
  type: git
  params:
    - name: revision
      value: master
    - name: url
      value: https://github.com/pywren/pywren-ibm-cloud
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
  name: image-from-git
spec:
  serviceAccountName: pywren-build-pipeline
  taskRef:
    name: git-source-to-image
  inputs:
    resources:
      - name: git-source
        resourceRef:
          name: pywren-git
    params:
      - name: pathToDockerFile
        value: pywren_ibm_cloud/compute/backends/knative/Dockerfile
"""


service_res = """
apiVersion: serving.knative.dev/v1alpha1
kind: Service
metadata:
  name: pywren-runtime
  #namespace: default
spec:
  template:
    metadata:
      labels:
        type: pywren-runtime
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

    required_keys = ('docker_user', 'docker_token')
    if not set(required_keys) <= set(config_data['knative']):
        raise Exception('You must provide {} to access to Knative'.format(required_keys))

    if 'git_url' not in config_data['knative']:
        config_data['knative']['git_url'] = BUILD_GIT_URL_DEFAULT
    if 'git_rev' not in config_data['knative']:
        revision = 'master' if 'SNAPSHOT' in __version__ else __version__
        config_data['knative']['git_rev'] = revision

    if 'runtime_memory' not in config_data['pywren']:
        config_data['pywren']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'docker_repo' not in config_data['knative']:
        config_data['knative']['docker_repo'] = DOCKER_REPO_DEFAULT

    if 'runtime' not in config_data['pywren']:
        docker_user = config_data['knative']['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'SNAPSHOT' in __version__ else __version__
        runtime_name = '{}/{}-v{}:{}'.format(docker_user, RUNTIME_NAME_DEFAULT, python_version, revision)
        config_data['pywren']['runtime'] = runtime_name

    if 'workers' not in config_data['pywren']:
        config_data['pywren']['workers'] = CONCURRENT_WORKERS_DEFAULT
