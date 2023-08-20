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
import logging
import shutil
from threading import Lock

from lithops import utils
from lithops.util.ibm_token_manager import IAMTokenManager
from lithops.version import __version__
from lithops.config import dump_yaml_config, load_yaml_config
from lithops.libs.openwhisk.client import OpenWhiskClient
from lithops.constants import CACHE_DIR, COMPUTE_CLI_MSG

from . import config

logger = logging.getLogger(__name__)
cf_mutex = Lock()


class IBMCloudFunctionsBackend:
    """
    A wrap-up around IBM Cloud Functions backend.
    """

    def __init__(self, cf_config, internal_storage):
        logger.debug("Creating IBM Cloud Functions client")
        self.name = 'ibm_cf'
        self.type = 'faas'
        self.config = cf_config
        self.is_lithops_worker = utils.is_lithops_worker()

        self.user_agent = cf_config['user_agent']
        self.endpoint = cf_config['endpoint']
        self.region = cf_config['region']
        self.iam_api_key = cf_config['iam_api_key']
        self.resource_group_id = cf_config.get('resource_group_id')

        logger.debug(f"Set IBM CF Endpoint to {self.endpoint}")

        self.user_key = self.iam_api_key[:4].lower()
        self.package = f'lithops_{self.user_key}'

        self.namespace = cf_config.get('namespace', f'lithops-{self.region}-{self.user_key}')
        self.namespace_id = cf_config.get('namespace_id')

        self.cache_dir = os.path.join(CACHE_DIR, self.name)
        self.cache_file = os.path.join(self.cache_dir, self.namespace + '_data')

        self.invoke_error = None
        self.token_manager = None

        self._create_ow_client()

        if not self.namespace_id and not self.is_lithops_worker:
            self._get_or_create_namespace()
            self.cf_client.namespace = self.namespace_id
            self.config['namespace'] = self.namespace
            self.config['namespace_id'] = self.namespace_id

        msg = COMPUTE_CLI_MSG.format('IBM CF')
        logger.info(f"{msg} - Region: {self.region} - Namespace: {self.namespace}")

    def _create_ow_client(self):
        """
        Createsthe OW client
        """
        old_token = self.config.get('token')
        old_expiry_time = self.config.get('token_expiry_time')

        self.token_manager = IAMTokenManager(self.iam_api_key, old_token, old_expiry_time)
        token, expiry_time = self.token_manager.get_token()

        self.config['token'] = token
        self.config['token_expiry_time'] = expiry_time

        self.cf_client = OpenWhiskClient(
            endpoint=self.endpoint,
            namespace=self.namespace_id,
            auth='Bearer ' + token,
            user_agent=self.user_agent
        )

    def _refresh_ow_client(self):
        """
        Refresh the OW client if necessary
        """
        if not self.is_lithops_worker:
            cf_mutex.acquire()
            token, expiry_time = self.token_manager.get_token()

            if expiry_time != self.config['token_expiry_time']:
                self.config['token'] = token
                self.config['token_expiry_time'] = expiry_time

                self.cf_client = OpenWhiskClient(
                    endpoint=self.endpoint,
                    namespace=self.namespace_id,
                    auth='Bearer ' + token,
                    user_agent=self.user_agent
                )
            cf_mutex.release()

    def _get_or_create_namespace(self):
        """
        Gets or creates a new IAM namepsace if not exists
        """
        cf_data = load_yaml_config(self.cache_file)
        self.namespace_id = cf_data.get('namespace_id')
        if self.namespace_id:
            return

        response = self.cf_client.list_namespaces(self.resource_group_id)
        if 'namespaces' in response:
            for namespace in response['namespaces']:
                if namespace['name'] == self.namespace:
                    logger.debug(f"Found Cloud Functions namespace: {self.namespace}")
                    self.namespace_id = namespace['id']

        if not self.namespace_id:
            logger.debug(f"Creating new Cloud Functions namespace: {self.namespace}")
            self.namespace_id = self.cf_client.create_namespace(
                self.namespace, self.resource_group_id
            )

        cf_data['namespace'] = self.namespace
        cf_data['namespace_id'] = self.namespace_id
        dump_yaml_config(self.cache_file, cf_data)

    def _format_function_name(self, runtime_name, runtime_memory, version=__version__):
        runtime_name = runtime_name.replace('/', '_').replace(':', '_')
        return f'{runtime_name}_{runtime_memory}MB_{version}'

    def _unformat_function_name(self, action_name):
        runtime_name, memory, version = action_name.rsplit('_', 2)
        image_name = runtime_name.replace('_', '/', 2)
        image_name = image_name.replace('_', ':', -1)
        return version, image_name, int(memory.replace('MB', ''))

    def _get_default_runtime_image_name(self):
        try:
            return config.AVAILABLE_PY_RUNTIMES[utils.CURRENT_PY_VERSION]
        except KeyError:
            raise Exception(f'Unsupported Python version: {utils.CURRENT_PY_VERSION}')

    def build_runtime(self, docker_image_name, dockerfile, extra_args=[]):
        """
        Builds a new runtime from a Docker file and pushes it to the registry
        """
        logger.info(f'Building runtime {docker_image_name} from {dockerfile or "Dockerfile"}')

        docker_path = utils.get_docker_path()

        if dockerfile:
            assert os.path.isfile(dockerfile), f'Cannot locate "{dockerfile}"'
            cmd = f'{docker_path} build --platform=linux/amd64 -t {docker_image_name} -f {dockerfile} . '
        else:
            cmd = f'{docker_path} build --platform=linux/amd64 -t {docker_image_name} . '

        cmd = cmd + ' '.join(extra_args)
        utils.run_command(cmd)

        docker_user = self.config.get("docker_user")
        docker_password = self.config.get("docker_password")
        docker_server = self.config.get("docker_server")

        logger.debug(f'Pushing runtime {docker_image_name} to container registry')

        if docker_user and docker_password:
            cmd = f'{docker_path} login -u {docker_user} --password-stdin {docker_server}'
            utils.run_command(cmd, input=docker_password)

        if utils.is_podman(docker_path):
            cmd = f'{docker_path} push {docker_image_name} --format docker --remove-signatures'
        else:
            cmd = f'{docker_path} push {docker_image_name}'
        utils.run_command(cmd)

        logger.debug('Building done!')

    def deploy_runtime(self, docker_image_name, memory, timeout):
        """
        Creates a new runtime into IBM CF namespace from an already built Docker image
        """
        logger.info(f"Deploying runtime: {docker_image_name} - Memory: {memory} Timeout: {timeout}")

        self._refresh_ow_client()

        self.cf_client.create_package(self.package)
        action_name = self._format_function_name(docker_image_name, memory)

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, '__main__.py')

        try:
            with open(config.FH_ZIP_LOCATION, "rb") as action_zip:
                action_bin = action_zip.read()
            self.cf_client.create_action(
                self.package, action_name, docker_image_name,
                code=action_bin, memory=memory,
                is_binary=True, timeout=timeout * 1000
            )
        finally:
            os.remove(config.FH_ZIP_LOCATION)

        runtime_meta = self._generate_runtime_meta(docker_image_name, memory)

        return runtime_meta

    def delete_runtime(self, docker_image_name, memory, version=__version__):
        """
        Deletes a runtime
        """
        logger.info(f'Deleting runtime: {docker_image_name} - {memory}MB')
        self._refresh_ow_client()
        action_name = self._format_function_name(docker_image_name, memory, version)
        self.cf_client.delete_action(self.package, action_name)

    def clean(self, all=False):
        """
        Deletes all runtimes from all packages
        """
        self._refresh_ow_client()

        packages = self.cf_client.list_packages()
        for pkg in packages:
            if pkg['name'].startswith('lithops') and pkg['name'].endswith(self.user_key):
                actions = self.cf_client.list_actions(pkg['name'])
                while actions:
                    for action in actions:
                        logger.info(f'Deleting function: {action["name"]}')
                        self.cf_client.delete_action(pkg['name'], action['name'])
                    actions = self.cf_client.list_actions(pkg['name'])
                self.cf_client.delete_package(pkg['name'])

        if all and os.path.exists(self.cache_file):
            self.cf_client.delete_namespace(self.namespace_id)
            os.remove(self.cache_file)

        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed in the IBM CF service
        return: list of tuples (docker_image_name, memory)
        """
        runtimes = []
        self._refresh_ow_client()
        packages = self.cf_client.list_packages()
        for pkg in packages:
            if pkg['name'] == self.package:
                actions = self.cf_client.list_actions(pkg['name'])
                for action in actions:
                    version, image_name, memory = self._unformat_function_name(action['name'])
                    if docker_image_name == image_name or docker_image_name == 'all':
                        runtimes.append((image_name, memory, version))
        return runtimes

    def invoke(self, docker_image_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        action_name = self._format_function_name(docker_image_name, runtime_memory)

        activation_id = self.cf_client.invoke(
            package=self.package,
            action_name=action_name,
            payload=payload,
            is_ow_action=self.is_lithops_worker
        )

        if activation_id == 401:
            # Token expired
            self._refresh_ow_client()
            return self.invoke(docker_image_name, runtime_memory, payload)

        elif activation_id == 404:
            # Runtime not deployed
            if self.invoke_error is None:
                self.invoke_error = 404
            cf_mutex.acquire()
            if self.invoke_error == 404:
                logger.debug('Runtime not found')
                self.deploy_runtime(
                    docker_image_name, runtime_memory,
                    self.config['runtime_timeout']
                )
                self.invoke_error = None
            cf_mutex.release()
            return self.invoke(docker_image_name, runtime_memory, payload)

        return activation_id

    def get_runtime_key(self, docker_image_name, runtime_memory, version=__version__):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_function_name(docker_image_name, runtime_memory, version)
        runtime_key = os.path.join(self.name, version, self.region, self.namespace, action_name)

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
            'runtime_memory': self.config['runtime_memory'],
            'runtime_timeout': self.config['runtime_timeout'],
            'max_workers': self.config['max_workers'],
        }

        return runtime_info

    def _generate_runtime_meta(self, docker_image_name, memory):
        """
        Extract installed Python modules from the docker image
        """
        logger.debug(f"Extracting runtime metadata from: {docker_image_name}")
        action_name = self._format_function_name(docker_image_name, memory)
        payload = {'log_level': logger.getEffectiveLevel(), 'get_metadata': True}
        try:
            retry_invoke = True
            while retry_invoke:
                retry_invoke = False
                runtime_meta = self.cf_client.invoke_with_result(self.package, action_name, payload)
                if 'activationId' in runtime_meta:
                    retry_invoke = True
        except Exception as e:
            raise (f"Unable to extract metadata: {e}")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta

    def calc_cost(self, runtimes, memory, *argv, **arg):
        """ returns total cost associated with executing the calling function-executor's job.
        :params *argv and **arg: made to support compatibility with similarly named functions in
        alternative computational backends.
        """
        return config.UNIT_PRICE * sum(runtimes[i] * memory[i] / 1024 for i in range(len(runtimes)))
