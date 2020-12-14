#
# Copyright Cloudlab URV 2020
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
import time
import json
import logging
import shutil
from azure.storage.queue import QueueServiceClient
import lithops
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG
from lithops.utils import create_handler_zip, version_str, dict_to_b64str,\
    b64str_to_dict
from . import config as az_config

logger = logging.getLogger(__name__)


class AzureFunctionAppBackend:
    """
    A wrap-up around Azure Function Apps backend.
    """

    def __init__(self, config, storage_config):
        logger.debug("Creating Azure Functions client")
        self.name = 'azure_fa'
        self.azure_config = config
        self.resource_group = self.azure_config['resource_group']
        self.storage_account = self.azure_config['storage_account']
        self.account_key = self.azure_config['storage_account_key']
        self.location = self.azure_config['location']
        self.functions_version = self.azure_config['functions_version']

        self.queue_service_url = 'https://{}.queue.core.windows.net'.format(self.storage_account)
        self.queue_service = QueueServiceClient(account_url=self.queue_service_url,
                                                credential=self.account_key)

        msg = COMPUTE_CLI_MSG.format('Azure Functions')
        logger.info("{} - Location: {}".format(msg, self.location))

    def _format_action_name(self, runtime_name, runtime_memory=None):
        runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        return runtime_name

    def _format_queue_name(self, action_name, q_type):
        runtime_name = action_name.replace('--', '-')
        return runtime_name+'-'+q_type

    def _get_default_runtime_image_name(self):
        py_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = '{}-{}-v{}-{}'.format(self.storage_account, az_config.RUNTIME_NAME,
                                             py_version, revision)
        return runtime_name

    def create_runtime(self, docker_image_name, memory=None, timeout=az_config.RUNTIME_TIMEOUT):
        """
        Creates a new runtime into Azure Function Apps
        from the provided Linux image for consumption plan
        """
        default_runtime_img_name = self._get_default_runtime_image_name()
        if docker_image_name in ['default', default_runtime_img_name]:
            # We only build the default image. rest of images must already exist
            # in the docker registry.
            docker_image_name = default_runtime_img_name
            self._build_default_runtime(default_runtime_img_name)

        logger.info('Creating new Lithops runtime for Azure Function Apps')
        self._create_function(docker_image_name, memory, timeout)
        metadata = self._generate_runtime_meta(docker_image_name, memory)

        return metadata

    def _build_default_runtime(self, default_runtime_img_name):
        """
        Builds the default runtime
        """
        return self.build_runtime(default_runtime_img_name)

        if os.system('{} --version >{} 2>&1'.format(az_config.DOCKER_PATH, os.devnull)) == 0:
            # Build default runtime using local dokcer
            python_version = version_str(sys.version_info)
            dockerfile = "Dockefile.default-azure-runtime"
            with open(dockerfile, 'w') as f:
                f.write("FROM mcr.microsoft.com/azure-functions/python:3.0-python{}\n".format(python_version))
                f.write(az_config.DEFAULT_DOCKERFILE)
            self.build_runtime_docker(default_runtime_img_name, dockerfile)
            os.remove(dockerfile)
        else:
            raise Exception('docker command not found. Install docker or use '
                            'an already built runtime')

    def build_runtime(self, runtime_name, requirements_file=None):
        try:
            shutil.rmtree(az_config.BUILD_DIR)
        except Exception:
            pass

        action_name = self._format_action_name(runtime_name)

        build_dir = os.path.join(az_config.BUILD_DIR, action_name)
        os.makedirs(build_dir, exist_ok=True)

        logger.info('Building default runtime in {}'.format(build_dir))

        action_dir = os.path.join(build_dir, az_config.ACTION_DIR)
        os.makedirs(action_dir, exist_ok=True)

        req_file = os.path.join(build_dir, 'requirements.txt')
        with open(req_file, 'w') as reqf:
            reqf.write(az_config.REQUIREMENTS_FILE)

        host_file = os.path.join(build_dir, 'host.json')
        with open(host_file, 'w') as hstf:
            hstf.write(az_config.HOST_FILE)

        fn_file = os.path.join(action_dir, 'function.json')
        with open(fn_file, 'w') as fnf:
            in_q_name = self._format_queue_name(action_name, az_config.IN_QUEUE)
            az_config.BINDINGS['bindings'][0]['queueName'] = in_q_name
            out_q_name = self._format_queue_name(action_name, az_config.OUT_QUEUE)
            az_config.BINDINGS['bindings'][1]['queueName'] = out_q_name
            fnf.write(json.dumps(az_config.BINDINGS))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        main_file = os.path.join(action_dir, '__init__.py')
        shutil.copy(entry_point, main_file)

        mod_dir = os.path.join(build_dir, az_config.ACTION_MODULES_DIR)
        os.chdir(build_dir)
        cmd = 'pip3 install -U -t {} -r requirements.txt'.format(mod_dir)
        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        os.system(cmd)
        lithops_location = os.path.dirname(os.path.abspath(lithops.__file__))
        shutil.copytree(lithops_location, os.path.join(mod_dir, 'lithops'))

    def build_runtime_docker(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.debug('Building new docker image from Dockerfile')
        logger.debug('Docker image name: {}'.format(docker_image_name))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        create_handler_zip(az_config.FH_ZIP_LOCATION, entry_point, '__init__.py')

        if dockerfile:
            cmd = '{} build -t {} -f {} .'.format(az_config.DOCKER_PATH,
                                                  docker_image_name,
                                                  dockerfile)
        else:
            cmd = '{} build -t {} .'.format(az_config.DOCKER_PATH, docker_image_name)

        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        logger.info('Building default runtime')
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        cmd = '{} push {}'.format(az_config.DOCKER_PATH, docker_image_name)
        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')
        logger.debug('Done!')

    def _create_function(self, docker_image_name, memory=None,
                         timeout=az_config.RUNTIME_TIMEOUT):
        """
        Create and publish an Azure Function App
        """
        action_name = self._format_action_name(docker_image_name, memory)

        try:
            in_q_name = self._format_queue_name(action_name, az_config.IN_QUEUE)
            self.queue_service.create_queue(in_q_name)
        except Exception:
            in_queue = self.queue_service.get_queue_client(in_q_name)
            in_queue.clear_messages()
        try:
            out_q_name = self._format_queue_name(action_name, az_config.OUT_QUEUE)
            self.queue_service.create_queue(out_q_name)
        except Exception:
            out_queue = self.queue_service.get_queue_client(out_q_name)
            out_queue.clear_messages()

        logger.debug('Creating function app')
        logger.debug('Function name: {}'.format(action_name))
        python_version = version_str(sys.version_info)
        cmd = ('az functionapp create --name {} --storage-account {} '
               '--resource-group {} --os-type Linux  --runtime python '
               '--runtime-version {} --functions-version {} --consumption-plan-location {}'
               .format(action_name, self.storage_account, self.resource_group,
                       python_version, self.functions_version, self.location))
        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error creating the function in Azure. cmd: {}'.format(cmd))

        logger.debug('Publishing function app')
        build_dir = os.path.join(az_config.BUILD_DIR, action_name)
        os.chdir(build_dir)
        res = 1
        while res != 0:
            time.sleep(5)
            cmd = 'func azure functionapp publish {} --python --no-build'.format(action_name)
            if logger.getEffectiveLevel() != logging.DEBUG:
                cmd = cmd + " >{} 2>&1".format(os.devnull)
            res = os.system(cmd)

        time.sleep(10)

    def delete_runtime(self, runtime_name, memory):
        """
        Deletes a runtime
        """
        action_name = self._format_action_name(runtime_name, memory)

        logger.debug('Deleting function app: {}'.format(action_name))
        cmd = ('az functionapp delete --name {} --resource-group {}'
               .format(action_name, self.resource_group))
        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        try:
            in_q_name = self._format_queue_name(action_name, az_config.IN_QUEUE)
            self.queue_service.delete_queue(in_q_name)
        except Exception:
            pass
        try:
            out_q_name = self._format_queue_name(action_name, az_config.OUT_QUEUE)
            self.queue_service.delete_queue(out_q_name)
        except Exception:
            pass

    def invoke(self, docker_image_name, memory=None, payload={}, return_result=False):
        """
        Invoke function
        """
        action_name = self._format_action_name(docker_image_name)
        in_q_name = self._format_queue_name(action_name, az_config.IN_QUEUE)
        in_queue = self.queue_service.get_queue_client(in_q_name)
        msg = in_queue.send_message(dict_to_b64str(payload))
        activation_id = msg.id

        if return_result:
            out_q_name = self._format_queue_name(action_name, az_config.OUT_QUEUE)
            out_queue = self.queue_service.get_queue_client(out_q_name)
            msg = []
            while not msg:
                time.sleep(1)
                msg = out_queue.receive_message()
            out_queue.clear_messages()
            return b64str_to_dict(msg.content)

        return activation_id

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_action_name(docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.name, action_name)

        return runtime_key

    def clean(self):
        # TODO
        pass

    def _generate_runtime_meta(self, docker_image_name, memory):
        """
        Extract installed Python modules from Azure runtime
        """
        logger.info("Extracting Python modules from: {}".format(docker_image_name))
        payload = {'log_level': logger.getEffectiveLevel(), 'get_preinstalls': True}

        try:
            runtime_meta = self.invoke(docker_image_name, memory=memory,
                                       payload=payload, return_result=True)
        except Exception:
            raise Exception("Unable to invoke 'extract-preinstalls' action")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        logger.debug("Extracted metadata succesfully")
        return runtime_meta
