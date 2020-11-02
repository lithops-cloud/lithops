#
# (C) Copyright IBM Corp. 2020
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
import logging
import uuid
import urllib3
import copy
import json
from . import config as codeengine_config
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from lithops.utils import version_str
from lithops.version import __version__
from lithops.utils import is_lithops_worker
from lithops.serverless.utils import create_function_handler_zip
from lithops.storage.utils import create_runtime_meta_key
from lithops.config import JOBS_PREFIX
from lithops.storage import InternalStorage
from lithops.storage.utils import StorageNoSuchKeyError

urllib3.disable_warnings()
logging.getLogger('kubernetes').setLevel(logging.CRITICAL)
logging.getLogger('urllib3.connectionpool').setLevel(logging.CRITICAL)
logging.getLogger('requests_oauthlib').setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)


class CodeEngineBackend:
    """
    A wrap-up around Code Engine backend.
    """

    def __init__(self, code_engine_config, storage_config):
        logger.debug("Creating Code Engine client")
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.name = 'code_engine'
        self.code_engine_config = code_engine_config
        self.is_lithops_worker = is_lithops_worker()
        self.storage_config = storage_config
        self.internal_storage = InternalStorage(storage_config)

        config.load_kube_config(config_file=code_engine_config.get('kubectl_config'))
        self.capi = client.CustomObjectsApi()

        self.user_agent = code_engine_config['user_agent']
        contexts = config.list_kube_config_contexts(config_file=code_engine_config.get('kubectl_config'))

        current_context = contexts[1].get('context')
        self.user = current_context.get('user')

        self.user_key = self.user
        self.package = 'lithops_v{}_{}'.format(__version__, self.user_key)
        self.namespace = current_context.get('namespace', 'default')
        self.cluster = current_context.get('cluster')

        log_msg = ('Lithops v{} init for Code Engine - Namespace: {} - '
                   'Cluster: {} - User {}'.format(__version__, self.namespace, self.cluster, self.user))
        if not self.log_active:
            print(log_msg)
        self.job_def_ids = set()
        logger.info("Code Engine client created successfully")

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '-').replace(':', '-').replace('.', '-')
        return '{}-{}mb'.format(runtime_name, runtime_memory)

    def _get_default_runtime_image_name(self):
        python_version = version_str(sys.version_info)
        return codeengine_config.RUNTIME_DEFAULT[python_version]

    def _delete_function_handler_zip(self):
        logger.debug("About to delete {}".format(codeengine_config.FH_ZIP_LOCATION))
        res = os.remove(codeengine_config.FH_ZIP_LOCATION)
        logger.debug(res)

    def _dict_to_binary(self, the_dict):
        string = json.dumps(the_dict)
        binary = ' '.join(format(ord(letter), 'b') for letter in string)
        return binary

    def build_runtime(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info('Building a new docker image from Dockerfile')
        logger.info('Docker image name: {}'.format(docker_image_name))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        create_function_handler_zip(codeengine_config.FH_ZIP_LOCATION, entry_point, 'lithopsentry.py')

        if dockerfile:
            cmd = 'docker build -t {} -f {} .'.format(docker_image_name, dockerfile)
        else:
            cmd = 'docker build -t {} .'.format(docker_image_name)

        if not self.log_active:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        print(cmd)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        self._delete_function_handler_zip()

        cmd = 'docker push {}'.format(docker_image_name)
        if not self.log_active:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')

    def create_runtime(self, docker_image_name, memory, timeout):
        """
        Creates a new runtime from an already built Docker image
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()

        logger.info('Creating new Lithops runtime based on Docker image {}'.format(docker_image_name))

        action_name = self._format_action_name(docker_image_name, memory)
        if self.is_job_def_exists(action_name) is False:
            logger.debug("No job definition {} exists".format(action_name))
            action_name = self._create_job_definition(docker_image_name, memory, action_name)

        runtime_meta = self._generate_runtime_meta(action_name)
        return runtime_meta

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        We need to delete job definition
        """
        def_id = self._format_action_name(docker_image_name, memory)
        self._job_def_cleanup(def_id)

    def clean(self):
        """
        Deletes all runtimes from all packages
        """
        pass

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes
        return: list of tuples (docker_image_name, memory)
        """
        return []

    def invoke(self, docker_image_name, runtime_memory, payload_cp):
        """
        Invoke -- return information about this invocation
        For array jobs only remote_invocator is allowed
        """
        payload = copy.deepcopy(payload_cp)
        if payload['remote_invoker'] is False:
            raise ("Code Engine Array jobs - only remote_invoker = True is allowed")
        array_size = len(payload['job_description']['data_ranges'])
        runtime_memory_array = payload['job_description']['runtime_memory']
        def_id = self._format_action_name(docker_image_name, runtime_memory_array)
        logger.debug("Job definition id {}".format(def_id))
        if self.is_job_def_exists(def_id) is False:
            def_id = self._create_job_definition(docker_image_name, runtime_memory_array, def_id)

        self.job_def_ids.add(def_id)
        current_location = os.path.dirname(os.path.abspath(__file__))
        job_run_file = os.path.join(current_location, 'job_run.json')
        logger.debug("Going to open {} ".format(job_run_file))
        with open(job_run_file) as json_file:
            job_desc = json.load(json_file)

            activation_id = str(uuid.uuid4()).replace('-', '')[:12]
            payload['activation_id'] = activation_id
            payload['call_id'] = activation_id

            job_desc['metadata']['name'] = payload['activation_id']
            job_desc['metadata']['namespace'] = self.namespace
            job_desc['apiVersion'] = self.code_engine_config['api_version']
            job_desc['spec']['jobDefinitionRef'] = str(def_id)
            job_desc['spec']['jobDefinitionSpec']['arraySpec'] = '0-' + str(array_size - 1)
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['name'] = str(def_id)
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][0]['value'] = 'payload'
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = self._dict_to_binary(payload)
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['resources']['requests']['memory'] = str(runtime_memory_array) +'Mi'
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['resources']['requests']['cpu'] = str(self.code_engine_config['runtime_cpu'])

            logger.info("Before invoke job name {}".format(job_desc['metadata']['name']))
            if (logging.getLogger().level == logging.DEBUG):
                debug_res = copy.deepcopy(job_desc)
                debug_res['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = ''
                logger.debug("request - {}".format(debug_res))
                del debug_res
            try:
                res = self.capi.create_namespaced_custom_object(
                    group=self.code_engine_config['group'],
                    version=self.code_engine_config['version'],
                    namespace=self.namespace,
                    plural="jobruns",
                    body=job_desc,
                )
            except Exception as e:
                print(e)
            logger.info("After invoke job name {}".format(job_desc['metadata']['name']))

            if (logging.getLogger().level == logging.DEBUG):
                debug_res = copy.deepcopy(res)
                debug_res['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = ''
                logger.debug("response - {}".format(debug_res))
                del debug_res

            return res['metadata']['name']

    def _create_job_definition(self, docker_image_name, runtime_memory, activation_id):
        """
        Invoke -- return information about this invocation
        """
        current_location = os.path.dirname(os.path.abspath(__file__))
        job_def_file = os.path.join(current_location, 'job_def.json')

        with open(job_def_file) as json_file:
            job_desc = json.load(json_file)

            job_desc['apiVersion'] = self.code_engine_config['api_version']
            job_desc['spec']['template']['containers'][0]['image'] = docker_image_name
            job_desc['spec']['template']['containers'][0]['name'] = activation_id
            job_desc['spec']['template']['containers'][0]['env'][0]['value'] = 'payload'
            if runtime_memory:
                job_desc['spec']['template']['containers'][0]['resources']['requests']['memory'] = str(runtime_memory)+'Mi'
            job_desc['spec']['template']['containers'][0]['resources']['requests']['cpu'] = str(self.code_engine_config['runtime_cpu'])
            job_desc['metadata']['name'] = activation_id

            logger.info("Before invoke job name {}".format(job_desc['metadata']['name']))
            try:
                res = self.capi.create_namespaced_custom_object(
                    group=self.code_engine_config['group'],
                    version=self.code_engine_config['version'],
                    namespace=self.namespace,
                    plural="jobdefinitions",
                    body=job_desc,
                )
            except Exception as e:
                print(e)
            logger.info("After invoke job name {}".format(job_desc['metadata']['name']))

            if (logging.getLogger().level == logging.DEBUG):
                debug_res = copy.deepcopy(res)
                debug_res['spec']['template']['containers'][0]['env'][1]['value'] = ''
                logger.debug("response - {}".format(debug_res))
                del debug_res

            return res['metadata']['name']

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        service_name = self._format_service_name(docker_image_name)
        runtime_key = os.path.join(self.namespace, service_name)

        return runtime_key

    def _job_run_cleanup(self, activation_id):
        logger.debug("Cleanup for activation_id {}".format(activation_id))
        try:
            self.capi.delete_namespaced_custom_object(
                group=self.code_engine_config['group'],
                version=self.code_engine_config['version'],
                name=activation_id,
                namespace=self.namespace,
                plural="jobruns",
                body=client.V1DeleteOptions(),
            )
        except ApiException as e:
            # swallow error
            if (e.status == 404):
                logger.info("Cleanup - job name {} was not found (404)".format(activation_id))

    def _job_def_cleanup(self, jobdef_id):
        logger.debug("Cleanup for job_definition {}".format(jobdef_id))
        try:
            self.capi.delete_namespaced_custom_object(
                group=self.code_engine_config['group'],
                version=self.code_engine_config['version'],
                name=jobdef_id,
                namespace=self.namespace,
                plural="jobdefinitions",
                body=client.V1DeleteOptions(),
            )
        except ApiException as e:
            # swallow error
            if (e.status == 404):
                logger.info("Cleanup - job definition {} was not found (404)".format(self.jobdef_id))

    def is_job_def_exists(self, job_def_name):
        logger.debug("Check if job_definition {} exists".format(job_def_name))
        try:
            self.capi.get_namespaced_custom_object(
                group=self.code_engine_config['group'],
                version=self.code_engine_config['version'],
                namespace=self.namespace,
                plural="jobdefinitions",
                name=job_def_name
            )
        except ApiException as e:
            # swallow error
            if (e.status == 404):
                logger.info("Job definition {} was not found (404)".format(job_def_name))
                return False
        logger.info("Job definition {} was found".format(job_def_name))
        return True

    def _format_service_name(self, runtime_name, runtime_memory=None):
        runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        if (runtime_memory is not None):
            return '{}--{}mb'.format(runtime_name, runtime_memory)
        return runtime_name

    def _generate_runtime_meta(self, job_def_name):
        try:
            current_location = os.path.dirname(os.path.abspath(__file__))
            job_run_file = os.path.join(current_location, 'job_run.json')

            with open(job_run_file) as json_file:
                job_desc = json.load(json_file)

                activation_id = 'lithops-' + str(uuid.uuid4()).replace('-', '')[:12]
                self.storage_config['activation_id'] = activation_id

                job_desc['metadata']['name'] = activation_id
                job_desc['metadata']['namespace'] = self.namespace
                job_desc['apiVersion'] = self.code_engine_config['api_version']
                job_desc['spec']['jobDefinitionRef'] = str(job_def_name)
                job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['name'] = str(job_def_name)
                job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][0]['value'] = 'preinstals'
                job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = self._dict_to_binary(self.storage_config)

            logger.info("About to invoke code engine job to get runtime metadata")
            logger.info(job_desc)
            res = self.capi.create_namespaced_custom_object(
                group=self.code_engine_config['group'],
                version=self.code_engine_config['version'],
                namespace=self.namespace,
                plural="jobruns",
                body=job_desc,
            )
            if (logging.getLogger().level == logging.DEBUG):
                debug_res = copy.deepcopy(res)
                debug_res['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = ''
                logger.debug("response - {}".format(debug_res))
                del debug_res

            # we need to read runtime metadata from COS in retry
            status_key = create_runtime_meta_key(JOBS_PREFIX, self.storage_config['activation_id'])
            import time
            retry = int(1)
            found = False
            while retry < 5 and not found:
                try:
                    logger.debug("Retry attempt {} to read {}".format(retry, status_key))
                    json_str = self.internal_storage.storage.get_cobject(key=status_key)
                    logger.debug("Found in attempt () to read {}".format(retry, status_key))
                    runtime_meta = json.loads(json_str.decode("ascii"))
                    found = True
                except StorageNoSuchKeyError:
                    logger.debug("{} not found in attempt {}. Sleep before retry".format(status_key, retry))
                    retry = retry + 1
                    time.sleep(30)
            if retry >= 5 and not found:
                raise("Unable to invoke 'modules' action")

            json_str = self.internal_storage.storage.get_cobject(key=status_key)
            runtime_meta = json.loads(json_str.decode("ascii"))

        except Exception:
            raise("Unable to invoke 'modules' action")

        return runtime_meta
