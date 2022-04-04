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
import sys
import base64
import json
import time
import logging
import urllib3
import copy
import yaml
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

from lithops.utils import version_str, dict_to_b64str, is_lithops_worker
from lithops.version import __version__
from lithops.utils import create_handler_zip
from lithops.constants import COMPUTE_CLI_MSG, JOBS_PREFIX
from . import config as ce_config
from lithops.util.ibm_token_manager import IBMTokenManager


urllib3.disable_warnings()

logger = logging.getLogger(__name__)

# Decorator to wrap a function to reinit clients and retry on except.
def retry_on_except(func):
    def decorated_func(*args, **kwargs):
        _self = args[0]
        connection_retries = _self.code_engine_config.get('connection_retries')
        if not connection_retries:
            return func(*args, **kwargs)
        else:
            ex = None
            for retry in range(connection_retries):
                try:
                    return func(*args, **kwargs)
                except ApiException as e:
                    if e.status == 409:
                        body = json.loads(e.body)
                        if body.get('reason') == 'AlreadyExists' or 'already exists' in body.get('message'):
                            logger.debug("Encountered conflict error {}, ignoring".format(body.get('message')))
                            return
                    if e.status == 500:
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

    def __init__(self, code_engine_config, internal_storage):
        logger.debug("Creating IBM Code Engine client")
        self.name = 'code_engine'
        self.type = 'batch'
        self.code_engine_config = code_engine_config
        self.internal_storage = internal_storage

        self.kubecfg_path = code_engine_config.get('kubecfg_path')
        self.user_agent = code_engine_config['user_agent']

        self.iam_api_key = code_engine_config.get('iam_api_key', None)
        self.namespace = code_engine_config.get('namespace', None)
        self.region = code_engine_config.get('region', None)

        self.ibm_token_manager = None
        self.is_lithops_worker = is_lithops_worker()

        if self.namespace and self.region:
            self.cluster = ce_config.CLUSTER_URL.format(self.region)

        if self.iam_api_key and not self.is_lithops_worker:
            self._get_iam_token()

        else:
            try:
                config.load_kube_config(config_file=self.kubecfg_path)
                logger.debug("Loading kubecfg file")
                contexts = config.list_kube_config_contexts(config_file=self.kubecfg_path)
                current_context = contexts[1].get('context')
                self.namespace = current_context.get('namespace')
                self.cluster = current_context.get('cluster')

                if self.iam_api_key:
                    self._get_iam_token()

            except Exception:
                logger.debug('Loading incluster kubecfg')
                config.load_incluster_config()

        self.code_engine_config['namespace'] = self.namespace
        self.code_engine_config['cluster'] = self.cluster
        logger.debug("Set namespace to {}".format(self.namespace))
        logger.debug("Set cluster to {}".format(self.cluster))

        self.custom_api = client.CustomObjectsApi()
        self.core_api = client.CoreV1Api()

        try:
            self.region = self.cluster.split('//')[1].split('.')[1]
        except Exception:
            self.region = self.cluster.replace('http://', '').replace('https://', '')

        self.jobs = []  # list to store executed jobs (job_keys)

        msg = COMPUTE_CLI_MSG.format('IBM Code Engine')
        logger.info("{} - Region: {}".format(msg, self.region))

    @retry_on_except
    def _get_iam_token(self):
        """ Requests an IBM IAM token """
        configuration = client.Configuration.get_default_copy()
        if self.namespace and self.region:
            configuration.host = self.cluster

        if not self.ibm_token_manager:
            token = self.code_engine_config.get('token', None)
            token_expiry_time = self.code_engine_config.get('token_expiry_time', None)
            self.ibm_token_manager = IBMTokenManager(self.iam_api_key,
                                                     'IAM', token,
                                                     token_expiry_time)

        token, token_expiry_time = self.ibm_token_manager.get_token()
        self.code_engine_config['token'] = token
        self.code_engine_config['token_expiry_time'] = token_expiry_time

        configuration.api_key = {"authorization": "Bearer " + token}
        client.Configuration.set_default(configuration)

    def _format_jobdef_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '--')
        runtime_name = runtime_name.replace(':', '--')
        runtime_name = runtime_name.replace('.', '')
        runtime_name = runtime_name.replace('_', '-')
        return '{}--{}mb'.format(runtime_name, runtime_memory)

    def _get_default_runtime_image_name(self):
        docker_user = self.code_engine_config.get('docker_user')
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        return '{}/{}-v{}:{}'.format(docker_user, ce_config.RUNTIME_NAME, python_version, revision)

    def _delete_function_handler_zip(self):
        os.remove(ce_config.FH_ZIP_LOCATION)

    def build_runtime(self, docker_image_name, dockerfile, extra_args=[]):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.debug('Building new docker image from Dockerfile')
        logger.debug('Docker image name: {}'.format(docker_image_name))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        create_handler_zip(ce_config.FH_ZIP_LOCATION, entry_point, 'lithopsentry.py')

        if dockerfile:
            cmd = '{} build -t {} -f {} . '.format(ce_config.DOCKER_PATH,
                                                   docker_image_name,
                                                   dockerfile)
        else:
            cmd = '{} build -t {} . '.format(ce_config.DOCKER_PATH, docker_image_name)

        cmd = cmd+' '.join(extra_args)

        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        logger.info('Building runtime')
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        self._delete_function_handler_zip()

        cmd = '{} push {}'.format(ce_config.DOCKER_PATH, docker_image_name)
        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')
        logger.debug('Building done!')

    def _build_default_runtime(self, default_runtime_img_name):
        """
        Builds the default runtime
        """
        if os.system('{} --version >{} 2>&1'.format(ce_config.DOCKER_PATH, os.devnull)) == 0:
            # Build default runtime using local dokcer
            python_version = version_str(sys.version_info)
            dockerfile = "Dockefile.default-codeengine-runtime"
            with open(dockerfile, 'w') as f:
                f.write("FROM python:{}-slim-buster\n".format(python_version))
                f.write(ce_config.DOCKERFILE_DEFAULT)
            self.build_runtime(default_runtime_img_name, dockerfile)
            os.remove(dockerfile)
        else:
            raise Exception('docker command not found. Install docker or use '
                            'an already built runtime')

    def deploy_runtime(self, docker_image_name, memory, timeout):
        """
        Deploys a new runtime from an already built Docker image
        """
        default_runtime_img_name = self._get_default_runtime_image_name()
        if docker_image_name in ['default', default_runtime_img_name]:
            # We only build the default image. rest of images must already exist
            # in the docker registry.
            docker_image_name = default_runtime_img_name
            self._build_default_runtime(default_runtime_img_name)

        logger.debug(f"Deploying runtime: {docker_image_name} - Memory: {memory} Timeout: {timeout}")
        self._create_job_definition(docker_image_name, memory, timeout)

        runtime_meta = self._generate_runtime_meta(docker_image_name, memory)

        return runtime_meta

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        We need to delete job definition
        """
        def_id = self._format_jobdef_name(docker_image_name, memory)
        self._job_def_cleanup(def_id)

    def _job_run_cleanup(self, jobrun_name):
        logger.debug("Deleting jobrun {}".format(jobrun_name))
        try:
            self.custom_api.delete_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                name=jobrun_name,
                namespace=self.namespace,
                plural="jobruns",
                body=client.V1DeleteOptions(),
            )
        except ApiException as e:
            logger.debug("Deleting a jobrun failed with {} {}"
                         .format(e.status, e.reason))

    def _job_def_cleanup(self, jobdef_id):
        logger.info("Deleting runtime: {}".format(jobdef_id))
        try:
            self.custom_api.delete_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                name=jobdef_id,
                namespace=self.namespace,
                plural="jobdefinitions",
                body=client.V1DeleteOptions(),
            )
        except ApiException as e:
            logger.debug("Deleting a jobdef failed with {} {}"
                         .format(e.status, e.reason))

    def clean(self):
        """
        Deletes all runtimes from all packages
        """
        self.clear()
        runtimes = self.list_runtimes()
        for docker_image_name, memory in runtimes:
            self.delete_runtime(docker_image_name, memory)

        logger.debug('Deleting all lithops configmaps')
        configmaps = self.core_api.list_namespaced_config_map(namespace=self.namespace)
        for configmap in configmaps.items:
            config_name = configmap.metadata.name
            if config_name.startswith('lithops'):
                logger.debug('Deleting configmap {}'.format(config_name))
                self.core_api.delete_namespaced_config_map(
                    name=config_name,
                    namespace=self.namespace,
                    grace_period_seconds=0)

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes
        return: list of tuples (docker_image_name, memory)
        """

        runtimes = []
        try:
            jobdefs = self.custom_api.list_namespaced_custom_object(
                            group=ce_config.DEFAULT_GROUP,
                            version=ce_config.DEFAULT_VERSION,
                            namespace=self.namespace,
                            plural="jobdefinitions")
        except ApiException as e:
            logger.debug("List all jobdefinitions failed with {} {}".format(e.status, e.reason))
            return runtimes

        for jobdef in jobdefs['items']:
            try:
                if jobdef['metadata']['labels']['type'] == 'lithops-runtime':
                    container = jobdef['spec']['template']['containers'][0]
                    image_name = container['image']
                    memory = container['resources']['requests']['memory'].replace('M', '')
                    memory = int(int(memory)/1000*1024)
                    if docker_image_name in image_name or docker_image_name == 'all':
                        runtimes.append((image_name, memory))
            except Exception:
                # It is not a lithops runtime
                pass

        return runtimes

    def clear(self, job_keys=None):
        """
        Clean all completed jobruns in the current executor
        """
        if self.iam_api_key and not self.is_lithops_worker:
            # try to refresh the token
            self._get_iam_token()
            self.custom_api = client.CustomObjectsApi()
            self.core_api = client.CoreV1Api()

        jobs_to_delete = job_keys or self.jobs
        for job_key in jobs_to_delete:
            jobrun_name = 'lithops-{}'.format(job_key.lower())
            try:
                self._job_run_cleanup(jobrun_name)
                self._delete_config_map(jobrun_name)
            except Exception as e:
                logger.debug("Deleting a jobrun failed with: {}".format(e))
            try:
                self.jobs.remove(job_key)
            except ValueError:
                pass

    def invoke(self, docker_image_name, runtime_memory, job_payload):
        """
        Invoke -- return information about this invocation
        For array jobs only remote_invocator is allowed
        """
        if self.iam_api_key and not self.is_lithops_worker:
            # try to refresh the token
            self._get_iam_token()
            self.custom_api = client.CustomObjectsApi()
            self.core_api = client.CoreV1Api()

        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']

        job_key = job_payload['job_key']
        self.jobs.append(job_key)

        total_calls = job_payload['total_calls']
        chunksize = job_payload['chunksize']
        total_workers = total_calls // chunksize + (total_calls % chunksize > 0)

        jobdef_name = self._format_jobdef_name(docker_image_name, runtime_memory)

        if not self._job_def_exists(jobdef_name):
            jobdef_name = self._create_job_definition(docker_image_name, runtime_memory, jobdef_name)

        jobrun_res = yaml.safe_load(ce_config.JOBRUN_DEFAULT)

        activation_id = 'lithops-{}'.format(job_key.lower())

        jobrun_res['metadata']['name'] = activation_id
        jobrun_res['metadata']['namespace'] = self.namespace
        jobrun_res['spec']['jobDefinitionRef'] = str(jobdef_name)
        jobrun_res['spec']['jobDefinitionSpec']['arraySpec'] = '0-' + str(total_workers - 1)

        container = jobrun_res['spec']['jobDefinitionSpec']['template']['containers'][0]
        container['name'] = str(jobdef_name)
        container['env'][0]['value'] = 'run'

        config_map = self._create_config_map(activation_id, job_payload)
        container['env'][1]['valueFrom']['configMapKeyRef']['name'] = config_map

        container['resources']['requests']['memory'] = '{}G'.format(runtime_memory/1024)
        container['resources']['requests']['cpu'] = str(self.code_engine_config['runtime_cpu'])

        # logger.debug("request - {}".format(jobrun_res)

        logger.debug('ExecutorID {} | JobID {} - Going to run {} activations '
                     '{} workers'.format(executor_id, job_id, total_calls, total_workers))

        self._run_job(jobrun_res)

        # logger.debug("response - {}".format(res))

        return activation_id

    @retry_on_except
    def _run_job(self, jobrun_res):
        self.custom_api.create_namespaced_custom_object(
            group=ce_config.DEFAULT_GROUP,
            version=ce_config.DEFAULT_VERSION,
            namespace=self.namespace,
            plural="jobruns",
            body=jobrun_res,
        )

    def _create_container_registry_secret(self):
        """
        Create the container registry secret in the cluster
        (only if credentials are present in config)
        """
        if not all(key in self.code_engine_config for key in ["docker_user", "docker_password"]):
            return

        logger.debug('Creating container registry secret')
        docker_server = self.code_engine_config.get('docker_server', 'https://index.docker.io/v1/')
        docker_user = self.code_engine_config.get('docker_user')
        docker_password = self.code_engine_config.get('docker_password')

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
        except ApiException as e:
            pass

        try:
            self.core_api.create_namespaced_secret(self.namespace, secret)
        except ApiException as e:
            if e.status != 409:
                raise e

    @retry_on_except
    def _create_job_definition(self, image_name, runtime_memory, timeout):
        """
        Creates a Job definition
        """
        self._create_container_registry_secret()

        jobdef_name = self._format_jobdef_name(image_name, runtime_memory)
        jobdef_res = yaml.safe_load(ce_config.JOBDEF_DEFAULT)
        jobdef_res['metadata']['name'] = jobdef_name
        container = jobdef_res['spec']['template']['containers'][0]
        container['image'] = image_name
        container['name'] = jobdef_name
        container['env'][0]['value'] = 'run'
        container['resources']['requests']['memory'] = '{}G'.format(runtime_memory/1024)
        container['resources']['requests']['cpu'] = str(self.code_engine_config['runtime_cpu'])

        try:
            self.custom_api.delete_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobdefinitions",
                name=jobdef_name,
            )
        except Exception:
            pass

        try:
            self.custom_api.create_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobdefinitions",
                body=jobdef_res,
            )
            # logger.debug("response - {}".format(res))
        except Exception as e:
            raise e

        logger.debug('Job Definition {} created'.format(jobdef_name))

        return jobdef_name

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        jobdef_name = self._format_jobdef_name(docker_image_name, 256)
        runtime_key = os.path.join(self.name, self.region, self.namespace, jobdef_name)

        return runtime_key

    @retry_on_except
    def _job_def_exists(self, jobdef_name):
        logger.debug("Check if job_definition {} exists".format(jobdef_name))
        try:
            self.custom_api.get_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobdefinitions",
                name=jobdef_name
            )
        except ApiException as e:
            # swallow error
            if (e.status == 404):
                logger.debug("Job definition {} not found (404)".format(jobdef_name))
                return False
        logger.debug("Job definition {} found".format(jobdef_name))
        return True

    def _generate_runtime_meta(self, docker_image_name, memory):

        logger.info("Extracting Python modules from: {}".format(docker_image_name))
        jobrun_res = yaml.safe_load(ce_config.JOBRUN_DEFAULT)

        jobdef_name = self._format_jobdef_name(docker_image_name, memory)
        jobrun_name = 'lithops-runtime-preinstalls'

        job_payload = copy.deepcopy(self.internal_storage.storage.storage_config)
        job_payload['log_level'] = logger.getEffectiveLevel()
        job_payload['runtime_name'] = jobdef_name

        jobrun_res['metadata']['name'] = jobrun_name
        jobrun_res['metadata']['namespace'] = self.namespace
        jobrun_res['spec']['jobDefinitionRef'] = str(jobdef_name)
        container = jobrun_res['spec']['jobDefinitionSpec']['template']['containers'][0]
        container['name'] = str(jobdef_name)
        container['env'][0]['value'] = 'preinstalls'

        config_map_name = 'lithops-{}-preinstalls'.format(jobdef_name)
        config_map_name = self._create_config_map(config_map_name, job_payload)
        container['env'][1]['valueFrom']['configMapKeyRef']['name'] = config_map_name

        try:
            self.custom_api.delete_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobruns",
                name=jobrun_name
            )
        except Exception:
            pass

        try:
            self.custom_api.create_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobruns",
                body=jobrun_res,
            )
        except Exception:
            pass

        logger.debug("Waiting for runtime metadata")

        done = False
        failed = False

        while not done or failed:
            try:
                w = watch.Watch()
                for event in w.stream(self.custom_api.list_namespaced_custom_object,
                                      namespace=self.namespace, group=ce_config.DEFAULT_GROUP,
                                      version=ce_config.DEFAULT_VERSION, plural="jobruns",
                                      field_selector="metadata.name={0}".format(jobrun_name),
                                      timeout_seconds=10):
                    failed = int(event['object'].get('status')['failed'])
                    done = int(event['object'].get('status')['succeeded'])
                    logger.debug('...')
                    if done or failed:
                        w.stop()
            except Exception:
                pass

        if done:
            logger.debug("Runtime metadata generated successfully")

        try:
            self.custom_api.delete_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobruns",
                name=jobrun_name
            )
        except Exception:
            pass

        self._delete_config_map(config_map_name)

        if failed:
            raise Exception("Unable to extract Python preinstalled modules from the runtime")

        data_key = '/'.join([JOBS_PREFIX, jobdef_name+'.meta'])
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
        cmap.data["lithops.payload"] = dict_to_b64str(payload)

        logger.debug("Creating ConfigMap {}".format(config_map_name))
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
            logger.debug("Deleting ConfigMap {}".format(config_map_name))
            self.core_api.delete_namespaced_config_map(
                name=config_map_name,
                namespace=self.namespace,
                grace_period_seconds=grace_period_seconds
            )
        except ApiException as e:
            logger.debug("Deleting a configmap failed with {} {}"
                         .format(e.status, e.reason))
