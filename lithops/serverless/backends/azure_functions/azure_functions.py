#
# Copyright Cloudlab URV 2021
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
import ssl
import json
import time
import logging
import shutil
import lithops
import zipfile
import http.client
from urllib.parse import urlparse
from azure.storage.queue import QueueServiceClient

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG
from . import config as az_config

logger = logging.getLogger(__name__)


class AzureFunctionAppBackend:
    """
    A wrap-up around Azure Function Apps backend.
    """

    def __init__(self, config, internal_storage):
        logger.debug("Creating Azure Functions client")
        self.name = 'azure_fa'
        self.type = 'faas'
        self.azure_config = config
        self.invocation_type = self.azure_config['invocation_type']
        self.resource_group = self.azure_config['resource_group']
        self.storage_account_name = self.azure_config['storage_account_name']
        self.storage_account_key = self.azure_config['storage_account_key']
        self.location = self.azure_config['location']
        self.functions_version = self.azure_config['functions_version']

        self.queue_service_url = f'https://{self.storage_account_name}.queue.core.windows.net'
        self.queue_service = QueueServiceClient(account_url=self.queue_service_url,
                                                credential=self.storage_account_key)

        msg = COMPUTE_CLI_MSG.format('Azure Functions')
        logger.info("{} - Location: {}".format(msg, self.location))

    def _format_function_name(self, runtime_name, runtime_memory=None):
        runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        return runtime_name

    def _format_queue_name(self, action_name, q_type):
        runtime_name = action_name.replace('--', '-')
        return runtime_name+'-'+q_type

    def _get_default_runtime_name(self):
        """
        Generates the default runtime name
        """
        py_version = utils.version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = f'{self.storage_account_name}-{az_config.RUNTIME_NAME}-v{py_version}-{revision}-{self.invocation_type}'
        return runtime_name

    def deploy_runtime(self, runtime_name, memory, timeout):
        """
        Deploys a new runtime into Azure Function Apps
        from the provided Linux image for consumption plan
        """
        if runtime_name == self._get_default_runtime_name():
            self._build_default_runtime(runtime_name)

        logger.info(f"Deploying runtime: {runtime_name} - Memory: {memory} Timeout: {timeout}")
        self._create_function(runtime_name, memory, timeout)
        metadata = self._generate_runtime_meta(runtime_name, memory)

        return metadata

    def _build_default_runtime(self, runtime_name):
        """
        Builds the default runtime
        """
        requirements_file = 'az_default_requirements.txt'
        with open(requirements_file, 'w') as reqf:
            reqf.write(az_config.REQUIREMENTS_FILE)
        try:
            self.build_runtime(runtime_name, requirements_file)
        finally:
            os.remove(requirements_file)

        # # Build default runtime using local dokcer
        # python_version = version_str(sys.version_info)
        # dockerfile = "Dockefile.default-azure-runtime"
        # with open(dockerfile, 'w') as f:
        #     f.write("FROM mcr.microsoft.com/azure-functions/python:3.0-python{}\n".format(python_version))
        #     f.write(az_config.DEFAULT_DOCKERFILE)
        # try:
        #     self._build_runtime(default_runtime_name, dockerfile)
        # finally:
        #     os.remove(dockerfile)

    def build_runtime(self, runtime_name, requirements_file, extra_args=[]):
        logger.info(f'Building runtime {runtime_name} from {requirements_file}')

        try:
            shutil.rmtree(az_config.BUILD_DIR)
        except Exception:
            pass

        action_name = self._format_function_name(runtime_name)

        build_dir = os.path.join(az_config.BUILD_DIR, action_name)
        os.makedirs(build_dir, exist_ok=True)

        action_dir = os.path.join(build_dir, az_config.ACTION_DIR)
        os.makedirs(action_dir, exist_ok=True)

        logger.debug('Building runtime in {}'.format(build_dir))

        with open(requirements_file, 'r') as req_file:
            req_data = req_file.read()

        req_file = os.path.join(build_dir, 'requirements.txt')
        with open(req_file, 'w') as reqf:
            reqf.write(req_data)
            if not utils.is_unix_system():
                if 'dev' in lithops.__version__:
                    reqf.write('git+https://github.com/lithops-cloud/lithops')
                else:
                    reqf.write('lithops=={}'.format(lithops.__version__))

        host_file = os.path.join(build_dir, 'host.json')
        with open(host_file, 'w') as hstf:
            hstf.write(az_config.HOST_FILE)

        fn_file = os.path.join(action_dir, 'function.json')
        if self.invocation_type == 'event':
            with open(fn_file, 'w') as fnf:
                in_q_name = self._format_queue_name(action_name, az_config.IN_QUEUE)
                az_config.BINDINGS_QUEUE['bindings'][0]['queueName'] = in_q_name
                out_q_name = self._format_queue_name(action_name, az_config.OUT_QUEUE)
                az_config.BINDINGS_QUEUE['bindings'][1]['queueName'] = out_q_name
                fnf.write(json.dumps(az_config.BINDINGS_QUEUE))

        elif self.invocation_type == 'http':
            with open(fn_file, 'w') as fnf:
                fnf.write(json.dumps(az_config.BINDINGS_HTTP))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        main_file = os.path.join(action_dir, '__init__.py')
        shutil.copy(entry_point, main_file)

        if utils.is_unix_system():
            mod_dir = os.path.join(build_dir, az_config.ACTION_MODULES_DIR)
            os.chdir(build_dir)
            cmd = f'{sys.executable} -m pip install -U -t {mod_dir} -r requirements.txt'
            utils.run_command(cmd)
            utils.create_handler_zip(az_config.FH_ZIP_LOCATION, entry_point, '__init__.py')
            archive = zipfile.ZipFile(az_config.FH_ZIP_LOCATION)
            archive.extractall(path=mod_dir)
            os.remove(mod_dir+'/__init__.py')
            os.remove(az_config.FH_ZIP_LOCATION)

    def _create_function(self, runtime_name, memory, timeout):
        """
        Create and publish an Azure Functions
        """
        action_name = self._format_function_name(runtime_name, memory)
        logger.info(f'Creating new Lithops runtime for Azure Function: {action_name}')

        if self.invocation_type == 'event':
            try:
                in_q_name = self._format_queue_name(action_name, az_config.IN_QUEUE)
                logger.debug(f'Creating queue {in_q_name}')
                self.queue_service.create_queue(in_q_name)
            except Exception:
                in_queue = self.queue_service.get_queue_client(in_q_name)
                in_queue.clear_messages()
            try:
                out_q_name = self._format_queue_name(action_name, az_config.OUT_QUEUE)
                logger.debug(f'Creating queue {out_q_name}')
                self.queue_service.create_queue(out_q_name)
            except Exception:
                out_queue = self.queue_service.get_queue_client(out_q_name)
                out_queue.clear_messages()

        cmd = (f'az functionapp create --name {action_name} '
               f'--storage-account {self.storage_account_name} '
               f'--resource-group {self.resource_group} '
               '--os-type Linux  --runtime python '
               f'--runtime-version {az_config.PYTHON_VERSION} '
               f'--functions-version {self.functions_version} '
               f'--consumption-plan-location {self.location}')
        utils.run_command(cmd)

        logger.debug(f'Publishing function: {action_name}')
        build_dir = os.path.join(az_config.BUILD_DIR, action_name)
        os.chdir(build_dir)
        res = 1
        while res != 0:
            time.sleep(5)
            if utils.is_unix_system():
                cmd = f'func azure functionapp publish {action_name} --python --no-build'
            else:
                cmd = f'func azure functionapp publish {action_name} --python'
            utils.run_command(cmd)

        time.sleep(10)

    def delete_runtime(self, runtime_name, memory):
        """
        Deletes a runtime
        """
        action_name = self._format_function_name(runtime_name, memory)
        logger.debug(f'Deleting function app: {action_name}')
        cmd = f'az functionapp delete --name {action_name} --resource-group {self.resource_group}'
        utils.run_command(cmd)

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
        action_name = self._format_function_name(docker_image_name, memory)
        if self.invocation_type == 'event':

            in_q_name = self._format_queue_name(action_name, az_config.IN_QUEUE)
            in_queue = self.queue_service.get_queue_client(in_q_name)
            msg = in_queue.send_message(utils.dict_to_b64str(payload))
            activation_id = msg.id

            if return_result:
                out_q_name = self._format_queue_name(action_name, az_config.OUT_QUEUE)
                out_queue = self.queue_service.get_queue_client(out_q_name)
                msg = []
                while not msg:
                    time.sleep(1)
                    msg = out_queue.receive_message()
                out_queue.clear_messages()
                return utils.b64str_to_dict(msg.content)

        elif self.invocation_type == 'http':
            endpoint = f"https://{action_name}.azurewebsites.net"
            parsed_url = urlparse(endpoint)
            ctx = ssl._create_unverified_context()
            conn = http.client.HTTPSConnection(parsed_url.netloc, context=ctx)

            route = "/api/lithops_handler"
            if return_result:
                conn.request("GET", route, body=json.dumps(payload, default=str))
                resp = conn.getresponse()
                data = json.loads(resp.read().decode("utf-8"))
                conn.close()
                return data
            else:
                # logger.debug('Invoking calls {}'.format(', '.join(payload['call_ids'])))
                conn.request("POST", route, body=json.dumps(payload, default=str))
                resp = conn.getresponse()
                if resp.status == 429:
                    time.sleep(0.2)
                    conn.close()
                    return None
                activation_id = resp.read().decode("utf-8")
                conn.close()

        return activation_id

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_function_name(docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.name, action_name)

        return runtime_key

    def clean(self):
        """
        Deletes all Lithops Azure Function Apps runtimes
        """
        logger.debug('Deleting all runtimes')

        runtimes = self.list_runtimes()

        for runtime in runtimes:
            runtime_name, runtime_memory = runtime
            self.delete_runtime(runtime_name, runtime_memory)

    def _generate_runtime_meta(self, docker_image_name, memory):
        """
        Extract metadata from Azure runtime
        """
        logger.info(f"Extracting metadata from: {docker_image_name}")
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

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the Azure Function Apps deployed.
        return: Array of tuples (function_name, memory)
        """
        logger.debug('Listing all functions deployed...')

        functions = []
        response = os.popen('az functionapp list --query "[].defaultHostName\"').read()
        response = json.loads(response)

        for function in response:
            function = function.replace('.azurewebsites.net', '')
            if docker_image_name == function or docker_image_name == 'all':
                functions.append((function, ''))

        logger.debug('Listed {} functions'.format(len(functions)))
        return functions

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if az_config.PYTHON_VERSION not in az_config.SUPPORTED_PYTHON:
            raise Exception(f'Python {az_config.PYTHON_VERSION} is not available for'
                f'Azure Functions. Please use one of {az_config.SUPPORTED_PYTHON}')

        if 'runtime' not in self.azure_config or self.azure_config['runtime'] == 'default':
            self.azure_config['runtime'] = self._get_default_runtime_name()
        
        runime_info = {
            'runtime_name': self.azure_config['runtime'],
            'runtime_memory': self.azure_config['runtime_memory'],
            'runtime_timeout': self.azure_config['runtime_timeout'],
            'max_workers': self.azure_config['max_workers'],
        }

        return runime_info
