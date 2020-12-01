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
import re
import sys
import logging
import copy
import time
import yaml
import requests

from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

from lithops.utils import version_str, dict_to_b64str
from lithops.version import __version__
from lithops.utils import create_handler_zip
from . import config as ce_config
from ..knative import config as kconfig
from types import SimpleNamespace


logger = logging.getLogger(__name__)


class CodeEngineBackend:
    """
    A wrap-up around Code Engine backend.
    """

    def __init__(self, code_engine_config, storage_config):
        logger.debug("Creating IBM Code Engine client")
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.name = 'code_engine'
        self.code_engine_config = code_engine_config

        self.kubecfg = code_engine_config.get('kubectl_config')
        self.user_agent = code_engine_config['user_agent']

        config.load_kube_config(config_file=self.kubecfg)
        self.capi = client.CustomObjectsApi()

        contexts = config.list_kube_config_contexts(config_file=self.kubecfg)
        current_context = contexts[1].get('context')
        self.namespace = current_context.get('namespace', 'default')
        self.cluster = current_context.get('cluster')
        self.region = self.cluster.split('//')[1].split('.')[1]

        log_msg = ('Lithops v{} init for Code Engine - Cluster: {} - Namespace: {}'
                   .format(__version__, self.cluster, self.namespace))
        if not self.log_active:
            print(log_msg)
        self.job_def_ids = set()
        logger.info("IBM Code Engine client created successfully")

    def _format_jobdef_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        return '{}--{}mb'.format(runtime_name, runtime_memory)

    def _unformat_jobdef_name(self, service_name):
        runtime_name, memory = service_name.rsplit('--', 1)
        image_name = runtime_name.replace('--', '/', 1)
        image_name = image_name.replace('--', ':', -1)
        return image_name, int(memory.replace('mb', ''))

    def _get_default_runtime_image_name(self):
        docker_user = self.code_engine_config.get('docker_user')
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        return '{}/{}-v{}:{}'.format(docker_user, ce_config.RUNTIME_NAME, python_version, revision)

    def _delete_function_handler_zip(self):
        os.remove(ce_config.FH_ZIP_LOCATION)

    def build_runtime(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info('Building new docker image from Dockerfile')
        logger.info('Docker image name: {}'.format(docker_image_name))

        expression = '^([a-z0-9]+)/([-a-z0-9]+)(:[a-z0-9]+)?'
        result = re.match(expression, docker_image_name)

        if not result or result.group() != docker_image_name:
            raise Exception("Invalid docker image name: All letters must be "
                            "lowercase and '.' or '_' characters are not allowed")

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        create_handler_zip(ce_config.FH_ZIP_LOCATION, entry_point, 'lithopsentry.py')

        if dockerfile:
            cmd = '{} build -t {} -f {} .'.format(ce_config.DOCKER_PATH,
                                                  docker_image_name,
                                                  dockerfile)
        else:
            cmd = '{} build -t {} .'.format(ce_config.DOCKER_PATH, docker_image_name)

        if not self.log_active or (self.log_active and logger.getEffectiveLevel() != logging.DEBUG):
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        logger.info('Building default runtime...')
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        self._delete_function_handler_zip()

        cmd = '{} push {}'.format(ce_config.DOCKER_PATH, docker_image_name)
        if not self.log_active or (self.log_active and logger.getEffectiveLevel() != logging.DEBUG):
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')
        logger.info('Done!')

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

    def create_runtime(self, docker_image_name, memory, timeout):
        """
        Creates a new runtime from an already built Docker image
        """
        default_runtime_img_name = self._get_default_runtime_image_name()
        if docker_image_name in ['default', default_runtime_img_name]:
            # We only build the default image. rest of images must already exist
            # in the docker registry.
            docker_image_name = default_runtime_img_name
            self._build_default_runtime(default_runtime_img_name)

        logger.info('Creating new Lithops runtime based on '
                    'Docker image: {}'.format(docker_image_name))
        self._create_job_definition(docker_image_name, memory, timeout)

        runtime_meta = self._generate_runtime_meta(docker_image_name)

        return runtime_meta

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        We need to delete job definition
        """
        def_id = self._format_jobdef_name(docker_image_name, memory)
        self._job_def_cleanup(def_id)

    def _job_run_cleanup(self, activation_id):
        logger.debug("Cleanup for activation_id {}".format(activation_id))
        try:
            self.capi.delete_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                name=activation_id,
                namespace=self.namespace,
                plural="jobruns",
                body=client.V1DeleteOptions(),
            )
        except ApiException:
            pass

    def _job_def_cleanup(self, jobdef_id):
        logger.info("Deleting runtime: {}".format(jobdef_id))
        try:
            self.capi.delete_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                name=jobdef_id,
                namespace=self.namespace,
                plural="jobdefinitions",
                body=client.V1DeleteOptions(),
            )
        except ApiException:
            pass

    def clean(self):
        """
        Deletes all runtimes from all packages
        """
        jobdefs = self.list_runtimes()
        for docker_image_name, memory in jobdefs:
            self.delete_runtime(docker_image_name, memory)

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes
        return: list of tuples (docker_image_name, memory)
        """
        jobdefs = self.capi.list_namespaced_custom_object(
                                group=ce_config.DEFAULT_GROUP,
                                version=ce_config.DEFAULT_VERSION,
                                namespace=self.namespace,
                                plural="jobdefinitions")
        runtimes = []

        for jobdef in jobdefs['items']:
            try:
                if jobdef['metadata']['labels']['type'] == 'lithops-runtime':
                    runtime_name = jobdef['metadata']['name']
                    image_name, memory = self._unformat_jobdef_name(runtime_name)
                    if docker_image_name == image_name or docker_image_name == 'all':
                        runtimes.append((image_name, memory))
            except Exception:
                # It is not a lithops runtime
                pass

        return runtimes

    def invoke(self, docker_image_name, runtime_memory, payload_cp):
        """
        Invoke -- return information about this invocation
        For array jobs only remote_invocator is allowed
        """
        payload = copy.deepcopy(payload_cp)

        array_size = len(payload['job_description']['data_ranges'])
        runtime_memory_array = payload['job_description']['runtime_memory']

        jobdef_name = self._format_jobdef_name(docker_image_name, runtime_memory_array)
        logger.debug("Job definition id {}".format(jobdef_name))
        if not self._job_def_exists(jobdef_name):
            jobdef_name = self._create_job_definition(docker_image_name, runtime_memory_array, jobdef_name)

        self.job_def_ids.add(jobdef_name)

        jobrun_res = yaml.safe_load(ce_config.JOBRUN_DEFAULT)

        executor_id = payload['executor_id']
        job_id = payload['job_id'].lower()
        activation_id = 'lithops-{}-{}'.format(executor_id, job_id)

        payload.pop('remote_invoker')
        payload.pop('invokers')

        job = SimpleNamespace(**payload.pop('job_description'))
        payload['host_submit_tstamp'] = time.time()
        payload['func_key'] = job.func_key
        payload['data_key'] = job.data_key
        payload['extra_env'] = job.extra_env
        payload['execution_timeout'] = job.execution_timeout
        payload['data_byte_range'] = job.data_ranges
        payload['runtime_name'] = job.runtime_name
        payload['runtime_memory'] = job.runtime_memory

        jobrun_res['metadata']['name'] = activation_id
        jobrun_res['metadata']['namespace'] = self.namespace
        jobrun_res['spec']['jobDefinitionRef'] = str(jobdef_name)
        jobrun_res['spec']['jobDefinitionSpec']['arraySpec'] = '0-' + str(array_size - 1)

        container = jobrun_res['spec']['jobDefinitionSpec']['template']['containers'][0]
        container['name'] = str(jobdef_name)
        container['env'][0]['value'] = 'run'
        container['env'][1]['value'] = dict_to_b64str(payload)
        container['resources']['requests']['memory'] = '{}Mi'.format(runtime_memory_array)
        container['resources']['requests']['cpu'] = '{}m'.format(self.code_engine_config['cpu'])

        logger.debug("request - {}".format(jobrun_res))

        try:
            res = self.capi.create_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobruns",
                body=jobrun_res,
            )
        except Exception as e:
            raise e

        logger.debug("response - {}".format(res))

        return activation_id

    def _create_job_definition(self, docker_image_name, runtime_memory, timeout):
        """
        Creates a Job definition
        """
        jobdef_name = self._format_jobdef_name(docker_image_name, runtime_memory)

        jobdef_res = yaml.safe_load(ce_config.JOBDEF_DEFAULT)
        jobdef_res['metadata']['name'] = jobdef_name
        container = jobdef_res['spec']['template']['containers'][0]
        container['image'] = docker_image_name
        container['name'] = jobdef_name
        container['env'][0]['value'] = 'run'
        container['resources']['requests']['memory'] = '{}Mi'.format(runtime_memory)
        container['resources']['requests']['cpu'] = '{}m'.format(self.code_engine_config['cpu'])

        try:
            res = self.capi.create_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobdefinitions",
                body=jobdef_res,
            )
            logger.debug("response - {}".format(res))
        except Exception as e:
            logger.debug(e)

        logger.info('Job Definition created')

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

    def _job_def_exists(self, jobdef_name):
        logger.debug("Check if job_definition {} exists".format(jobdef_name))
        try:
            self.capi.get_namespaced_custom_object(
                group=ce_config.DEFAULT_GROUP,
                version=ce_config.DEFAULT_VERSION,
                namespace=self.namespace,
                plural="jobdefinitions",
                name=jobdef_name
            )
        except ApiException as e:
            # swallow error
            if (e.status == 404):
                logger.info("Job definition {} not found (404)".format(jobdef_name))
                return False
        logger.debug("Job definition {} found".format(jobdef_name))
        return True

    def _generate_runtime_meta(self, docker_image_name):
        """
        Creates a service in CodeEngine based on the docker_image_name
        """
        logger.info("Extracting Python modules from: {}".format(docker_image_name))
        svc_res = yaml.safe_load(kconfig.service_res)

        service_name = docker_image_name.replace('/', '--').replace(':', '--')
        svc_res['metadata']['name'] = service_name
        svc_res['metadata']['namespace'] = self.namespace
        svc_res['spec']['template']['spec']['timeoutSeconds'] = 30
        svc_res['spec']['template']['spec']['containerConcurrency'] = 1
        svc_res['spec']['template']['spec']['containers'][0]['image'] = docker_image_name
        svc_res['spec']['template']['spec']['containers'][0]['resources']['limits']['memory'] = '128Mi'
        svc_res['spec']['template']['spec']['containers'][0]['resources']['limits']['cpu'] = '100m'
        svc_res['spec']['template']['spec']['containers'][0]['resources']['requests']['memory'] = '128Mi'
        svc_res['spec']['template']['spec']['containers'][0]['resources']['requests']['cpu'] = '100m'
        svc_res['spec']['template']['metadata']['annotations']['autoscaling.knative.dev/minScale'] = "0"
        svc_res['spec']['template']['metadata']['annotations']['autoscaling.knative.dev/maxScale'] = "1"

        try:
            # create the service resource
            self.capi.create_namespaced_custom_object(
                    group=kconfig.DEFAULT_GROUP,
                    version=kconfig.DEFAULT_VERSION,
                    namespace=self.namespace,
                    plural="services",
                    body=svc_res
                )
        except Exception:
            pass

        w = watch.Watch()
        for event in w.stream(self.capi.list_namespaced_custom_object,
                              namespace=self.namespace, group=kconfig.DEFAULT_GROUP,
                              version=kconfig.DEFAULT_VERSION, plural="services",
                              field_selector="metadata.name={0}".format(service_name),
                              timeout_seconds=300):
            if event['object'].get('status'):
                service_url = event['object']['status'].get('url')
                conditions = event['object']['status']['conditions']
                if conditions[0]['status'] == 'True' and \
                   conditions[1]['status'] == 'True' and \
                   conditions[2]['status'] == 'True':
                    w.stop()
                    time.sleep(2)

        try:
            service_url = service_url.replace('http://', 'https://')
            resp = requests.get(service_url+"/preinstalls")
            runtime_meta = resp.json()
        except Exception as e:
            raise Exception('Unable to extract preinstalled modules'
                            'list from runtime: {}'.format(e))

        try:
            # delete the service resource if exists
            self.capi.delete_namespaced_custom_object(
                    group=kconfig.DEFAULT_GROUP,
                    version=kconfig.DEFAULT_VERSION,
                    name=service_name,
                    namespace=self.namespace,
                    plural="services",
                    body=client.V1DeleteOptions()
                )
        except Exception:
            pass

        return runtime_meta
