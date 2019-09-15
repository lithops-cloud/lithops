import sys
from pywren_ibm_cloud.utils import version_str

RUNTIME_DEFAULT = '<USER>/kpywren'
DOCKER_REPO_DEFAULT = 'docker.io'
#relative to git rep home
DOCKERFILE_DEFAULT = './runtime/knative/Dockerfile'

GIT_URL_DEFAULT = 'https://github.com/pywren/pywren-ibm-cloud.git'
GIT_REV_DEFAULT = 'master'

RUNTIME_TIMEOUT_DEFAULT = 600000  # TODO
RUNTIME_MEMORY_DEFAULT = 0  # TODO

#bluemix-default-secret default name chosen for IKS
secret_res = """
apiVersion: v1
kind: Secret
metadata:
  name: bluemix-default-secret
  annotations:
    tekton.dev/docker-0: https://index.docker.io/v1/
type: kubernetes.io/basic-auth
stringData:
  username: <user/iamapikey>
  password: <pass>
"""

account_res = """
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pipeline-account
secrets:
- name: bluemix-default-secret
"""

git_res = """
apiVersion: tekton.dev/v1alpha1
kind: PipelineResource
metadata:
  name: pywren-git
spec:
  type: git
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
        default: .
      - name: pathToDockerFile
        description: Relative to the context
        default: Dockerfile
      - name: imageUrl
      - name: imageTag
  steps:
    - name: build-and-push
      image: gcr.io/kaniko-project/executor
      env:
        - name: "DOCKER_CONFIG"
          value: "/builder/home/.docker/"
      command:
        - /kaniko/executor
      args:
        - --dockerfile=${inputs.params.pathToDockerFile}
        - --destination=${inputs.params.imageUrl}:${inputs.params.imageTag}
        - --context=/workspace/git-source/${inputs.params.pathToContext}
"""

task_run = """
apiVersion: tekton.dev/v1alpha1
kind: TaskRun
metadata:
  generateName: image-from-git-
spec:
  taskRef:
    name: git-source-to-image
  inputs:
    resources:
      - name: git-source
        resourceRef:
          name: pywren-git
    params:
      - name: pathToDockerFile
        value: ./runtime/knative/Dockerfile
      - name: pathToContext
        value: .
      - name: imageTag
        value: latest
  serviceAccount: pipeline-account
"""

service_res = """
apiVersion: serving.knative.dev/v1alpha1
kind: Service
metadata:
  name: pywren-action
  namespace: default
spec:
  runLatest:
    configuration:
      revisionTemplate:
        spec:
          container:
            image: IMAGE_URL
          containerConcurrency: 1
"""

def load_config(config_data=None):
    if 'runtime_memory' not in config_data['pywren']:
        config_data['pywren']['runtime_memory'] = 0
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'docker_repo' not in config_data['knative']:
        config_data['knative']['docker_repo'] = DOCKER_REPO_DEFAULT
    
    if 'runtime' not in config_data['pywren']:
        config_data['pywren']['runtime'] = RUNTIME_DEFAULT
  
    #pass config to knative backend to load service details by init
    config_data['knative']['service_name'] = config_data['pywren']['runtime']
    
    if 'separate_preinstalls_func' not in config_data['pywren']:
        config_data['pywren']['separate_preinstalls_func'] = False  
