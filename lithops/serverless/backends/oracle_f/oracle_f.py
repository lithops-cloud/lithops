# (C) Copyright Cloudlab URV 2023
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
import json
import ast
import hashlib
import time

import oci
from oci.functions import FunctionsManagementClient
from oci.functions import FunctionsInvokeClient
from oci.object_storage import ObjectStorageClient

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG

from . import config

logger = logging.getLogger(__name__)


class OracleCloudFunctionsBackend:

    def __init__(self, oci_config, internal_storage):
        self.name = 'oracle_f'
        self.type = utils.BackendType.FAAS.value
        self.config = oci_config

        self.user = oci_config['user']
        self.region = oci_config['region']
        self.key_file = oci_config['key_file']
        self.compartment_id = oci_config['compartment_id']
        self.subnet_id = oci_config['subnet_id']

        self.app_name = oci_config.get(
            'application_name', f'{config.APP_NAME}_{self.user[-8:-1].lower()}')

        self.cf_client = self._init_functions_mgmt_client()

        self.app_id = self._get_application_id(self.app_name)
        self.namespace = oci_config.get("tenancy_namespace", self._get_namespace())

        msg = COMPUTE_CLI_MSG.format('Oracle Functions')
        logger.info(f"{msg} - Region: {self.region}")

    def _init_functions_mgmt_client(self):
        if os.path.isfile(self.key_file):
            return FunctionsManagementClient(config=self.config)
        else:
            self.signer = oci.auth.signers.get_resource_principals_signer()
            return FunctionsManagementClient(config={}, signer=self.signer)

    def _init_functions_invk_client(self, endpoint):
        if os.path.isfile(self.key_file):
            return FunctionsInvokeClient(config=self.config, service_endpoint=endpoint)
        else:
            return FunctionsInvokeClient(config={}, service_endpoint=endpoint, signer=self.signer)

    def _get_namespace(self):
        """
        Returns the namespace
        """
        response = ObjectStorageClient(self.config).get_namespace()

        if response.status == 200:
            return response.data
        else:
            raise Exception(f"An error occurred: ({response.status}) {response.data}")

    def _format_function_name(self, runtime_name, runtime_memory, version=__version__):
        name = f'{runtime_name}-{runtime_memory}-{version}-{self.user}'
        name_hash = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
        return f'lithops-worker-{runtime_name.split("/")[-1]}-v{version}-{name_hash}'

    def _format_image_name(self, runtime_name):
        """
        Formats OC image name from runtime name
        """
        if 'ocir.io' not in runtime_name:
            image_name = f'{self.region}.ocir.io/{self.namespace}/{runtime_name}'
        else:
            image_name = runtime_name

        if ':' not in image_name:
            image_name = f'{image_name}:latest'

        return image_name

    def get_runtime_key(self, runtime_name, runtime_memory, version=__version__):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        image_name = self._format_image_name(runtime_name)
        function_name = self._format_function_name(image_name, runtime_memory, version)
        runtime_key = os.path.join(
            self.name,
            version,
            self.region,
            self.namespace,
            self.app_name,
            function_name
        )
        return runtime_key

    def _get_default_runtime_image_name(self):
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        return self._format_image_name(f'lithops-default-runtime-v{py_version}')

    def clean(self, all=False):
        """
        Deletes all runtimes from the current service
        """
        logger.debug('Going to delete all deployed runtimes')

        if not self.app_id:
            logger.debug(f'Application {self.app_name} does not exist')
            return

        functions = self.cf_client.list_functions(self.app_id).data

        for function in functions:
            memory = function.memory_in_mbs
            image_name = function.image
            logger.info(f'Deleting runtime: {image_name} - {memory}MB')
            self.cf_client.delete_function(function.id)

        if all:
            self.cf_client.delete_application(self.app_id)

    def pre_invoke(self, runtime_name, memory):
        """
        Pre-invocation task. This is executed only once before the invocation
        """
        if not self.app_id:
            raise Exception(f'Application {self.app_name} does not exist')

        image_name = self._format_image_name(runtime_name)
        function_name = self._format_function_name(image_name, memory)

        # Get the function ID
        self.invoke_function_id = self._get_function_id(function_name)
        if not self.invoke_function_id:
            raise Exception("Function %s not found", function_name)

        # Retrieve the function's information, including the invoke endpoint
        fn_info = self.cf_client.get_function(self.invoke_function_id).data

        if not fn_info.lifecycle_state == 'ACTIVE':
            raise Exception("Function %s is not yet active", function_name)

        # Set the invoke endpoint
        self.invoke_endpoint = fn_info.invoke_endpoint

    def invoke(self, runtime_name, memory, payload={}):
        """
        Invoke function
        """
        # The pre_invoke() method is already called at this point

        # Prepare the Oracle Functions client with the invoke endpoint
        fn_invoke_client = self._init_functions_invk_client(self.invoke_endpoint)

        response = fn_invoke_client.invoke_function(
            function_id=self.invoke_function_id,
            invoke_function_body=json.dumps(payload, default=str),
            fn_invoke_type='detached'
        )

        if response.status == 202:
            return response.headers['Fn-Call-Id']
        else:
            raise Exception(f"An error occurred: ({response.status}) {response.data.text}")

    def build_runtime(self, runtime_name, dockerfile, extra_args=[]):
        """
        Build the runtime Docker image and push it to OCIR
        """
        image_name = self._format_image_name(runtime_name)

        logger.info(f'Building runtime {image_name} from {dockerfile}')
        docker_path = utils.get_docker_path()

        # Build the Docker image
        if dockerfile:
            assert os.path.isfile(dockerfile), f'Cannot locate "{dockerfile}"'
            cmd = f'{docker_path} build --platform=linux/amd64 -t {image_name} -f {dockerfile} . '
        else:
            cmd = f'{docker_path} build --platform=linux/amd64 -t {image_name} . '
        cmd = cmd + ' '.join(extra_args)

        try:
            entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
            utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, 'entry_point.py')
            utils.run_command(cmd)
        finally:
            os.remove(config.FH_ZIP_LOCATION)

        logger.debug(f'Pushing runtime {image_name} to Oracle Cloud Container Registry')
        if utils.is_podman(docker_path):
            cmd = f'{docker_path} push {image_name} --format docker --remove-signatures'
        else:
            cmd = f'{docker_path} push {image_name}'
        utils.run_command(cmd)

    def _build_default_runtime(self, runtime_name):
        """
        Builds the default runtime
        """
        logger.debug('Building default runtime')
        # Build default runtime using local dokcer
        dockerfile = "Dockefile.default-oracle-runtime"
        with open(dockerfile, 'w') as f:
            f.write(f"FROM python:{utils.CURRENT_PY_VERSION}-slim-buster\n")
            f.write(config.DEFAULT_DOCKERFILE)
        try:
            self.build_runtime(runtime_name, dockerfile)
        finally:
            os.remove(dockerfile)

    def deploy_runtime(self, runtime_name, memory, timeout):
        """
        Deploys a new runtime into Oracle Function Compute
        with the custom modules for lithops
        """
        image_name = self._format_image_name(runtime_name)

        if image_name == self._get_default_runtime_image_name():
            self._build_default_runtime(runtime_name)

        logger.info("Deploying runtime: %s - Memory: %s - Timeout: %s", image_name, memory, timeout)

        if not self.app_id:
            logger.debug("Creating application %s", self.app_name)
            application = self.cf_client.create_application(
                create_application_details=oci.functions.models.CreateApplicationDetails(
                    compartment_id=self.compartment_id,
                    display_name=self.app_name,
                    subnet_ids=[self.subnet_id])).data
            self.app_id = application.id

        function_name = self._format_function_name(image_name, memory)
        function_tags = {"type": "lithops-runtime", "lithops_version": __version__}

        logger.debug("Checking if function %s already exists", function_name)
        function_id = self._get_function_id(function_name)

        if function_id:
            logger.debug("Function %s already exists. Updating it", function_name)
            self.cf_client.update_function(
                function_id=function_id,
                update_function_details=oci.functions.models.UpdateFunctionDetails(
                    image=image_name,
                    memory_in_mbs=memory,
                    timeout_in_seconds=timeout,
                    freeform_tags=function_tags))
        else:
            logger.debug("Creating function %s", function_name)
            self.cf_client.create_function(
                create_function_details=oci.functions.models.CreateFunctionDetails(
                    display_name=function_name,
                    application_id=self.app_id,
                    image=image_name,
                    memory_in_mbs=memory,
                    timeout_in_seconds=timeout,
                    freeform_tags=function_tags))

        logger.debug("Waitting for the function to be deployed")
        time.sleep(10)

        return self._generate_runtime_meta(runtime_name, memory)

    def _generate_runtime_meta(self, runtime_name, memory):
        """
        Invokes a function to get the runtime metadata
        """
        image_name = self._format_image_name(runtime_name)
        logger.debug("Extracting runtime metadata from %s", image_name)

        self.pre_invoke(runtime_name, memory)

        payload = {'log_level': logger.getEffectiveLevel(), 'get_metadata': True}

        fn_invoke_client = self._init_functions_invk_client(self.invoke_endpoint)

        response = fn_invoke_client.invoke_function(
            function_id=self.invoke_function_id,
            invoke_function_body=json.dumps(payload, default=str),
            fn_invoke_type='sync'
        )

        runtime_meta = None

        if response.status == 200:
            meta_dict = ast.literal_eval(response.data.text)
            runtime_meta = json.loads(json.dumps(meta_dict))

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(f"An error occurred: ({response.status}) {response.data.text}")

        return runtime_meta

    def delete_runtime(self, runtime_name, runtime_memory, version=__version__):
        """
        Deletes a runtime
        """
        image_name = self._format_image_name(runtime_name)
        logger.info(f'Deleting runtime: {image_name} - {runtime_memory}MB')

        if not self.app_id:
            logger.debug(f'Application {self.app_name} does not exist')
            return

        function_name = self._format_function_name(image_name, runtime_memory, version)
        function_id = self._get_function_id(function_name)
        if function_id:
            self.cf_client.delete_function(function_id)

    def list_runtimes(self, runtime_name='all'):
        """
        List all the runtimes deployed in the OCI Functions service
        return: list of tuples (container_image_name, memory, version)
        """
        logger.debug('Listing deployed runtimes')
        runtimes = []

        if not self.app_id:
            logger.debug(f'Application {self.app_name} does not exist')
            return runtimes

        # Get the list of functions within the application
        functions = self.cf_client.list_functions(self.app_id).data

        for function in functions:
            if function.display_name.startswith('lithops-worker'):
                memory = function.memory_in_mbs
                image_name = function.image
                version = function.freeform_tags['lithops_version']
                if runtime_name == 'all' or self._format_image_name(runtime_name) == image_name:
                    runtimes.append((image_name, memory, version, function.display_name))

        return runtimes

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if utils.CURRENT_PY_VERSION not in config.AVAILABLE_PY_RUNTIMES:
            raise Exception(
                f'Python {utils.CURRENT_PY_VERSION} is not available for Oracle '
                f'Functions. Please use one of {config.AVAILABLE_PY_RUNTIMES}'
            )

        if 'runtime' not in self.config or self.config['runtime'] == 'default':
            self.config['runtime'] = self._get_default_runtime_image_name()

        runtime_info = {
            'runtime_name': self.config['runtime'],
            'runtime_memory': self.config['runtime_memory'],
            'runtime_timeout': self.config['runtime_timeout'],
            'max_workers': self.config['max_workers'],
        }

        return runtime_info

    def _get_application_id(self, application_name):
        """
        Returns the application id of a given application
        """
        applications = self.cf_client.list_applications(self.compartment_id).data
        for app in applications:
            if app.display_name == application_name:
                return app.id

        return None

    def _get_function_id(self, function_name):
        # Get the list of functions within the application
        functions = self.cf_client.list_functions(self.app_id).data

        # Search for the function and return its OCID
        for function in functions:
            if function.display_name == function_name:
                return function.id

        return None
