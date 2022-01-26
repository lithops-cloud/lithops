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
import logging
import shutil
import json
import lithops
import fc2

from lithops.constants import COMPUTE_CLI_MSG, TEMP
from . import config as aliyunfc_config

logger = logging.getLogger(__name__)


class AliyunFunctionComputeBackend:
    """
    A wrap-up around Aliyun Function Compute backend.
    """

    def __init__(self, aliyun_fc_config, storage_config):
        logger.debug("Creating Aliyun Function Compute client")
        self.name = 'aliyun_fc'
        self.type = 'faas'
        self.config = aliyun_fc_config
        self.user_agent = aliyun_fc_config['user_agent']

        self.endpoint = aliyun_fc_config['public_endpoint']
        self.access_key_id = aliyun_fc_config['access_key_id']
        self.access_key_secret = aliyun_fc_config['access_key_secret']
        self.role_arn = aliyun_fc_config['role_arn']
        self.region = self.endpoint.split('.')[1]

        self.default_service_name = f'{aliyunfc_config.SERVICE_NAME}_{self.access_key_id[0:4].lower()}'
        self.service_name = aliyun_fc_config.get('service', self.default_service_name)

        logger.debug("Set Aliyun FC Service to {}".format(self.service_name))
        logger.debug("Set Aliyun FC Endpoint to {}".format(self.endpoint))

        self.fc_client = fc2.Client(endpoint=self.endpoint,
                                    accessKeyID=self.access_key_id,
                                    accessKeySecret=self.access_key_secret)

        msg = COMPUTE_CLI_MSG.format('Aliyun Function Compute')
        logger.info("{}".format(msg))

    def _format_function_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '_').replace(':', '_')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _unformat_function_name(self, function_name):
        runtime_name, memory = function_name.rsplit('_', 1)
        image_name = runtime_name.replace('_', '/', 1)
        image_name = image_name.replace('_', ':', -1)
        return image_name, int(memory.replace('MB', ''))

    def build_runtime(self, runtime_name, requirements_file, extra_args=[]):
        pass

    def deploy_runtime(self, runtime_name, memory, timeout):
        """
        Deploys a new runtime into Aliyun Function Compute
        with the custom modules for lithops
        """
        logger.debug(f"Deploying runtime: {runtime_name} - Memory: {memory} Timeout: {timeout}")

        if self.service_name == self.default_service_name:
            services = self.fc_client.list_services(prefix=self.service_name).data['services']
            service = None
            for serv in services:
                if serv['serviceName'] == self.service_name:
                    service = serv
                    break
            if not service:
                logger.debug("creating service {}".format(self.service_name))
                self.fc_client.create_service(self.service_name, role=self.role_arn)

        if runtime_name == 'default':
            runtime_name = aliyunfc_config.RUNTIME_DEFAULT
            handler_path = aliyunfc_config.HANDLER_FOLDER_LOCATION
            is_custom = False
        elif os.path.isdir(runtime_name):
            handler_path = runtime_name
            is_custom = True
        else:
            raise Exception('The path you provided for the custom runtime'
                            'does not exist: {}'.format(runtime_name))

        try:
            self._create_function_handler_folder(handler_path, is_custom=is_custom)
            function_name = self._format_function_name(runtime_name, memory)

            functions = self.fc_client.list_functions(self.service_name).data['functions']
            for function in functions:
                if function['functionName'] == function_name:
                    self.delete_runtime(runtime_name, memory)

            self.fc_client.create_function(
                serviceName=self.service_name,
                functionName=function_name,
                runtime=aliyunfc_config.RUNTIME_DEFAULT,
                handler='entry_point.main',
                codeDir=handler_path,
                memorySize=memory,
                timeout=timeout
            )

            metadata = self._generate_runtime_meta(function_name)

        finally:
            if not is_custom:
                self._delete_function_handler_folder(handler_path)

        return metadata

    def delete_runtime(self, runtime_name, memory):
        """
        Deletes a runtime
        """
        if runtime_name == 'default':
            runtime_name = aliyunfc_config.RUNTIME_DEFAULT
        function_name = self._format_function_name(runtime_name, memory)
        self.fc_client.delete_function(self.service_name, function_name)

    def clean(self):
        """"
        Deletes all runtimes from the current service
        """
        functions = self.fc_client.list_functions(self.service_name).data['functions']
        for function in functions:
            self.fc_client.delete_function(self.service_name, function['functionName'])
        self.fc_client.delete_service(self.service_name)

    def list_runtimes(self, runtime_name='all'):
        """
        List all the runtimes deployed in the Aliyun FC service
        return: list of tuples (docker_image_name, memory)
        """
        if runtime_name == 'default':
            runtime_name = aliyunfc_config.RUNTIME_DEFAULT

        runtimes = []
        functions = self.fc_client.list_functions(self.service_name).data['functions']

        for function in functions:
            name, memory = self._unformat_function_name(function['functionName'])
            if runtime_name == name or runtime_name == 'all':
                runtimes.append((name, memory))
        return runtimes

    def invoke(self, runtime_name, memory=None, payload={}):
        """
        Invoke function
        """
        if runtime_name == 'default':
            runtime_name = aliyunfc_config.RUNTIME_DEFAULT
        function_name = self._format_function_name(runtime_name, memory)

        try:
            res = self.fc_client.invoke_function(
                serviceName=self.service_name,
                functionName=function_name,
                payload=json.dumps(payload, default=str),
                headers={'x-fc-invocation-type': 'Async'}
            )
        except fc2.fc_exceptions.FcError as e:
            raise(e)

        return res.headers['X-Fc-Request-Id']

    def get_runtime_key(self, runtime_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        if runtime_name == 'default':
            runtime_name = aliyunfc_config.RUNTIME_DEFAULT
        function_name = self._format_function_name(runtime_name, runtime_memory)
        runtime_key = os.path.join(self.name, self.region, self.service_name, function_name)

        return runtime_key

    def _create_function_handler_folder(self, handler_path, is_custom):
        """
        Creates a local directory with all the required dependencies
        """
        logger.debug("Creating function handler folder in {}".format(handler_path))

        if not is_custom:
            self._delete_function_handler_folder(handler_path)
            os.mkdir(handler_path)

            # Add lithops base modules
            logger.debug("Installing base modules (via pip install)")
            req_file = os.path.join(TEMP, 'requirements.txt')
            with open(req_file, 'w') as reqf:
                reqf.write(aliyunfc_config.REQUIREMENTS_FILE)

            cmd = f'{sys.executable} -m pip install -t {handler_path} -r {req_file} --no-deps'
            if logger.getEffectiveLevel() != logging.DEBUG:
                cmd = cmd + " >{} 2>&1".format(os.devnull)
            res = os.system(cmd)
            if res != 0:
                raise Exception('There was an error building the runtime')

        # Add function handlerd
        current_location = os.path.dirname(os.path.abspath(__file__))
        handler_file = os.path.join(current_location, 'entry_point.py')
        shutil.copy(handler_file, handler_path)

        # Add lithops module
        module_location = os.path.dirname(os.path.abspath(lithops.__file__))
        dst_location = os.path.join(handler_path, 'lithops')

        if os.path.isdir(dst_location):
            logger.warning("Using user specified 'lithops' module from the custom runtime folder. "
                           "Please refrain from including it as it will be automatically installed anyway.")
        else:
            shutil.copytree(module_location, dst_location, ignore=shutil.ignore_patterns('__pycache__'))

    def _delete_function_handler_folder(self, handler_path):
        """
        Deletes local handler folder
        """
        shutil.rmtree(handler_path, ignore_errors=True)

    def _generate_runtime_meta(self, function_name):
        """
        Extract installed Python modules from Aliyun runtime
        """
        logger.info('Extracting preinstalls from Aliyun runtime')
        payload = {'log_level': logger.getEffectiveLevel(), 'get_preinstalls': True}
        try:
            res = self.fc_client.invoke_function(
                self.service_name, function_name,
                payload=json.dumps(payload, default=str),
                headers={'x-fc-invocation-type': 'Sync'}
            )
            runtime_meta = json.loads(res.data)

        except Exception:
            raise Exception("Unable to extract runtime modules preinstalls")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        logger.debug("Metadata extracted successfully")
        return runtime_meta
