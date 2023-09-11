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

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG


import oci
from oci.exceptions import ServiceError

from . import config

logger = logging.getLogger(__name__)

LITHOPS_FUNCTION_ZIP = 'lithops_oracle.zip'

class OracleCloudFunctionsBackend:

    def __init__(self, oracle_config, storage_config):
        self.name = 'oracle_f'
        self.type = 'faas'
        self.config = oracle_config
        self.cf_client = self._init_functions_client()
        self.region = oracle_config['region']
        self.tenancy = oracle_config['tenancy']
        self.compartment_id = oracle_config['compartment_id']
        self.user = oracle_config['user']
        self.namespace_name = oracle_config['namespace_name']
        self.default_application_name = f'{config.APPLICATION_NAME}_{self.user[-5:-1].lower()}'
        self.application_name = oracle_config.get('application', self.default_application_name)
        self.app_id = self._get_application_id(self.application_name)

        msg = COMPUTE_CLI_MSG.format('Oracle Functions')
        logger.info(f"{msg} - Region: {self.region}")

    def _init_functions_client(self):
        if 'key_file' in self.config and os.path.isfile(self.config['key_file']):
            return oci.functions.FunctionsManagementClient(config=self.config)
        else:
            self.signer = oci.auth.signers.get_resource_principals_signer()
            return oci.functions.FunctionsManagementClient(config={}, signer=self.signer)

    def _format_function_name(self, runtime_name, runtime_memory, version=__version__):
        name = f'{runtime_name}-{runtime_memory}-{version}'
        name_hash = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
        return f'lithops-worker-{runtime_name}-v{version.replace(".", "-")}-{name_hash}'

    def _unformat_function_name(self, function_name):
        runtime_name, hash = function_name.rsplit('-', 1)
        runtime_name = runtime_name.replace('lithops-worker-', '')
        runtime_name, version = runtime_name.rsplit('-v', 1)
        version = version.replace('-', '.')
        return version, runtime_name

    def _format_image_name(self, runtime_name):
        """
        Formats OC image name from runtime name
        """
        if 'ocir.io' not in runtime_name:
            return f'{self.region}.ocir.io/{self.namespace_name}/{runtime_name}'
        else:
            return runtime_name

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
            self.application_name,
            function_name
        )
        return runtime_key

    @staticmethod
    def _create_handler_bin(remove=True):
        """
        Create and return Lithops handler function as zip bytes
        @param remove: True to delete the zip archive after building
        @return: Lithops handler function as zip bytes
        """
        current_location = os.path.dirname(os.path.abspath(__file__))
        main_file = os.path.join(current_location, 'entry_point.py')
        utils.create_handler_zip(LITHOPS_FUNCTION_ZIP, main_file, 'entry_point.py')

        with open(LITHOPS_FUNCTION_ZIP, 'rb') as action_zip:
            action_bin = action_zip.read()

        if remove:
            os.remove(LITHOPS_FUNCTION_ZIP)

        return action_bin

    def _get_default_runtime_name(self):
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        return self._format_image_name(f'lithops-default-runtime-v{py_version}')

    def clean(self, **kwargs):
        """
        Deletes all runtimes from the current service
        """
        logger.debug('Going to delete all deployed runtimes')

        if not self._application_exists(self.application_name):
            return

        if self.app_id is None:
            return

        functions = self.cf_client.list_functions(self.app_id).data

        for function in functions:
            function_name = function.display_name
            logger.info(f'Going to delete runtime {function_name}')
            self.cf_client.delete_function(function.id)

        self.cf_client.delete_application(self.app_id)

    def invoke(self, runtime_name, memory=None, payload={}):
        """
        Invoke function
        """
        image_name = self._format_image_name(runtime_name)
        function_name = self._format_function_name(image_name, self.config['runtime_memory'])
        response = self.invoke_function(function_name, payload, 'detached')
        status_code = response.status

        if status_code == 202:
            return response.request_id
        elif status_code == 401:
            logger.debug(response.data.text)
            raise Exception('Unauthorized - Invalid API Key')
        elif status_code == 404:
            logger.debug(response.data.text)
            raise Exception(f"Lithops Runtime: {runtime_name} not deployed")
        else:
            logger.debug(response.data.text)
            raise Exception(f"An error occurred: {response.data.text}")

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
            cmd = f'{docker_path} build -t {image_name} -f {dockerfile} . '
        else:
            cmd = f'{docker_path} build -t {image_name} . '
        cmd = cmd + ' '.join(extra_args)

        # Create Lithops handler zip file
        try:
            self._create_handler_bin(remove=False)
            utils.run_command(cmd, return_result=True)
        finally:
            os.remove(LITHOPS_FUNCTION_ZIP)

        logger.debug(f'Pushing runtime {image_name} to Oracle Cloud Container Registry')
        if utils.is_podman(docker_path):
            cmd = f'{docker_path} push {image_name} --format docker --remove-signatures'
        else:
            cmd = f'{docker_path} push {image_name}'
        utils.run_command(cmd)

    def delete_runtime(self, runtime_name, runtime_memory, version=__version__):
        logger.info(f'Deleting runtime: {runtime_name} - {runtime_memory}MB')
        img_name = self._format_image_name(runtime_name)

        raise NotImplementedError()

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if 'runtime' not in self.config or self.config['runtime'] == 'default':
            self.config['runtime'] = self._get_default_runtime_name()

        runtime_info = {
            'runtime_name': self.config['runtime'],
            'runtime_memory': self.config['runtime_memory'],
            'runtime_timeout': self.config['runtime_timeout'],
            'max_workers': self.config['max_workers'],
        }

        return runtime_info

    def _application_exists(self, application_name):
        """
        Checks if a given application exists
        """
        applications = self.cf_client.list_applications(self.config['tenancy']).data

        for serv in applications:
            if serv.display_name == application_name:
                return True
        return False

    def _get_application_id(self, application_name):
        """
        Returns the application id of a given application
        """
        applications = self.cf_client.list_applications(self.config['tenancy']).data
        for serv in applications:
            if serv.display_name == application_name:
                return serv.id
        return None

    def invoke_function(self, function_name, payload, invoke_type=None):
        '''
        A wrapper for the function invokation API call.
        '''
        # Get the function ID
        function_ocid = self._get_function_ocid(function_name, self.app_id)
        # Retrieve the function's information, including the invoke endpoint
        fn_info = self.cf_client.get_function(function_ocid).data
        # Set the invoke endpoint
        invoke_endpoint = fn_info.invoke_endpoint
        # Prepare the Oracle Functions client with the invoke endpoint
        if 'key_file' in self.config and os.path.isfile(self.config['key_file']):
            fn_invoke_client = oci.functions.FunctionsInvokeClient(
                self.config,
                service_endpoint=invoke_endpoint
            )
        else:
            fn_invoke_client = oci.functions.FunctionsInvokeClient(
                config={},
                service_endpoint=invoke_endpoint,
                signer=self.signer
            )
        # Invoke the function with the payload
        response = fn_invoke_client.invoke_function(
            function_id=function_ocid,
            invoke_function_body=json.dumps(payload, default=str),
            fn_invoke_type=invoke_type
        )

        return response

    def deploy_runtime(self, runtime_name, memory, timeout):
        """
        Deploys a new runtime into Oracle Function Compute
        with the custom modules for lithops
        """
        logger.info("Deploying runtime: %s - Memory: %s Timeout: %s", runtime_name, memory, timeout)
        if not self._application_exists(self.application_name):
            logger.debug("Creating application %s", self.application_name)
            self.cf_client.create_application(
                create_application_details=oci.functions.models.CreateApplicationDetails(
                    compartment_id=self.tenancy,
                    display_name=self.application_name,
                    subnet_ids=[self.config['vcn']['subnet_ids']]))

        image_name = self._format_image_name(runtime_name)
        function_name = self._format_function_name(image_name, memory)
        logger.debug("Checking if function %s exists", function_name)

        existing_function = self._get_function_ocid(function_name, self.app_id)

        if existing_function is not None:
            logger.debug("Function %s already exists. Updating it", function_name)
            self.cf_client.update_function(
                function_id=existing_function.id,
                update_function_details=oci.functions.models.UpdateFunctionDetails(
                    image=image_name,
                    memory_in_mbs=memory,
                    timeout_in_seconds=timeout))
        else:
            logger.debug("Creating function %s", function_name)
            self.cf_client.create_function(
                create_function_details=oci.functions.models.CreateFunctionDetails(
                    display_name=function_name,
                    application_id=self.app_id,
                    image=image_name,
                    memory_in_mbs=memory,
                    timeout_in_seconds=timeout))

            max_retries = 5
            retry_interval = 5

            for i in range(max_retries):
                try:
                    metadata = self._generate_runtime_meta(function_name)
                    return metadata
                except ServiceError as e:
                    if e.status == 404 and i < max_retries - 1:
                        logger.debug("Function not found yet, waiting %s seconds before retrying...", retry_interval)
                        time.sleep(retry_interval)
                    else:
                        raise e

        metadata = self._generate_runtime_meta(function_name)
        return metadata

    def _generate_runtime_meta(self, function_name):
        logger.debug("Extracting runtime metadata from: %s", function_name)
        response = self.invoke_function(function_name, {"get_metadata": True})
        meta_dict = ast.literal_eval(response.data.text)
        result = json.dumps(meta_dict)
        result = json.loads(result)
        if 'lithops_version' in result:
            return result

    def _get_function_ocid(self, runtime_name, app_id):
        if app_id is None:
            raise Exception("Application %s not found.", app_id)

        # Get the list of functions within the found application
        functions = self.cf_client.list_functions(app_id).data

        # Search for the function and return its OCID
        for function in functions:
            if function.display_name == runtime_name:
                return function.id
        raise Exception("Function %s not found.", runtime_name)
