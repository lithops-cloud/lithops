#
# (C) Copyright IBM Corp. 2020
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
import base64
import hashlib
import json
import time
import logging
import urllib3
import copy
import yaml
from kubernetes import client, watch
from kubernetes.config import load_incluster_config
from kubernetes.client.rest import ApiException

from lithops import utils
from lithops.config import dump_yaml_config, load_yaml_config
from lithops.version import __version__
from lithops.constants import CACHE_DIR, COMPUTE_CLI_MSG, JOBS_PREFIX
from lithops.util.ibm_token_manager import IAMTokenManager

from . import config

urllib3.disable_warnings()

logger = logging.getLogger(__name__)


# Decorator to wrap a function to reinit clients and retry on except.
def retry_on_except(func):
    def decorated_func(*args, **kwargs):
        _self = args[0]
        connection_retries = _self.config.get('connection_retries')
        if not connection_retries:
            return func(*args, **kwargs)
        else:
            ex = None
            for retry in range(connection_retries):
                try:
                    return func(*args, **kwargs)
                except ApiException as e:
                    if e.status == 409:
                        ex = e
                        body = json.loads(e.body)
                        if body.get('reason') in {'AlreadyExists', 'Conflict'} or 'already exists' in body.get('message'):
                            logger.debug("Encountered conflict error {}, ignoring".format(body.get('message')))
                    elif e.status == 500:
                        ex = e
                        logger.exception((f'Got exception {e}, retrying for the {retry} time, left retries {connection_retries - 1 - retry}'))
                    else:
                        logger.debug((f'Got exception {e} when trying to invoke {func.__name__}, raising'))
                        raise e
                    time.sleep(5)
            # we got run out of retries, now raising
            raise ex
    return decorated_func


