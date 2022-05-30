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
import zipfile
import http.client
from urllib.parse import urlparse
from azure.storage.queue import QueueServiceClient

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG, TEMP_DIR

from . import config

logger = logging.getLogger(__name__)


class AzureFunctionAppBackend:
    """
    A wrap-up around Azure Function Apps backend.
    """

    def __init__(self, af_config, internal_storage):
        logger.debug("Creating Azure Functions client")
        self.name = 'azure_functions'
        self.type = 'faas'
        self.af_config = af_config
        self.invocation_type = af_config['invocation_type']
        self.resource_group = af_config['resource_group']
        self.storage_account_name = af_config['storage_account_name']
        self.storage_account_key = af_config['storage_account_key']
        self.location = af_config['location']
        self.functions_version = self.af_config['functions_version']

        self.queue_service_url = f'https://{self.storage_account_name}.queue.core.windows.net'
        self.queue_service = QueueServiceClient(account_url=self.queue_service_url,
                                                credential=self.storage_account_key)

        msg = COMPUTE_CLI_MSG.format('Azure Functions')
        logger.info(f"{msg} - Location: {self.location}")

    def _format_function_name(self, runtime_name, runtime_memory=None):
        """
        Formates the function name
        """
        ver = __version__.replace('.', '-')
        function_name = f'{self.storage_account_name}-{runtime_name}-{ver}-{self.invocation_type}'
        return function_name

    def _format_queue_name(self, function_name, q_type):
        return  function_name.replace('--', '-') + '-' + q_type

    def _get_default_runtime_name(self):
        """
        Generates the default runtime name
        """
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        return  f'lithops-default-runtime-v{py_version}'

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
        requirements_file = os.path.join(TEMP_DIR, 'az_default_requirements.txt')
        with open(requirements_file, 'w') as reqf:
            reqf.write(config.REQUIREMENTS_FILE)
        try:
            self.build_runtime(runtime_name, requirements_file)
        finally:
            os.remove(requirements_file)

    def build_runtime(self, runtime_name, requirements_file, extra_args=[]):
        logger.info(f'Building runtime {runtime_name} from {requirements_file}')

        try:
            shutil.rmtree(config.BUILD_DIR)
        except Exception:
            pass

        function_name = self._format_function_name(runtime_name)

        build_dir = os.path.join(config.BUILD_DIR, function_name)
        os.makedirs(build_dir, exist_ok=True)

        action_dir = os.path.join(build_dir, config.ACTION_DIR)
        os.makedirs(action_dir, exist_ok=True)

        logger.debug(f'Building runtime in {build_dir}')

        with open(requirements_file, 'r') as req_file:
            req_data = req_file.read()

        req_file = os.path.join(build_dir, 'requirements.txt')
        with open(req_file, 'w') as reqf:
            reqf.write(req_data)
            if not utils.is_unix_system():
                if 'dev' in __version__:
                    reqf.write('git+https://github.com/lithops-cloud/lithops')
                else:
                    reqf.write(f'lithops=={__version__}')

        host_file = os.path.join(build_dir, 'host.json')
        with open(host_file, 'w') as hstf:
            hstf.write(config.HOST_FILE)

        fn_file = os.path.join(action_dir, 'function.json')
        if self.invocation_type == 'event':
            with open(fn_file, 'w') as fnf:
                in_q_name = self._format_queue_name(function_name, config.IN_QUEUE)
                config.BINDINGS_QUEUE['bindings'][0]['queueName'] = in_q_name
                out_q_name = self._format_queue_name(function_name, config.OUT_QUEUE)
                config.BINDINGS_QUEUE['bindings'][1]['queueName'] = out_q_name
                fnf.write(json.dumps(config.BINDINGS_QUEUE))

        elif self.invocation_type == 'http':
            with open(fn_file, 'w') as fnf:
                fnf.write(json.dumps(config.BINDINGS_HTTP))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        main_file = os.path.join(action_dir, '__init__.py')
        shutil.copy(entry_point, main_file)

        if utils.is_unix_system():
            mod_dir = os.path.join(build_dir, config.ACTION_MODULES_DIR)
            os.chdir(build_dir)
            cmd = f'{sys.executable} -m pip install -U -t {mod_dir} -r requirements.txt'
            utils.run_command(cmd)
            utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, '__init__.py')
            archive = zipfile.ZipFile(config.FH_ZIP_LOCATION)
            archive.extractall(path=mod_dir)
            os.remove(mod_dir+'/__init__.py')
            os.remove(config.FH_ZIP_LOCATION)
        
        logger.debug(f'Runtime {runtime_name} built successfully')

    def _create_function(self, runtime_name, memory, timeout):
        """
        Create and publish an Azure Functions
        """
        logger.info(f'Creating Azure Function from runtime {runtime_name}')
        function_name = self._format_function_name(runtime_name, memory)

        if self.invocation_type == 'event':
            try:
                in_q_name = self._format_queue_name(function_name, config.IN_QUEUE)
                logger.debug(f'Creating queue {in_q_name}')
                self.queue_service.create_queue(in_q_name)
            except Exception:
                in_queue = self.queue_service.get_queue_client(in_q_name)
                in_queue.clear_messages()
            try:
                out_q_name = self._format_queue_name(function_name, config.OUT_QUEUE)
                logger.debug(f'Creating queue {out_q_name}')
                self.queue_service.create_queue(out_q_name)
            except Exception:
                out_queue = self.queue_service.get_queue_client(out_q_name)
                out_queue.clear_messages()

        cmd = (f'az functionapp create --name {function_name} '
               f'--storage-account {self.storage_account_name} '
               f'--resource-group {self.resource_group} '
               '--os-type Linux --runtime python '
               f'--runtime-version {utils.CURRENT_PY_VERSION} '
               f'--functions-version {self.functions_version} '
               f'--consumption-plan-location {self.location} '
               f'--tags type=lithops-runtime lithops_version={__version__} runtime_name={runtime_name}')
        utils.run_command(cmd)
        time.sleep(10)

        logger.debug(f'Publishing function: {function_name}')
        build_dir = os.path.join(config.BUILD_DIR, function_name)
        os.chdir(build_dir)
        if utils.is_unix_system():
            cmd = f'func azure functionapp publish {function_name} --python --no-build'
        else:
            cmd = f'func azure functionapp publish {function_name} --python'
        while True:
            try:
                utils.run_command(cmd)
                break
            except Exception as e:
                time.sleep(10)
        time.sleep(10)

    def delete_runtime(self, runtime_name, memory):
        """
        Deletes a runtime
        """
        logger.info(f'Deleting runtime: {runtime_name} - {memory}MB')
        function_name = self._format_function_name(runtime_name, memory)
        cmd = f'az functionapp delete --name {function_name} --resource-group {self.resource_group}'
        utils.run_command(cmd)

        try:
            in_q_name = self._format_queue_name(function_name, config.IN_QUEUE)
            self.queue_service.delete_queue(in_q_name)
        except Exception:
            pass
        try:
            out_q_name = self._format_queue_name(function_name, config.OUT_QUEUE)
            self.queue_service.delete_queue(out_q_name)
        except Exception:
            pass

    def invoke(self, docker_image_name, memory=None, payload={}, return_result=False):
        """
        Invoke function
        """
        function_name = self._format_function_name(docker_image_name, memory)
        if self.invocation_type == 'event':

            in_q_name = self._format_queue_name(function_name, config.IN_QUEUE)
            in_queue = self.queue_service.get_queue_client(in_q_name)
            msg = in_queue.send_message(utils.dict_to_b64str(payload))
            activation_id = msg.id

            if return_result:
                out_q_name = self._format_queue_name(function_name, config.OUT_QUEUE)
                out_queue = self.queue_service.get_queue_client(out_q_name)
                msg = []
                while not msg:
                    time.sleep(1)
                    msg = out_queue.receive_message()
                out_queue.clear_messages()
                return utils.b64str_to_dict(msg.content)

        elif self.invocation_type == 'http':
            endpoint = f"https://{function_name}.azurewebsites.net"
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
        function_name = self._format_function_name(docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.name, __version__, function_name)

        return runtime_key

    def clean(self):
        """
        Deletes all Lithops Azure Function Apps runtimes
        """
        logger.debug('Deleting all runtimes')

        runtimes = self.list_runtimes()

        for runtime_name, runtime_memory, version in runtimes:
            self.delete_runtime(runtime_name, runtime_memory)

    def _generate_runtime_meta(self, docker_image_name, memory):
        """
        Extract metadata from Azure runtime
        """
        logger.info(f"Extracting metadata from: {docker_image_name}")
        payload = {'log_level': logger.getEffectiveLevel(), 'get_metadata': True}

        try:
            runtime_meta = self.invoke(docker_image_name, memory=memory,
                                       payload=payload, return_result=True)
        except Exception as e:
            raise Exception(f"Unable to extract metadata: {e}")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        logger.debug("Extracted metadata succesfully")
        return runtime_meta

    def list_runtimes(self, runtime_name='all'):
        """
        List all the Azure Function Apps deployed.
        return: Array of tuples (function_name, memory)
        """
        logger.debug('Listing all functions deployed...')

        runtimes = []
        response = os.popen('az functionapp list --query "[].{Name:name, Tags:tags}\"').read()
        response = json.loads(response)

        for function in response:
            if function['Tags'] and 'type' in function['Tags'] \
                and function['Tags']['type'] == 'lithops-runtime':
                version = function['Tags']['lithops_version']
                runtime = function['Tags']['runtime_name']
                if runtime_name == function['Name'] or runtime_name == 'all':
                    runtimes.append((runtime, 'shared', version))

        return runtimes

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if utils.CURRENT_PY_VERSION not in config.AVAILABLE_PY_RUNTIMES:
            raise Exception(f'Python {utils.CURRENT_PY_VERSION} is not available for'
                f'Azure Functions. Please use one of {config.AVAILABLE_PY_RUNTIMES}')

        if 'runtime' not in self.af_config or self.af_config['runtime'] == 'default':
            self.af_config['runtime'] = self._get_default_runtime_name()
        
        runtime_info = {
            'runtime_name': self.af_config['runtime'],
            'runtime_memory': self.af_config['runtime_memory'],
            'runtime_timeout': self.af_config['runtime_timeout'],
            'max_workers': self.af_config['max_workers'],
        }

        return runtime_info
