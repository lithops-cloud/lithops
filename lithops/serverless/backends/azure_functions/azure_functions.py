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
import hashlib
import logging
import shutil
import zipfile
import subprocess as sp
import http.client
from urllib.parse import urlparse
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
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
        self.type = utils.BackendType.FAAS.value
        self.af_config = af_config
        self.trigger = af_config['trigger']
        self.resource_group = af_config['resource_group']
        self.storage_account_name = af_config['storage_account_name']
        self.storage_account_key = af_config['storage_account_key']
        self.location = af_config['region']
        self.functions_version = self.af_config['functions_version']

        self.queue_service_url = f'https://{self.storage_account_name}.queue.core.windows.net'
        self.queue_service = QueueServiceClient(account_url=self.queue_service_url,
                                                credential=self.storage_account_key)

        logger.debug(f'Invocation trigger set to: {self.trigger}')

        msg = COMPUTE_CLI_MSG.format('Azure Functions')
        logger.info(f"{msg} - Region: {self.location}")

    def _check_az_cli(self):
        if not shutil.which('az'):
            raise Exception(
                'Azure CLI (az) command not found. '
                'Install it from https://docs.microsoft.com/en-us/cli/azure/install-azure-cli'
            )

    def _run_az_command(self, cmd, return_json=False, return_result=False):
        """
        Run an Azure CLI command using shell=True.
        """
        self._check_az_cli()
        kwargs = {}
        if logger.getEffectiveLevel() != logging.DEBUG:
            kwargs['stderr'] = sp.DEVNULL
        try:
            if return_json or return_result:
                result = sp.check_output(cmd, shell=True, encoding='UTF-8', **kwargs)
            else:
                if logger.getEffectiveLevel() != logging.DEBUG:
                    kwargs['stdout'] = sp.DEVNULL
                sp.check_call(cmd, shell=True, **kwargs)
                return None
        except sp.CalledProcessError as e:
            raise Exception(f'Azure CLI command failed: {cmd}') from e

        result = result.strip()
        if return_json:
            try:
                return json.loads(result)
            except json.JSONDecodeError as e:
                raise Exception(
                    f'Failed to parse Azure CLI output as JSON: {result}'
                ) from e
        if return_result:
            return result.replace('"', '')
        return result

    def _function_app_exists(self, function_name):
        cmd = (f'az functionapp show --name {function_name} '
               f'--resource-group {self.resource_group}')
        kwargs = {}
        if logger.getEffectiveLevel() != logging.DEBUG:
            kwargs['stderr'] = sp.DEVNULL
            kwargs['stdout'] = sp.DEVNULL
        try:
            sp.check_call(cmd, shell=True, **kwargs)
            return True
        except sp.CalledProcessError:
            return False

    def _create_deploy_zip(self, build_dir):
        """
        Create a zip of the build directory contents for OneDeploy.
        """
        zip_path = os.path.join(TEMP_DIR, f'{os.path.basename(build_dir)}-deploy.zip')
        if os.path.exists(zip_path):
            os.remove(zip_path)

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(build_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, build_dir)
                    zf.write(file_path, arcname)

        return zip_path

    def _publish_function(self, function_name, build_dir):
        """
        Deploy the function app package using Azure CLI OneDeploy (Flex Consumption).
        """
        zip_path = self._create_deploy_zip(build_dir)
        try:
            logger.info(f'Publishing function: {function_name}')
            if utils.is_linux_system():
                cmd = (f'az functionapp deployment source config-zip '
                       f'-g {self.resource_group} -n {function_name} '
                       f'--src {zip_path} --build-remote false')
            else:
                cmd = (f'az functionapp deployment source config-zip '
                       f'-g {self.resource_group} -n {function_name} '
                       f'--src {zip_path}')

            max_retries = 10
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    time.sleep(10)
                    self._run_az_command(cmd)
                    logger.info(f'Function {function_name} published successfully')
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(f'Publish attempt {attempt}/{max_retries} failed: {e}')
            else:
                raise Exception(
                    f'Failed to publish function {function_name} after {max_retries} attempts'
                ) from last_error
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)

        time.sleep(10)

    def _get_function_identity(self, runtime_name, version=__version__):
        """
        Returns a stable hash for a Lithops runtime on Azure Functions.
        """
        name = f'{self.storage_account_name}-{runtime_name}-{version}-{self.trigger}'
        return hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]

    def _format_function_name(self, runtime_name, version=__version__):
        """
        Formats the function app name.
        Host ID collisions are avoided via AzureFunctionsWebHost__hostid.
        """
        name_hash = self._get_function_identity(runtime_name, version)
        return f'lithops-worker-{runtime_name}-{version.replace(".", "")}-{name_hash}'

    def _format_host_id(self, runtime_name, version=__version__):
        """
        Unique Functions host ID (must start with a letter, alphanumeric only).
        """
        return f'l{self._get_function_identity(runtime_name, version)}'

    def _format_queue_name(self, function_name, q_type):
        """
        Generates the queue name
        """
        name_hash = function_name.rsplit("-", 1)[-1]
        return f'lithops-worker-{name_hash}-{q_type}'

    def _get_default_runtime_name(self):
        """
        Generates the default runtime name
        """
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        return f'default-runtime-v{py_version}'

    def deploy_runtime(self, runtime_name, memory, timeout):
        """
        Deploys a new runtime into Azure Function Apps
        on the Flex Consumption plan
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
        if not requirements_file:
            raise Exception('Please provide a "requirements.txt" file with the necessary modules')

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
            if not utils.is_linux_system():
                if 'dev' in __version__:
                    reqf.write('git+https://github.com/lithops-cloud/lithops')
                else:
                    reqf.write(f'lithops=={__version__}')

        host_file = os.path.join(build_dir, 'host.json')
        with open(host_file, 'w') as hstf:
            hstf.write(config.HOST_FILE)

        fn_file = os.path.join(action_dir, 'function.json')
        if self.trigger == 'pub/sub':
            with open(fn_file, 'w') as fnf:
                in_q_name = self._format_queue_name(function_name, config.IN_QUEUE)
                config.BINDINGS_QUEUE['bindings'][0]['queueName'] = in_q_name
                out_q_name = self._format_queue_name(function_name, config.OUT_QUEUE)
                config.BINDINGS_QUEUE['bindings'][1]['queueName'] = out_q_name
                fnf.write(json.dumps(config.BINDINGS_QUEUE))

        elif self.trigger == 'https':
            with open(fn_file, 'w') as fnf:
                fnf.write(json.dumps(config.BINDINGS_HTTP))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        main_file = os.path.join(action_dir, '__init__.py')
        shutil.copy(entry_point, main_file)

        if utils.is_linux_system():
            mod_dir = os.path.join(build_dir, config.ACTION_MODULES_DIR)
            os.chdir(build_dir)
            cmd = f'{sys.executable} -m pip install -U -t {mod_dir} -r requirements.txt'
            utils.run_command(cmd)
            utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, '__init__.py')
            archive = zipfile.ZipFile(config.FH_ZIP_LOCATION)
            archive.extractall(path=mod_dir)
            os.remove(mod_dir + '/__init__.py')
            os.remove(config.FH_ZIP_LOCATION)

        logger.debug(f'Runtime {runtime_name} built successfully')

    def _create_function(self, runtime_name, memory, timeout):
        """
        Create and publish an Azure Functions
        """
        logger.info(f'Creating Azure Function from runtime {runtime_name}')
        function_name = self._format_function_name(runtime_name)

        if self.trigger == 'pub/sub':
            in_q_name = self._format_queue_name(function_name, config.IN_QUEUE)
            logger.debug(f'Creating queue {in_q_name}')
            self._ensure_queue(in_q_name)
            out_q_name = self._format_queue_name(function_name, config.OUT_QUEUE)
            logger.debug(f'Creating queue {out_q_name}')
            self._ensure_queue(out_q_name)

        instance_memory = config.get_flex_instance_memory(memory)
        if instance_memory != memory:
            logger.debug(
                f'Using Flex Consumption instance memory {instance_memory}MB '
                f'(requested {memory}MB)'
            )

        cmd = (f'az functionapp create --name {function_name} '
               f'--storage-account {self.storage_account_name} '
               f'--resource-group {self.resource_group} '
               f'--flexconsumption-location {self.location} '
               '--runtime python '
               f'--runtime-version {utils.CURRENT_PY_VERSION} '
               f'--functions-version {self.functions_version} '
               f'--instance-memory {instance_memory} '
               f'--tags type=lithops-runtime lithops_version={__version__} runtime_name={runtime_name}')
        if not self._function_app_exists(function_name):
            self._run_az_command(cmd)
        else:
            logger.debug(f'Function app {function_name} already exists, skipping create')

        host_id = self._format_host_id(runtime_name)
        cmd = (f'az functionapp config appsettings set --name {function_name} '
               f'--resource-group {self.resource_group} '
               f'--settings AzureFunctionsWebHost__hostid={host_id}')
        self._run_az_command(cmd)

        build_dir = os.path.join(config.BUILD_DIR, function_name)
        self._publish_function(function_name, build_dir)

    def delete_runtime(self, runtime_name, memory, version=__version__, function_name=None):
        """
        Deletes a runtime
        """
        logger.info(f'Deleting runtime: {runtime_name} - {memory}MB')
        if function_name is None:
            function_name = self._format_function_name(runtime_name, version)
        cmd = f'az functionapp delete --name {function_name} --resource-group {self.resource_group}'
        self._run_az_command(cmd)

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

    def invoke(self, runtime_name, memory=None, payload={}, return_result=False):
        """
        Invoke function
        """
        function_name = self._format_function_name(runtime_name)

        if self.trigger == 'pub/sub':
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

            return activation_id

        elif self.trigger == 'https':
            endpoint = f"https://{function_name}.azurewebsites.net"
            parsed_url = urlparse(endpoint)
            ctx = ssl._create_unverified_context()
            conn = http.client.HTTPSConnection(parsed_url.netloc, context=ctx)

            route = "/api/lithops_handler"
            if return_result:
                conn.request("GET", route, body=json.dumps(payload, default=str))
                resp = conn.getresponse()
                resp_text = resp.read().decode("utf-8")
                conn.close()
                if resp.status != 200:
                    raise Exception(f'Invocation error: {resp.reason} - {resp_text}')
                try:
                    resp_text = json.loads(resp_text)
                except Exception:
                    raise Exception(f'Unable to load runtime metadata: {resp_text}')
            else:
                # logger.debug('Invoking calls {}'.format(', '.join(payload['call_ids'])))
                conn.request("POST", route, body=json.dumps(payload, default=str))
                resp = conn.getresponse()
                resp_text = resp.read().decode("utf-8")
                conn.close()
                if resp.status == 429:
                    time.sleep(0.2)
                    return None

            return resp_text

    def get_runtime_key(self, runtime_name, runtime_memory, version=__version__):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        function_name = self._format_function_name(runtime_name, version)
        runtime_key = os.path.join(self.name, version, function_name)

        return runtime_key

    def _ensure_queue(self, queue_name):
        """
        Create a queue if it does not exist, or clear it if it already exists.
        """
        queue_client = self.queue_service.get_queue_client(queue_name)
        try:
            queue_client.create_queue()
        except ResourceExistsError:
            try:
                queue_client.clear_messages()
            except ResourceNotFoundError:
                pass

    def _clean_queues(self):
        """
        Delete all Lithops worker queues, including orphaned ones from failed deploys.
        """
        if self.trigger != 'pub/sub':
            return

        try:
            for queue in self.queue_service.list_queues(name_starts_with='lithops-worker-'):
                logger.debug(f'Deleting queue {queue.name}')
                self.queue_service.delete_queue(queue.name)
        except Exception as e:
            logger.debug(f'Error cleaning queues: {e}')

    def clean(self, **kwargs):
        """
        Deletes all Lithops Azure Function Apps runtimes
        """
        logger.debug('Deleting all runtimes')

        runtimes = self.list_runtimes()

        for runtime_name, runtime_memory, version, wk_name in runtimes:
            self.delete_runtime(runtime_name, runtime_memory, version, function_name=wk_name)

        self._clean_queues()

    def _generate_runtime_meta(self, runtime_name, memory):
        """
        Extract metadata from Azure runtime
        """
        logger.info(f"Extracting metadata from: {runtime_name}")
        payload = {'log_level': logger.getEffectiveLevel(), 'get_metadata': True}

        runtime_meta = self.invoke(
            runtime_name, memory=memory,
            payload=payload, return_result=True
        )

        if 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        logger.debug("Metadata extracted succesfully")
        return runtime_meta

    def list_runtimes(self, runtime_name='all'):
        """
        List all the Azure Function Apps deployed.
        return: Array of tuples (function_name, memory)
        """
        logger.debug('Listing all deployed runtimes')

        runtimes = []
        cmd = 'az functionapp list --query "[].{Name:name, Tags:tags}"'
        response = self._run_az_command(cmd, return_json=True)

        for functionapp in response:
            if functionapp['Tags'] and 'type' in functionapp['Tags'] \
               and functionapp['Tags']['type'] == 'lithops-runtime':
                version = functionapp['Tags']['lithops_version']
                name = functionapp['Tags']['runtime_name']
                memory = config.DEFAULT_CONFIG_KEYS['runtime_memory']
                if runtime_name == functionapp['Name'] or runtime_name == 'all':
                    runtimes.append((name, memory, version, functionapp['Name']))

        return runtimes

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if utils.CURRENT_PY_VERSION not in config.AVAILABLE_PY_RUNTIMES:
            raise Exception(
                f'Python {utils.CURRENT_PY_VERSION} is not available for Azure '
                f'Functions. Please use one of {list(config.AVAILABLE_PY_RUNTIMES)}'
            )

        if 'runtime' not in self.af_config or self.af_config['runtime'] == 'default':
            self.af_config['runtime'] = self._get_default_runtime_name()

        runtime_info = {
            'runtime_name': self.af_config['runtime'],
            'runtime_memory': self.af_config['runtime_memory'],
            'runtime_timeout': self.af_config['runtime_timeout'],
            'max_workers': self.af_config['max_workers'],
        }

        return runtime_info
