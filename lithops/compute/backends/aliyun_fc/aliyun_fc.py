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
import subprocess as sp
import uuid
import fc2
from . import config as backend_config
from lithops.utils import uuid_str
from lithops.version import __version__
import lithops

logger = logging.getLogger(__name__)

class AliyunFunctionComputeBackend:
    """
    A wrap-up around Aliyun Function Compute backend.
    """

    def __init__(self, config, storage_config):
        self.log_level = os.getenv('LITHOPS_LOGLEVEL')
        self.name = 'aliyun_fc'
        self.config = config
        self.service_name = backend_config.SERVICE_NAME
        self.version = 'lithops_{}'.format(__version__)

        self.fc_client = fc2.Client(endpoint=self.config['public_endpoint'],
                                    accessKeyID=self.config['access_key_id'],
                                    accessKeySecret=self.config['access_key_secret'])
                                    
        log_msg = 'Lithops v{} init for Aliyun Function Compute'.format(__version__)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)


    def create_runtime(self, docker_image_name, memory=backend_config.RUNTIME_TIMEOUT_DEFAULT,
                       timeout=backend_config.RUNTIME_TIMEOUT_DEFAULT):
        """
        Creates a new runtime into Aliyun Function Compute
        with the custom modules for lithops
        """
        logger.info('Creating new lithops runtime for Aliyun Function Compute')

        res = self.fc_client.list_services(prefix=self.service_name).data
        if len(res['services']) == 0:
            self.fc_client.create_service(self.service_name)
        
        if docker_image_name == 'default':
            handler_path = backend_config.HANDLER_FOLDER_LOCATION
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
            
            function_name = self._format_function_name(self.version, docker_image_name, memory)

            self.fc_client.create_function(serviceName=self.service_name, 
                                           functionName=function_name, 
                                           runtime=backend_config.PYTHON_RUNTIME,
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
        function_name = self._format_function_name(self.version, docker_image_name, memory)
        self.fc_client.delete_function(self.service_name, function_name)


    def invoke(self, docker_image_name, memory=None, payload={}):
        """
        Invoke function
        """
        function_name = self._format_function_name(self.version, docker_image_name, memory)
        
        res = self.fc_client.invoke_function(serviceName=self.service_name,
                                             functionName=function_name,
                                             payload=json.dumps(payload),
                                             headers={'x-fc-invocation-type': 'Async'})

        return res.headers['X-Fc-Request-Id']

                        
    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        function_name = self._format_function_name(self.version, docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.name, self.config['public_endpoint'], function_name)

        return runtime_key


    def _format_function_name(self, version, runtime_name, runtime_memory):
        version = version.replace('.', '-')

        if runtime_name != 'default':
            runtime_name = os.path.basename(runtime_name)
        runtime_name = runtime_name.replace('/', '_').replace(':', '_')\
                                .replace('-', '_').replace('.', '_')

        return '{}_{}_{}MB'.format(version, runtime_name, runtime_memory)


    def _create_function_handler_folder(self, handler_path, is_custom):
        logger.debug("Creating function handler folder in {}".format(handler_path))

        if not is_custom:
            os.mkdir(handler_path)

            # Add lithops base modules
            logger.debug("Installing base modules (via pip install)")
            current_location = os.path.dirname(os.path.abspath(__file__))
            requirements_file = os.path.join(current_location, 'requirements.txt')

            cmd = 'pip3 install -t {} -r {} --no-deps'.format(handler_path, requirements_file)
            child = sp.Popen(cmd, shell=True, stdout=sp.PIPE, stderr=sp.PIPE) # silent
            child.wait()
            logger.debug(child.stdout.read().decode())
            logger.debug(child.stderr.read().decode())

            if child.returncode != 0:
                cmd = 'pip install -t {} -r {} --no-deps'.format(handler_path, requirements_file)
                child = sp.Popen(cmd, shell=True, stdout=sp.PIPE, stderr=sp.PIPE) # silent
                child.wait()
                logger.debug(child.stdout.read().decode())
                logger.debug(child.stderr.read().decode())

                if child.returncode != 0:
                    logger.critical('Failed to install base modules')
                    exit(1)

        # Add function handler
        current_location = os.path.dirname(os.path.abspath(__file__))
        handler_file = os.path.join(current_location, 'entry_point.py')
        shutil.copy(handler_file, handler_path)

        # Add lithops module
        module_location = os.path.dirname(os.path.abspath(lithops.__file__))
        dst_location = os.path.join(handler_path, 'lithops')

        if os.path.isdir(dst_location):
            logger.warn("Using user specified 'lithops' module from the custom runtime folder. "
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
                                       runtime=backend_config.PYTHON_RUNTIME,
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



