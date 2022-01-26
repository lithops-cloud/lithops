#
# (C) Copyright Cloudlab URV 2021
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
import logging
import copy
import time
import yaml
import urllib3
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

from lithops.utils import version_str, dict_to_b64str
from lithops.version import __version__
from lithops.utils import create_handler_zip
from lithops.constants import COMPUTE_CLI_MSG, JOBS_PREFIX

from . import config as k8s_config


logger = logging.getLogger(__name__)
urllib3.disable_warnings()


class KubernetesBackend:
    """
    A wrap-up around Code Engine backend.
    """

    def __init__(self, k8s_config, internal_storage):
        logger.debug("Creating Kubernetes Job client")
        self.name = 'k8s'
        self.type = 'batch'
        self.k8s_config = k8s_config
        self.internal_storage = internal_storage

        self.kubecfg_path = k8s_config.get('kubecfg_path')
        self.user_agent = k8s_config['user_agent']

        try:
            config.load_kube_config(config_file=self.kubecfg_path)
            contexts = config.list_kube_config_contexts(config_file=self.kubecfg_path)
            current_context = contexts[1].get('context')
            self.namespace = current_context.get('namespace', 'default')
            self.cluster = current_context.get('cluster')
            self.k8s_config['namespace'] = self.namespace
            self.k8s_config['cluster'] = self.cluster
            self.is_incluster = False
        except Exception:
            logger.debug('Loading incluster config')
            config.load_incluster_config()
            self.namespace = self.k8s_config.get('namespace', 'default')
            self.cluster = self.k8s_config.get('cluster', 'default')
            self.is_incluster = True

        logger.debug("Set namespace to {}".format(self.namespace))
        logger.debug("Set cluster to {}".format(self.cluster))

        self.batch_api = client.BatchV1Api()
        self.core_api = client.CoreV1Api()

        self.jobs = []  # list to store executed jobs (job_keys)

        msg = COMPUTE_CLI_MSG.format('Kubernetes Job')
        logger.info("{} - Namespace: {}".format(msg, self.namespace))

    def _format_job_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '--')
        runtime_name = runtime_name.replace(':', '--')
        runtime_name = runtime_name.replace('.', '')
        runtime_name = runtime_name.replace('_', '-')
        return '{}--{}mb'.format(runtime_name, runtime_memory)

    def _get_default_runtime_image_name(self):
        docker_user = self.k8s_config.get('docker_user')
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        return '{}/{}-v{}:{}'.format(docker_user, k8s_config.RUNTIME_NAME, python_version, revision)

    def _delete_function_handler_zip(self):
        os.remove(k8s_config.FH_ZIP_LOCATION)

    def build_runtime(self, docker_image_name, dockerfile, extra_args=[]):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.debug('Building new docker image from Dockerfile')
        logger.debug('Docker image name: {}'.format(docker_image_name))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        create_handler_zip(k8s_config.FH_ZIP_LOCATION, entry_point, 'lithopsentry.py')

        if dockerfile:
            cmd = '{} build -t {} -f {} . '.format(k8s_config.DOCKER_PATH,
                                                   docker_image_name,
                                                   dockerfile)
        else:
            cmd = '{} build -t {} . '.format(k8s_config.DOCKER_PATH, docker_image_name)

        cmd = cmd+' '.join(extra_args)

        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        logger.info('Building runtime')
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        self._delete_function_handler_zip()

        cmd = '{} push {}'.format(k8s_config.DOCKER_PATH, docker_image_name)
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
        if os.system('{} --version >{} 2>&1'.format(k8s_config.DOCKER_PATH, os.devnull)) == 0:
            # Build default runtime using local dokcer
            python_version = version_str(sys.version_info)
            dockerfile = "Dockefile.default-k8s-runtime"
            with open(dockerfile, 'w') as f:
                f.write("FROM python:{}-slim-buster\n".format(python_version))
                f.write(k8s_config.DOCKERFILE_DEFAULT)
            self.build_runtime(default_runtime_img_name, dockerfile)
            os.remove(dockerfile)
        else:
            raise Exception('docker command not found. Install docker or use '
                            'an already built runtime')

    def _create_container_registry_secret(self):
        """
        Create the container registry secret in the cluster
        (only if credentials are present in config)
        """
        if not all(key in self.k8s_config for key in ["docker_user", "docker_password"]):
            return

        logger.debug('Creating container registry secret')
        docker_server = self.k8s_config.get('docker_server', 'https://index.docker.io/v1/')
        docker_user = self.k8s_config.get('docker_user')
        docker_password = self.k8s_config.get('docker_password')

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
        self._create_container_registry_secret()
        runtime_meta = self._generate_runtime_meta(docker_image_name)

        return runtime_meta

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        """
        pass

    def clean(self, force=True):
        """
        Deletes all jobs
        """
        logger.debug('Cleaning kubernetes Jobs')

        try:
            jobs = self.batch_api.list_namespaced_job(namespace=self.namespace)
            for job in jobs.items:
                if job.metadata.labels['type'] == 'lithops-runtime'\
                   and (job.status.completion_time is not None or force):
                    job_name = job.metadata.name
                    logger.debug('Deleting job {}'.format(job_name))
                    try:
                        self.batch_api.delete_namespaced_job(name=job_name,
                                                             namespace=self.namespace,
                                                             propagation_policy='Background')
                    except Exception:
                        pass
        except ApiException:
            pass

    def clear(self, job_keys=None):
        """
        Delete only completed jobs
        """
        jobs_to_delete = job_keys or self.jobs

        for job_key in jobs_to_delete:
            job_name = 'lithops-{}'.format(job_key.lower())
            logger.debug('Deleting job {}'.format(job_name))
            try:
                self.batch_api.delete_namespaced_job(
                    name=job_name,
                    namespace=self.namespace,
                    propagation_policy='Background'
                )
            except Exception:
                pass
            try:
                self.jobs.remove(job_key)
            except ValueError:
                pass

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes
        return: list of tuples (docker_image_name, memory)
        """
        logger.debug('Listing runtimes')
        logger.debug('Note that k8s job backend does not manage runtimes')
        return []

    def _start_master(self, docker_image_name):

        job_name = 'lithops-master'

        master_pods = self.core_api.list_namespaced_pod(
            namespace=self.namespace, label_selector="job-name={}".format(job_name)
            )

        if len(master_pods.items) > 0:
            return master_pods.items[0].status.pod_ip

        logger.debug('Starting Lithops master Pod')
        try:
            self.batch_api.delete_namespaced_job(name=job_name,
                                                 namespace=self.namespace,
                                                 propagation_policy='Background')
            time.sleep(2)
        except Exception as e:
            pass

        job_res = yaml.safe_load(k8s_config.JOB_DEFAULT)
        job_res['metadata']['name'] = job_name
        job_res['metadata']['namespace'] = self.namespace
        container = job_res['spec']['template']['spec']['containers'][0]
        container['image'] = docker_image_name
        container['env'][0]['value'] = 'master'

        try:
            self.batch_api.create_namespaced_job(namespace=self.namespace,
                                                 body=job_res)
        except Exception as e:
            raise e

        w = watch.Watch()
        for event in w.stream(self.core_api.list_namespaced_pod, namespace=self.namespace,
                              label_selector="job-name={}".format(job_name)):
            if event['object'].status.phase == "Running":
                return event['object'].status.pod_ip

    def invoke(self, docker_image_name, runtime_memory, job_payload):
        """
        Invoke -- return information about this invocation
        For array jobs only remote_invocator is allowed
        """
        master_ip = self._start_master(docker_image_name)

        workers = job_payload['max_workers']
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']

        job_key = job_payload['job_key']
        self.jobs.append(job_key)

        total_calls = job_payload['total_calls']
        chunksize = job_payload['chunksize']
        total_workers = min(workers, total_calls // chunksize + (total_calls % chunksize > 0))

        job_res = yaml.safe_load(k8s_config.JOB_DEFAULT)

        activation_id = 'lithops-{}'.format(job_key.lower())

        job_res['metadata']['name'] = activation_id
        job_res['metadata']['namespace'] = self.namespace

        job_res['spec']['activeDeadlineSeconds'] = self.k8s_config['runtime_timeout']
        job_res['spec']['parallelism'] = total_workers

        container = job_res['spec']['template']['spec']['containers'][0]
        container['image'] = docker_image_name
        if not docker_image_name.endswith(':latest'):
            container['imagePullPolicy'] = 'IfNotPresent'

        container['env'][0]['value'] = 'run'
        container['env'][1]['value'] = dict_to_b64str(job_payload)
        container['env'][2]['value'] = master_ip

        container['resources']['requests']['memory'] = '{}Mi'.format(runtime_memory)
        container['resources']['requests']['cpu'] = str(self.k8s_config['runtime_cpu'])
        container['resources']['limits']['memory'] = '{}Mi'.format(runtime_memory)
        container['resources']['limits']['cpu'] = str(self.k8s_config['runtime_cpu'])

        logger.debug('ExecutorID {} | JobID {} - Going '
                     'to run {} activations in {} workers'
                     .format(executor_id, job_id, total_calls, total_workers))

        try:
            self.batch_api.create_namespaced_job(namespace=self.namespace,
                                                 body=job_res)
        except Exception as e:
            raise e

        return activation_id

    def _generate_runtime_meta(self, docker_image_name):
        runtime_name = self._format_job_name(docker_image_name, 128)
        modules_job_name = '{}-modules'.format(runtime_name)

        logger.info("Extracting Python modules from: {}".format(docker_image_name))

        payload = copy.deepcopy(self.internal_storage.storage.storage_config)
        payload['runtime_name'] = runtime_name
        payload['log_level'] = logger.getEffectiveLevel()

        job_res = yaml.safe_load(k8s_config.JOB_DEFAULT)
        job_res['metadata']['name'] = modules_job_name
        job_res['metadata']['namespace'] = self.namespace

        container = job_res['spec']['template']['spec']['containers'][0]
        container['image'] = docker_image_name
        container['env'][0]['value'] = 'preinstalls'
        container['env'][1]['value'] = dict_to_b64str(payload)

        try:
            self.batch_api.delete_namespaced_job(namespace=self.namespace,
                                                 name=modules_job_name,
                                                 propagation_policy='Background')
        except Exception as e:
            pass

        try:
            self.batch_api.create_namespaced_job(namespace=self.namespace,
                                                 body=job_res)
        except Exception as e:
            raise e
            pass

        logger.debug("Waiting for runtime metadata")

        done = False
        failed = False

        while not done or failed:
            try:
                w = watch.Watch()
                for event in w.stream(self.batch_api.list_namespaced_job,
                                      namespace=self.namespace,
                                      field_selector="metadata.name={0}".format(modules_job_name),
                                      timeout_seconds=10):
                    failed = event['object'].status.failed
                    done = event['object'].status.succeeded
                    logger.debug('...')
                    if done or failed:
                        w.stop()
            except Exception as e:
                pass

        if done:
            logger.debug("Runtime metadata generated successfully")

        try:
            self.batch_api.delete_namespaced_job(namespace=self.namespace,
                                                 name=modules_job_name,
                                                 propagation_policy='Background')
        except Exception as e:
            pass

        if failed:
            raise Exception("Unable to extract Python preinstalled modules from the runtime")

        data_key = '/'.join([JOBS_PREFIX, runtime_name+'.meta'])
        json_str = self.internal_storage.get_data(key=data_key)
        runtime_meta = json.loads(json_str.decode("ascii"))
        self.internal_storage.del_data(key=data_key)

        return runtime_meta

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        jobdef_name = self._format_job_name(docker_image_name, 256)
        runtime_key = os.path.join(self.name, self.namespace, jobdef_name)

        return runtime_key
