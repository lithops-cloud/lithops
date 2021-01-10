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
import logging
import shutil
import json
import sys
import lithops
import fc2

from lithops.utils import uuid_str, is_lithops_worker, version_str
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG, TEMP
from . import config as aliyunfc_config

logger = logging.getLogger(__name__)


class AliyunFunctionComputeBackend:
    """
    A wrap-up around Aliyun Function Compute backend.
    """

    def __init__(self, aliyun_fc_config, storage_config):
        logger.debug("Creating Aliyun Function Compute client")
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.name = 'aliyun_fc'
        self.config = aliyun_fc_config
        self.is_lithops_worker = is_lithops_worker()
        self.version = 'lithops_{}'.format(__version__)

        self.user_agent = aliyun_fc_config['user_agent']
        if 'service' in aliyun_fc_config:
            self.service_name = aliyun_fc_config['service']
        else:
            self.service_name = aliyunfc_config.SERVICE_NAME

        self.endpoint = aliyun_fc_config['public_endpoint']
        self.access_key_id = aliyun_fc_config['access_key_id']
        self.access_key_secret = aliyun_fc_config['access_key_secret']

        logger.debug("Set Aliyun FC Service to {}".format(self.service_name))
        logger.debug("Set Aliyun FC Endpoint to {}".format(self.endpoint))

        self.fc_client = fc2.Client(endpoint=self.endpoint,
                                    accessKeyID=self.access_key_id,
                                    accessKeySecret=self.access_key_secret)

        msg = COMPUTE_CLI_MSG.format('Aliyun Function Compute')
        logger.info("{}".format(msg))

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '_').replace(':', '_')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _unformat_action_name(self, action_name):
        runtime_name, memory = action_name.rsplit('_', 1)
        image_name = runtime_name.replace('_', '/', 1)
        image_name = image_name.replace('_', ':', -1)
        return image_name, int(memory.replace('MB', ''))

    def _get_default_runtime_image_name(self):
        python_version = version_str(sys.version_info)
        return aliyunfc_config.RUNTIME_DEFAULT[python_version]

    def _delete_function_handler_zip(self):
        os.remove(aliyunfc_config.FH_ZIP_LOCATION)

    def create_runtime(self, docker_image_name, memory=aliyunfc_config.RUNTIME_TIMEOUT_DEFAULT,
                       timeout=aliyunfc_config.RUNTIME_TIMEOUT_DEFAULT):
        """
        Creates a new runtime into Aliyun Function Compute
        with the custom modules for lithops
        """

        logger.info('Creating new Lithops runtime for Aliyun Function Compute')

        res = self.fc_client.list_services(prefix=self.service_name).data

        if len(res['services']) == 0:
            logger.info("creating service {}".format(self.service_name))
            self.fc_client.create_service(self.service_name)

        if docker_image_name == 'default':
            handler_path = aliyunfc_config.HANDLER_FOLDER_LOCATION
            is_custom = False
        elif os.path.isdir(docker_image_name):
            handler_path = docker_image_name
            is_custom = True
        else:
            raise Exception('The path you provided for the custom runtime'
                            'does not exist: {}'.format(docker_image_name))

        try:
            self._create_function_handler_folder(handler_path, is_custom=is_custom)
            metadata = self._generate_runtime_meta(handler_path)
            function_name = self._format_action_name(docker_image_name, memory)

            self.fc_client.create_function(serviceName=self.service_name,
                                           functionName=function_name,
                                           runtime=self._get_default_runtime_image_name(),
                                           handler='entry_point.main',
                                           codeDir=handler_path,
                                           memorySize=memory,
                                           timeout=timeout)

        finally:
            if not is_custom:
                self._delete_function_handler_folder(handler_path)

        return metadata

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()
        action_name = self._format_action_name(docker_image_name, memory)
        self.fc_client.delete_function(self.service_name, action_name)

    def clean(self):
        """"
        deletes all runtimes from the current service
        """
        actions = self.fc_client.list_functions(self, self.service_name, prefix="lithops")
        for action in actions:
            self.fc_client.delete_function(self.service_name, action)
        if self.service_name.startswith("lithops"):
            self.fc_client.delete_service(self.service_name)

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed in the Aliyun FC service
        return: list of tuples (docker_image_name, memory)
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()

        runtimes = []
        actions = self.fc_client.list_functions(self.service_name)

        for action in actions:
            action_image_name, memory = self._unformat_action_name(action['name'])
            if docker_image_name == action_image_name or docker_image_name == 'all':
                runtimes.append((action_image_name, memory))
        return runtimes

    def invoke(self, docker_image_name, memory=None, payload={}):
        """
        Invoke function
        """
        action_name = self._format_action_name(docker_image_name, memory)

        res = self.fc_client.invoke_function(serviceName=self.service_name,
                                             functionName=action_name,
                                             payload=json.dumps(payload),
                                             headers={'x-fc-invocation-type': 'Async'})

        return res.headers['X-Fc-Request-Id']

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_action_name(docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.name, self.config['public_endpoint'].split('.')[1], action_name)

        return runtime_key

    def _create_function_handler_folder(self, handler_path, is_custom):
        # logger.debug("Creating function handler folder in {}".format(handler_path))
        print("Creating function handler folder in {}".format(handler_path))

        if not is_custom:
            os.mkdir(handler_path)

            # Add lithops base modules
            logger.debug("Installing base modules (via pip install)")
            req_file = os.path.join(TEMP, 'requirements.txt')
            with open(req_file, 'w') as reqf:
                reqf.write(aliyunfc_config.REQUIREMENTS_FILE)

            cmd = 'pip3 install -t {} -r {} --no-deps'.format(handler_path, req_file)
            if logger.getEffectiveLevel() != logging.DEBUG:
                cmd = cmd + " >{} 2>&1".format(os.devnull)
            res = os.system(cmd)
            if res != 0:
                raise Exception('There was an error building the runtime')

        # Add function handler
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
            shutil.copytree(module_location, dst_location)

    def _delete_function_handler_folder(self, handler_path):
        shutil.rmtree(handler_path)

    def _generate_runtime_meta(self, handler_path):
        """
        Extract installed Python modules from Aliyun runtime
        """

        logger.info('Extracting preinstalls for Aliyun runtime')
        function_name = 'lithops-extract-preinstalls-' + uuid_str()[:8]

        self.fc_client.create_function(serviceName=self.service_name,
                                       functionName=function_name,
                                       runtime=self._get_default_runtime_image_name(),
                                       handler='entry_point.extract_preinstalls',
                                       codeDir=handler_path,
                                       memorySize=128)

        logger.info("Invoking 'extract-preinstalls' function")
        try:
            res = self.fc_client.invoke_function(self.service_name, function_name,
                headers={'x-fc-invocation-type': 'Sync'})
            runtime_meta = json.loads(res.data)

        except Exception:
            raise Exception("Unable to invoke 'extract-preinstalls' function")
        finally:
            try:
                self.fc_client.delete_function(self.service_name, function_name)
            except Exception:
                raise Exception("Unable to delete 'extract-preinstalls' function")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        logger.info("Extracted metadata succesfully")
        return runtime_meta