class CodeEngineBackend:
    """
    A wrap-up around Code Engine backend.
    """

    def __init__(self, ce_config, internal_storage):
        logger.debug("Creating IBM Code Engine client")
        self.name = 'code_engine'
        self.type = utils.BackendType.BATCH.value
        self.config = ce_config
        self.internal_storage = internal_storage
        self.is_lithops_worker = utils.is_lithops_worker()

        self.user_agent = ce_config['user_agent']
        self.iam_api_key = ce_config['iam_api_key']
        self.namespace = ce_config.get('namespace')
        self.region = ce_config['region']

        self.user_key = self.iam_api_key[:4].lower()
        self.project_name = ce_config.get('project_name', f'lithops-{self.region}-{self.user_key}')
        self.project_id = None

        self.config['project_name'] = self.project_name

        self.token_manager = None
        self.code_engine_service_v1 = None
        self.code_engine_service_v2 = None

        self.cache_dir = os.path.join(CACHE_DIR, self.name)
        self.cache_file = os.path.join(self.cache_dir, self.project_name + '_data')

        self.cluster = config.CLUSTER_URL.format(self.region)

        if self.is_lithops_worker:
            logger.debug('Loading incluster kubecfg')
            load_incluster_config()
            self.custom_api = client.CustomObjectsApi()
            self.core_api = client.CoreV1Api()
        else:
            self._create_k8s_iam_client()

        self.jobs = []  # list to store executed jobs (job_keys)

        msg = COMPUTE_CLI_MSG.format('IBM Code Engine')
        logger.info(f"{msg} - Project: {self.project_name} - Region: {self.region}")

    def _create_code_engine_client(self):
        """
        Creates new code engine clients
        """
        if self.code_engine_service_v1 and self.code_engine_service_v2:
            return

        from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
        from ibm_code_engine_sdk.code_engine_v2 import CodeEngineV2
        from ibm_code_engine_sdk.ibm_cloud_code_engine_v1 import IbmCloudCodeEngineV1

        authenticator = IAMAuthenticator(self.iam_api_key)
        self.code_engine_service_v1 = IbmCloudCodeEngineV1(authenticator=authenticator)
        self.code_engine_service_v1.set_service_url(config.BASE_URL_V1.format(self.region))
        self.code_engine_service_v2 = CodeEngineV2(authenticator=authenticator)
        self.code_engine_service_v2.set_service_url(config.BASE_URL_V2.format(self.region))

    def _get_or_create_namespace(self, create=True):
        """
        Gets or creates a new namespace
        """
        if self.namespace or self.is_lithops_worker:
            return self.namespace

        ce_data = load_yaml_config(self.cache_file)
        self.namespace = ce_data.get('namespace')
        self.project_id = ce_data.get('project_id')
        self.config['project_id'] = self.project_id
        self.config['namespace'] = self.namespace

        if self.namespace:
            return self.namespace

        self._create_code_engine_client()

        def get_k8s_namespace(project_id):
            delegated_refresh_token_payload = {
                'grant_type': 'urn:ibm:params:oauth:grant-type:apikey',
                'apikey': self.iam_api_key,
                'response_type': 'delegated_refresh_token',
                'receiver_client_ids': 'ce',
                'delegated_refresh_token_expiry': '3600'
            }
            token_manager = self.code_engine_service_v2.authenticator.token_manager
            request_payload = token_manager.request_payload
            token_manager.request_payload = delegated_refresh_token_payload
            iam_response = token_manager.request_token()
            token_manager.request_payload = request_payload
            delegated_refresh_token = iam_response['delegated_refresh_token']
            kc_resp = self.code_engine_service_v1.get_kubeconfig(delegated_refresh_token, project_id)
            return kc_resp.get_result()['contexts'][0]['context']['namespace']

        response = self.code_engine_service_v2.list_projects().get_result()
        if 'projects' in response:
            for project in response['projects']:
                if project['name'] == self.project_name:
                    logger.debug(f"Found Code Engine project: {self.project_name}")
                    self.project_id = project['id']
                    self.namespace = get_k8s_namespace(self.project_id)
                    self.config['project_id'] = self.project_id
                    self.config['namespace'] = self.namespace

        if not self.namespace and create:
            logger.debug(f"Creating new Code Engine project: {self.project_name}")
            response = self.code_engine_service_v2.create_project(
                name=self.project_name,
                resource_group_id=self.config['resource_group_id']
            )
            project = response.get_result()
            self.project_id = project['id']
            self.namespace = get_k8s_namespace(self.project_id)
            self.config['project_id'] = self.project_id
            self.config['namespace'] = self.namespace

        ce_data['project_name'] = self.project_name
        ce_data['project_id'] = self.project_id
        ce_data['namespace'] = self.namespace
        dump_yaml_config(self.cache_file, ce_data)

        return self.namespace

    def _create_k8s_iam_client(self):
        """
        Creates the k8s client with the IAM token
        """
        if self.is_lithops_worker:
            return

        if not self.token_manager:
            self.token_manager = IAMTokenManager(self.iam_api_key)

        token, expiry_time = self.token_manager.get_token()

        if expiry_time != self.config.get('token_expiry_time'):
            self.config['token_expiry_time'] = expiry_time

            configuration = client.Configuration.get_default_copy()
            configuration.host = self.cluster
            configuration.api_key = {"authorization": "Bearer " + token}
            client.Configuration.set_default(configuration)

            self.custom_api = client.CustomObjectsApi()
            self.core_api = client.CoreV1Api()

    def _format_jobdef_name(self, runtime_name, runtime_memory, version=__version__):
        name = f'{runtime_name}-{runtime_memory}-{version}'
        name_hash = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]

        return f'lithops-worker-{self.user_key}-{version.replace(".", "")}-{name_hash}'

    def _get_default_runtime_image_name(self):
        """
        Generates the default runtime image name
        """
        return utils.get_default_container_name(
            self.name, self.config, 'lithops-codeenigne-default'
        )

    def build_runtime(self, docker_image_name, dockerfile, extra_args=[]):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info(f'Building runtime {docker_image_name} from {dockerfile}')

        docker_path = utils.get_docker_path()

        if dockerfile:
            assert os.path.isfile(dockerfile), f'Cannot locate "{dockerfile}"'
            cmd = f'{docker_path} build --platform=linux/amd64 -t {docker_image_name} -f {dockerfile} . '
        else:
            cmd = f'{docker_path} build --platform=linux/amd64 -t {docker_image_name} . '
        cmd = cmd + ' '.join(extra_args)

        try:
            entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
            utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, 'lithopsentry.py')
            utils.run_command(cmd)
        finally:
            os.remove(config.FH_ZIP_LOCATION)

        docker_user = self.config.get("docker_user")
        docker_password = self.config.get("docker_password")
        docker_server = self.config.get("docker_server")

        logger.debug(f'Pushing runtime {docker_image_name} to container registry')

        if docker_user and docker_password:
            logger.debug('Container registry credentials found in config. Logging in into the registry')
            cmd = f'{docker_path} login -u {docker_user} --password-stdin {docker_server}'
            utils.run_command(cmd, input=docker_password)

        if utils.is_podman(docker_path):
            cmd = f'{docker_path} push {docker_image_name} --format docker --remove-signatures'
        else:
            cmd = f'{docker_path} push {docker_image_name}'
        utils.run_command(cmd)

        logger.debug('Building done!')

    def _build_default_runtime(self, default_runtime_img_name):
        """
        Builds the default runtime
        """
        # Build default runtime using local dokcer
        dockerfile = "Dockefile.default-ce-runtime"
        python_version = utils.CURRENT_PY_VERSION
        base_image = "slim-buster" if int(python_version.split('.')[1]) < 13 else "bookworm"
        with open(dockerfile, 'w') as f:
            f.write(f"FROM python:{python_version}-{base_image}\n")
            f.write(config.DOCKERFILE_DEFAULT)
        try:
            self.build_runtime(default_runtime_img_name, dockerfile)
        finally:
            os.remove(dockerfile)

    def deploy_runtime(self, docker_image_name, memory, timeout):
        """
        Deploys a new runtime from an already built Docker image
        """
        self._get_or_create_namespace()

        try:
            default_image_name = self._get_default_runtime_image_name()
        except Exception:
            default_image_name = None

        if docker_image_name == default_image_name:
            self._build_default_runtime(docker_image_name)

        logger.debug(f"Deploying runtime: {docker_image_name} - Memory: {memory} Timeout: {timeout}")
        self._create_k8s_iam_client()
        self._create_job_definition(docker_image_name, memory, timeout)
        runtime_meta = self._generate_runtime_meta(docker_image_name, memory)

        return runtime_meta

    def delete_runtime(self, runtime_name, memory, version=__version__):
        """
        Deletes a runtime
        We need to delete job definition
        """
        if not self._get_or_create_namespace(create=False):
            logger.info(f"Project {self.project_name} does not exist")
            return

        logger.info(f'Deleting runtime: {runtime_name} - {memory}MB')
        self._create_k8s_iam_client()
        try:
            jobdef_id = self._format_jobdef_name(runtime_name, memory, version)
            self.custom_api.delete_namespaced_custom_object(
                group=config.DEFAULT_GROUP,
                version=config.DEFAULT_VERSION,
                name=jobdef_id,
                namespace=self.namespace,
                plural="jobdefinitions",
                body=client.V1DeleteOptions(),
            )
        except ApiException as e:
            logger.debug(f"Deleting a jobdef failed with {e.status} {e.reason}")

    def clean(self, all=False):
        """
        Deletes all runtimes from all packages
        """
        logger.info(f'Cleaning project {self.project_name}')
        if not self._get_or_create_namespace(create=False):
            logger.info(f"Project {self.project_name} does not exist")
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
            return

        self._create_k8s_iam_client()
        self.clear()
        runtimes = self.list_runtimes()
        for image_name, memory, version, fn_name in runtimes:
            self.delete_runtime(image_name, memory, version)

        logger.debug('Deleting all lithops configmaps')
        configmaps = self.core_api.list_namespaced_config_map(namespace=self.namespace)
        for configmap in configmaps.items:
            config_name = configmap.metadata.name
            if config_name.startswith('lithops'):
                logger.debug(f'Deleting configmap {config_name}')
                self.core_api.delete_namespaced_config_map(
                    name=config_name,
                    namespace=self.namespace,
                    grace_period_seconds=0)

        if all and os.path.exists(self.cache_file):
            self._create_code_engine_client()
            logger.info(f"Deleting Code Engine project: {self.project_name}")
            self.code_engine_service_v2.delete_project(id=self.project_id)
            os.remove(self.cache_file)

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes
        return: list of tuples (docker_image_name, memory)
        """
        runtimes = []

        if not self._get_or_create_namespace(create=False):
            logger.info(f"Project {self.project_name} does not exist")
            return runtimes

        self._create_k8s_iam_client()

        try:
            jobdefs = self.custom_api.list_namespaced_custom_object(
                group=config.DEFAULT_GROUP,
                version=config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobdefinitions"
            )
        except ApiException as e:
            logger.debug(f"List all jobdefinitions failed with {e.status} {e.reason}")
            return runtimes

        for jobdef in jobdefs['items']:
            try:
                if not jobdef['metadata']['name'].startswith(f'lithops-worker-{self.user_key}'):
                    continue
                if not jobdef['metadata']['labels']['type'] == 'lithops-runtime':
                    continue
                fn_name = jobdef['metadata']['name']
                version = jobdef['metadata']['labels']['version'].replace('lithops_v', '')
                container = jobdef['spec']['template']['containers'][0]
                image_name = container['image']
                memory = container['resources']['requests']['memory'].replace('M', '')
                memory = int(int(memory) / 1000 * 1024)
                if docker_image_name in image_name or docker_image_name == 'all':
                    runtimes.append((image_name, memory, version, fn_name))
            except Exception:
                pass

        return runtimes

    def clear(self, job_keys=None):
        """
        Clean all completed jobruns in the current executor
        """
        if not self._get_or_create_namespace(create=False):
            logger.info(f"Project {self.project_name} does not exist")
            return

        self._create_k8s_iam_client()
        jobs_to_delete = job_keys or self.jobs
        for job_key in jobs_to_delete:
            try:
                jobrun_name = f'lithops-{job_key.lower()}'
                self.custom_api.delete_namespaced_custom_object(
                    group=config.DEFAULT_GROUP,
                    version=config.DEFAULT_VERSION,
                    name=jobrun_name,
                    namespace=self.namespace,
                    plural="jobruns",
                    body=client.V1DeleteOptions(),
                )
                self._delete_config_map(jobrun_name)
            except ApiException as e:
                logger.debug(f"Deleting a jobrun failed with {e.status} {e.reason}")
            try:
                self.jobs.remove(job_key)
            except ValueError:
                pass

    def invoke(self, docker_image_name, runtime_memory, job_payload):
        """
        Invoke -- return information about this invocation
        For array jobs only remote_invocator is allowed
        """
        self._get_or_create_namespace()
        self._create_k8s_iam_client()

        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']

        job_key = job_payload['job_key']
        self.jobs.append(job_key)

        total_calls = job_payload['total_calls']
        chunksize = job_payload['chunksize']
        max_workers = job_payload['max_workers']

        # Make sure only max_workers are started
        total_workers = total_calls // chunksize + (total_calls % chunksize > 0)
        if max_workers < total_workers:
            chunksize = total_calls // max_workers + (total_calls % max_workers > 0)
            total_workers = total_calls // chunksize + (total_calls % chunksize > 0)
            job_payload['chunksize'] = chunksize

        logger.debug(
            f'ExecutorID {executor_id} | JobID {job_id} - Required Workers: {total_workers}'
        )

        jobdef_name = self._format_jobdef_name(docker_image_name, runtime_memory)

        if not self._job_def_exists(jobdef_name):
            jobdef_name = self._create_job_definition(docker_image_name, runtime_memory)

        jobrun_res = yaml.safe_load(config.JOBRUN_DEFAULT)

        activation_id = f'lithops-{job_key.lower()}'

        jobrun_res['metadata']['name'] = activation_id
        jobrun_res['metadata']['namespace'] = self.namespace

        jobrun_res['spec']['jobDefinitionRef'] = str(jobdef_name)
        jobrun_res['spec']['jobDefinitionSpec']['arraySpec'] = '0-' + str(total_workers - 1)
        jobrun_res['spec']['jobDefinitionSpec']['maxExecutionTime'] = self.config['runtime_timeout']

        container = jobrun_res['spec']['jobDefinitionSpec']['template']['containers'][0]
        container['name'] = str(jobdef_name)
        container['env'][0]['value'] = 'run'

        config_map = self._create_config_map(activation_id, job_payload)
        container['env'][1]['valueFrom']['configMapKeyRef']['name'] = config_map

        container['resources']['requests']['memory'] = f'{runtime_memory/1024}G'
        container['resources']['requests']['cpu'] = str(self.config['runtime_cpu'])

        logger.debug('ExecutorID {} | JobID {} - Going to run {} activations '
                     '{} workers'.format(executor_id, job_id, total_calls, total_workers))

        self._run_job(jobrun_res)

        # logger.debug(f"response - {res}")

        return activation_id

    @retry_on_except
    def _run_job(self, jobrun_res):
        self.custom_api.create_namespaced_custom_object(
            group=config.DEFAULT_GROUP,
            version=config.DEFAULT_VERSION,
            namespace=self.namespace,
            plural="jobruns",
            body=jobrun_res,
        )

    def _create_container_registry_secret(self):
        """
        Create the container registry secret in the cluster
        (only if credentials are present in config)
        """
        if not all(key in self.config for key in ["docker_user", "docker_password"]):
            return

        logger.debug('Creating container registry secret')
        docker_server = self.config['docker_server']
        docker_user = self.config['docker_user']
        docker_password = self.config['docker_password']

        cred_payload = {
            "auths": {
                docker_server: {
                    "Username": docker_user,
                    "Password": docker_password
                }
            }
        }

        data = {
            ".dockerconfigjson": base64.b64encode(
                json.dumps(cred_payload).encode()
            ).decode()
        }

        secret = client.V1Secret(
            api_version="v1",
            data=data,
            kind="Secret",
            metadata=dict(name="lithops-regcred", namespace=self.namespace),
            type="kubernetes.io/dockerconfigjson",
        )

        try:
            self.core_api.delete_namespaced_secret("lithops-regcred", self.namespace)
        except ApiException:
            pass

        try:
            self.core_api.create_namespaced_secret(self.namespace, secret)
        except ApiException as e:
            if e.status != 409:
                raise e

    @retry_on_except
    def _create_job_definition(self, docker_image_name, runtime_memory, timeout=None):
        """
        Creates a Job definition
        """
        self._create_container_registry_secret()

        jobdef_name = self._format_jobdef_name(docker_image_name, runtime_memory)
        logger.debug(f"Creating job definition {jobdef_name}")

        jobdef_res = yaml.safe_load(config.JOBDEF_DEFAULT)

        jobdef_res['metadata']['name'] = jobdef_name
        jobdef_res['metadata']['labels']['version'] = 'lithops_v' + __version__
        jobdef_res['spec']['maxExecutionTime'] = timeout or self.config['runtime_timeout']

        container = jobdef_res['spec']['template']['containers'][0]
        container['image'] = docker_image_name
        container['name'] = jobdef_name
        container['env'][0]['value'] = 'run'
        container['resources']['requests']['memory'] = f'{runtime_memory/1024}G'
        container['resources']['requests']['cpu'] = str(self.config['runtime_cpu'])

        if not all(key in self.config for key in ["docker_user", "docker_password"]):
            del jobdef_res['spec']['template']['imagePullSecrets']

        try:
            self.custom_api.delete_namespaced_custom_object(
                group=config.DEFAULT_GROUP,
                version=config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobdefinitions",
                name=jobdef_name,
            )
        except ApiException as e:
            if e.status == 404:
                pass
            else:
                raise e

        while self._job_def_exists(jobdef_name):
            time.sleep(1)

        try:
            self.custom_api.create_namespaced_custom_object(
                group=config.DEFAULT_GROUP,
                version=config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobdefinitions",
                body=jobdef_res,
            )
        except ApiException as e:
            raise e

        logger.debug(f'Job Definition {jobdef_name} created')

        return jobdef_name

    def get_runtime_key(self, docker_image_name, runtime_memory, version=__version__):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        self._get_or_create_namespace()
        jobdef_name = self._format_jobdef_name(docker_image_name, 256, version)
        runtime_key = os.path.join(self.name, version, self.region, self.namespace, jobdef_name)

        return runtime_key

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if 'runtime' not in self.config or self.config['runtime'] == 'default':
            self.config['runtime'] = self._get_default_runtime_image_name()

        runtime_info = {
            'runtime_name': self.config['runtime'],
            'runtime_cpu': self.config['runtime_cpu'],
            'runtime_memory': self.config['runtime_memory'],
            'runtime_timeout': self.config['runtime_timeout'],
            'max_workers': self.config['max_workers'],
        }

        return runtime_info

    @retry_on_except
    def _job_def_exists(self, jobdef_name):
        logger.debug(f"Checking if job definition {jobdef_name} already exists")
        try:
            self.custom_api.get_namespaced_custom_object(
                group=config.DEFAULT_GROUP,
                version=config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobdefinitions",
                name=jobdef_name
            )
        except ApiException as e:
            if e.status == 404:
                logger.debug(f"Job definition {jobdef_name} not found (404)")
                return False
            else:
                raise e

        logger.debug(f"Job definition {jobdef_name} found")
        return True

    def _generate_runtime_meta(self, docker_image_name, memory):

        logger.info(f"Extracting metadata from: {docker_image_name}")
        jobrun_res = yaml.safe_load(config.JOBRUN_DEFAULT)

        jobdef_name = self._format_jobdef_name(docker_image_name, memory)
        jobrun_name = 'lithops-runtime-metadata'

        job_payload = copy.deepcopy(self.internal_storage.storage.config)
        job_payload['log_level'] = logger.getEffectiveLevel()
        job_payload['runtime_name'] = jobdef_name

        jobrun_res['metadata']['name'] = jobrun_name
        jobrun_res['metadata']['namespace'] = self.namespace
        jobrun_res['spec']['jobDefinitionRef'] = str(jobdef_name)
        container = jobrun_res['spec']['jobDefinitionSpec']['template']['containers'][0]
        container['name'] = str(jobdef_name)
        container['env'][0]['value'] = 'metadata'

        config_map_name = f'lithops-{jobdef_name}-metadata'
        config_map_name = self._create_config_map(config_map_name, job_payload)
        container['env'][1]['valueFrom']['configMapKeyRef']['name'] = config_map_name

        try:
            self.custom_api.delete_namespaced_custom_object(
                group=config.DEFAULT_GROUP,
                version=config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobruns",
                name=jobrun_name
            )
        except Exception:
            pass

        try:
            self.custom_api.create_namespaced_custom_object(
                group=config.DEFAULT_GROUP,
                version=config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobruns",
                body=jobrun_res,
            )
        except Exception:
            pass

        logger.debug("Waiting for runtime metadata")

        done = False
        failed = False
        failed_message = ""

        while not done and not failed:
            try:
                w = watch.Watch()
                for event in w.stream(self.custom_api.list_namespaced_custom_object,
                                      namespace=self.namespace, group=config.DEFAULT_GROUP,
                                      version=config.DEFAULT_VERSION, plural="jobruns",
                                      field_selector=f"metadata.name={jobrun_name}",
                                      timeout_seconds=10):
                    failed = int(event['object'].get('status')['failed'])
                    done = int(event['object'].get('status')['succeeded'])
                    logger.debug('...')
                    if failed:
                        try:
                            pod_description = self.core_api.read_namespaced_pod(
                                name=f'{jobrun_name}-1-0', namespace=self.namespace
                            )
                            failed_message = pod_description.status.container_statuses[0].state.terminated.message
                        except Exception:
                            pass
                    if done or failed:
                        w.stop()
            except Exception:
                pass

        if done:
            logger.debug("Runtime metadata generated successfully")

        try:
            self.custom_api.delete_namespaced_custom_object(
                group=config.DEFAULT_GROUP,
                version=config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobruns",
                name=jobrun_name
            )
        except Exception:
            pass

        self._delete_config_map(config_map_name)

        if failed:
            raise Exception(f"Unable to extract Python preinstalled modules from the runtime: {failed_message}")

        data_key = '/'.join([JOBS_PREFIX, jobdef_name + '.meta'])
        json_str = self.internal_storage.get_data(key=data_key)
        runtime_meta = json.loads(json_str.decode("ascii"))
        self.internal_storage.del_data(key=data_key)

        return runtime_meta

    @retry_on_except
    def _create_config_map(self, config_map_name, payload):
        """
        Creates a configmap
        """
        cmap = client.V1ConfigMap()
        cmap.metadata = client.V1ObjectMeta(name=config_map_name)
        cmap.data = {}
        cmap.data["lithops.payload"] = utils.dict_to_b64str(payload)

        logger.debug(f"Creating ConfigMap {config_map_name}")

        self.core_api.create_namespaced_config_map(
            namespace=self.namespace,
            body=cmap,
            field_manager='lithops'
        )

        return config_map_name

    def _delete_config_map(self, config_map_name):
        """
        Deletes a configmap
        """
        grace_period_seconds = 0
        try:
            logger.debug(f"Deleting ConfigMap {config_map_name}")
            self.core_api.delete_namespaced_config_map(
                name=config_map_name,
                namespace=self.namespace,
                grace_period_seconds=grace_period_seconds
            )
        except ApiException as e:
            logger.debug(f"Deleting a configmap failed with {e.status} {e.reason}")
