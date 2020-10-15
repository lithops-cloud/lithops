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
import tempfile
import hashlib
import time
import json
import re
import subprocess as sp
import uuid
from . import config as azure_fa_config
from lithops.utils import version_str
from lithops.version import __version__
from .functionapps_client import FunctionAppClient
from azure.storage.queue import QueueService
from azure.storage.queue.models import QueueMessageFormat
import lithops

logger = logging.getLogger(__name__)

class AzureFunctionAppBackend:
    """
    A wrap-up around Azure Function Apps backend.
    """

    def __init__(self, config, storage_config):
        self.log_level = os.getenv('LITHOPS_LOGLEVEL')
        self.name = 'azure_fa'
        self.config = config

        self.fa_client = FunctionAppClient(self.config)
        self.queue_service = QueueService(account_name=self.config['account_name'],
                                          account_key=self.config['account_key'])
        self.queue_service.encode_function = QueueMessageFormat.text_base64encode
        self.queue_service.decode_function = QueueMessageFormat.text_base64decode


        log_msg = 'Lithops v{} init for Azure Function Apps'.format(__version__)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)


    def create_runtime(self, docker_image_name, memory=None, timeout=azure_fa_config.RUNTIME_TIMEOUT_DEFAULT):
        """
        Creates a new runtime into Azure Function Apps 
        from the provided Linux image for consumption plan
        """

        log_msg = 'Creating new Lithops runtime for Azure Function Apps'
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

        logger.info('Extracting preinstalls for Azure runtime')
        metadata = self._generate_runtime_meta()

        logger.info('Creating new Lithops runtime')
        action_name = self._format_action_name(docker_image_name)
        self._create_runtime(action_name)

        return metadata


    def delete_runtime(self, docker_image_name, extract_preinstalls=False):
        """
        Deletes a runtime
        """
        if extract_preinstalls:
            action_name = docker_image_name
        else:
            action_name = self._format_action_name(docker_image_name)

        self.fa_client.delete_action(action_name)
        queue_name = self._format_queue_name(docker_image_name, type='trigger')
        self.queue_service.delete_queue(queue_name)


    def invoke(self, docker_image_name, memory=None, payload={}):
        """
        Invoke function
        """        
        action_name = self._format_action_name(docker_image_name)
        queue_name = self._format_queue_name(action_name, type='trigger')
        
        try:
            msg = self.queue_service.put_message(queue_name, json.dumps(payload))
            activation_id = msg.id

        except Exception:
            logger.debug('Creating queue (invoke)')
            self.queue_service.create_queue(queue_name)
            return self.invoke(docker_image_name, memory=memory, payload=payload)

        return activation_id
                        

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_action_name(docker_image_name)
        runtime_key = os.path.join(self.name, action_name)

        return runtime_key


    def _format_action_name(self, action_name):
        sha_1 = hashlib.sha1()
        block = action_name.encode('ascii', errors='ignore')
        sha_1.update(block)
        tag = sha_1.hexdigest()[:8]

        sha_1 = hashlib.sha1()
        block = self.config['account_name'].encode('ascii', errors='ignore')
        sha_1.update(block)
        tag = tag + sha_1.hexdigest()[:8]
        
        version = re.sub(r'[/_:.-]', '', __version__)
        action_name = action_name[:16] + '-' + version[:5] + '-' + tag

        return action_name


    def _format_queue_name(self, action_name, type):
        #  Using different queue names because there is a delay between
        #  deleting a queue and creating another one with the same name
        return action_name + '-' + type


    def _create_runtime(self, action_name, extract_preinstalls=False):
        """
        Creates a new runtime with the base modules and lithops
        """

        def add_base_modules():
            cmd = 'pip3 install -t {} -r requirements.txt'.format(azure_fa_config.ACTION_MODULES_DIR)
            child = sp.Popen(cmd, shell=True, stdout=sp.PIPE, stderr=sp.PIPE) # silent
            child.wait()
            logger.debug(child.stdout.read().decode())
            logger.error(child.stderr.read().decode())

            if child.returncode != 0:
                cmd = 'pip install -t {} -r requirements.txt'.format(azure_fa_config.ACTION_MODULES_DIR)
                child = sp.Popen(cmd, shell=True, stdout=sp.PIPE, stderr=sp.PIPE) # silent
                child.wait()
                logger.debug(child.stdout.read().decode())
                logger.error(child.stderr.read().decode())

                if child.returncode != 0:
                    logger.critical('Failed to install base modules')
                    exit(1)

        def add_lithops_module():
            module_location = os.path.dirname(os.path.abspath(lithops.__file__))
            shutil.copytree(module_location, os.path.join(azure_fa_config.ACTION_MODULES_DIR, 'lithops'))

        def get_bindings_str(action_name, extract_preinstalls=False):
            if not extract_preinstalls:
                bindings = {
                    "scriptFile": "__init__.py",
                    "bindings": [
                        {
                            "name": "msgIn",
                            "type": "queueTrigger",
                            "direction": "in",
                            "queueName": self._format_queue_name(action_name, 'trigger'),
                            "connection": "AzureWebJobsStorage"
                        }
                    ]}
            else:
                bindings = {
                    "scriptFile": "__init__.py",
                    "bindings": [
                        {
                            "name": "msgIn",
                            "type": "queueTrigger",
                            "direction": "in",
                            "queueName": self._format_queue_name(action_name,
                                                                 type='trigger'),
                            "connection": "AzureWebJobsStorage"
                        },
                        {
                            "name": "msgOut",
                            "type": "queue",
                            "direction": "out",
                            "queueName": self._format_queue_name(action_name,
                                                                 type='result'),
                            "connection": "AzureWebJobsStorage"
                        }]}
            return json.dumps(bindings)

        initial_dir = os.getcwd()
        temp_folder = next(tempfile._get_candidate_names())
        os.mkdir(temp_folder)
        os.chdir(temp_folder)

        try:

            # Create project folder from template
            project_template = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'action')
            project_dir = os.path.join(initial_dir, temp_folder, action_name)
            shutil.copytree(project_template, project_dir)
            
            os.chdir(project_dir)
            action_dir = os.path.join(project_dir, action_name)
            os.rename('action', action_dir)
            
            # Add the base dependencies and current lithops module
            logger.debug('Adding runtime base modules')
            os.makedirs(azure_fa_config.ACTION_MODULES_DIR, exist_ok=True)
            add_base_modules()
            add_lithops_module()

            # Set entry point file
            if extract_preinstalls:
                entry_point_file = 'extract_preinstalls_action.py'
            else:
                entry_point_file = 'handler_action.py'

            os.rename(os.path.join(action_dir, entry_point_file), 
                        os.path.join(action_dir, '__init__.py'))

            # Edit the function's bindings for it to be a queue triggered function
            with open(os.path.join(action_dir, 'function.json'), 'w') as bindings_file:
                bindings_file.write(get_bindings_str(action_name, extract_preinstalls))
                
            # Create trigger queue, create action
            logger.debug('Creating trigger queue')
            queue_name = self._format_queue_name(action_name, type='trigger')
            self.queue_service.create_queue(queue_name)

            self.fa_client.create_action(action_name)

        except Exception as e:
            raise Exception("Unable to create the new runtime", e)

        finally: 
            os.chdir(initial_dir)
            shutil.rmtree(temp_folder, ignore_errors=True) # Remove tmp project folder
        

    def _generate_runtime_meta(self):
        """
        Extract installed Python modules from Azure runtime
        """
        
        action_name = 'lithops-extract-preinstalls-' + get_unique_id()
        self._create_runtime(action_name, extract_preinstalls=True)

        logger.info("Invoking 'extract-preinstalls' action")
        try:
            runtime_meta = self._invoke_with_result(action_name)
        except Exception:
            raise Exception("Unable to invoke 'extract-preinstalls' action")
        try:
            self.delete_runtime(action_name, extract_preinstalls=True)
        except Exception:
            raise Exception("Unable to delete 'extract-preinstalls' action")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        logger.info("Extracted metadata succesfully")
        return runtime_meta


    def _invoke_with_result(self, action_name):
        result_queue_name = self._format_queue_name(action_name, type='result')
        self.queue_service.create_queue(result_queue_name)
        trigger_queue_name = self._format_queue_name(action_name, type='trigger')
        self.queue_service.put_message(trigger_queue_name, '')

        msg = []
        while not msg:
            msg = self.queue_service.get_messages(result_queue_name, num_messages=1)
            time.sleep(0.5)

        result_str = msg[0].content
        self.queue_service.delete_queue(result_queue_name)
        
        return json.loads(result_str)

def get_unique_id():
    return str(uuid.uuid4()).replace('-', '')[:10]

