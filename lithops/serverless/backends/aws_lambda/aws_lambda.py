#
# Copyright Cloudlab URV 2020
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import shutil
import logging
import boto3
import botocore.session
import time
import json
import zipfile
import sys
import subprocess
import tempfile
import textwrap
import lithops
from . import config as aws_lambda_config
from .config import NUMERICS_LAYERS, REQUIREMENTS

logger = logging.getLogger(__name__)


class AWSLambdaBackend:
    '''
    A wrap-up around AWS Boto3 API
    '''

    def __init__(self, aws_lambda_config, storage_config):
        logger.debug('Creating AWS Lambda client')

        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.name = 'aws_lambda'
        self.aws_lambda_config = aws_lambda_config

        self.package = 'lithops_v'+lithops.__version__
        self.region_name = aws_lambda_config['region_name']
        self.role_arn = aws_lambda_config['execution_role']
        self.layer_key = '_'.join([self.package.replace('.', '-'), '_layer'])

        logger.debug('Creating Boto3 AWS Session and Lambda Client')
        self.aws_session = boto3.Session(aws_access_key_id=aws_lambda_config['access_key_id'],
                                         aws_secret_access_key=aws_lambda_config['secret_access_key'],
                                         region_name=self.region_name)
        self.lambda_client = self.aws_session.client(
            'lambda', region_name=self.region_name)

        log_msg = 'Lithops v{} init for AWS Lambda - Region: {}' \
            .format(lithops.__version__, self.region_name)
        logger.info(log_msg)
        if not self.log_active:
            print(log_msg)

    def __format_action_name(self, runtime_name, runtime_memory):
        runtime_name = (self.package+'_'+runtime_name).replace('.', '-')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def __unformat_action_name(self, action_name):
        split = action_name.split('_')
        runtime_name = split[1].replace('-', '.')
        runtime_memory = int(split[2].replace('MB', ''))
        return runtime_name, runtime_memory

    def __get_scipy_layer_arn(self, runtime_name):
        '''
        Retruns arn for the existing numerics lambda layer based on region 
        return : layer arn
        '''
        runtime_name = runtime_name.replace('p', 'P').replace('.', '')
        arn = ':'.join([
            'arn',
            'aws',
            'lambda',
            self.region_name,
            NUMERICS_LAYERS[self.region_name],
            'layer',
            'AWSLambda-{}-SciPy1x'.format(runtime_name),
            '29'
        ])
        return arn
    
    def __setup_layers(self, runtime_name):
        # Check if Lithops dependencies layer is already deployed
        layers = self.list_layers(runtime_name)
        dep_layer = [layer for layer in layers if layer['LayerName'] == self.layer_key]
        if len(dep_layer) == 1:
            layer = dep_layer.pop()
            dependencies_layer = layer['LatestMatchingVersion']['LayerVersionArn']
        else:
            dependencies_layer = None

        # Create Lithops dependencies layer
        if dependencies_layer is None:
            layer_bytes = self.__build_layer_zip()
            dependencies_layer = self.create_layer(self.layer_key,
                                                   runtime_name,
                                                   layer_bytes)

        return [dependencies_layer, self.__get_scipy_layer_arn(runtime_name)]

    def __build_layer_zip(self):
        '''
        Downloads and builds module dependencies for Lithops lambda runtime
        return : layer zip bytes
        '''
        def add_folder_to_zip(zip_file, full_dir_path, sub_dir=''):
            for file in os.listdir(full_dir_path):
                full_path = os.path.join(full_dir_path, file)
                if os.path.isfile(full_path):
                    zip_file.write(full_path, os.path.join(
                        sub_dir, file), zipfile.ZIP_DEFLATED)
                elif os.path.isdir(full_path) and '__pycache__' not in full_path:
                    add_folder_to_zip(zip_file, full_path,
                                      os.path.join(sub_dir, file))

        # Delete layer directory if it exists
        if os.path.exists(aws_lambda_config.LAYER_DIR_PATH):
            if os.path.isdir(aws_lambda_config.LAYER_DIR_PATH):
                shutil.rmtree(aws_lambda_config.LAYER_DIR_PATH)
            elif os.path.isfile(aws_lambda_config.LAYER_DIR_PATH):
                os.remove(aws_lambda_config.LAYER_DIR_PATH)

        os.makedirs(aws_lambda_config.LAYER_DIR_PATH)

        # Install modules
        dependencies = [dependency.strip().replace(' ', '')
                        for dependency in REQUIREMENTS]
        command = [
            sys.executable,
            '-m', 'pip', 'install', '-t',
            aws_lambda_config.LAYER_DIR_PATH]
        command.extend(dependencies)
        subprocess.check_call(command)

        # Compress modules
        with zipfile.ZipFile(aws_lambda_config.LAYER_ZIP_PATH, 'w') as layer_zip:
            add_folder_to_zip(layer_zip,
                              os.path.join(tempfile.gettempdir(),
                                           'modules'))

        # Read zip as bytes
        with open(aws_lambda_config.LAYER_ZIP_PATH, 'rb') as layer_zip:
            layer_bytes = layer_zip.read()

        return layer_bytes

    def __create_handler_bin(self):
        '''
        Creates Lithops handler zip
        return : zip binary
        '''
        logger.debug('Creating function handler zip in {}'
                     .format(aws_lambda_config.ACTION_ZIP_PATH))

        def add_folder_to_zip(zip_file, full_dir_path, sub_dir=''):
            for file in os.listdir(full_dir_path):
                full_path = os.path.join(full_dir_path, file)
                if os.path.isfile(full_path):
                    zip_file.write(full_path,
                                   os.path.join('lithops', sub_dir, file),
                                   zipfile.ZIP_DEFLATED)
                elif os.path.isdir(full_path) and '__pycache__' not in full_path:
                    add_folder_to_zip(zip_file,
                                      full_path,
                                      os.path.join(sub_dir, file))

        try:
            with zipfile.ZipFile(aws_lambda_config.ACTION_ZIP_PATH, 'w') as lithops_zip:
                current_location = os.path.dirname(os.path.abspath(__file__))
                module_location = os.path.dirname(os.path.abspath(lithops.__file__))
                main_file = os.path.join(current_location, 'entry_point.py')
                lithops_zip.write(main_file,
                                      '__main__.py',
                                      zipfile.ZIP_DEFLATED)
                add_folder_to_zip(lithops_zip, module_location)

            with open(aws_lambda_config.ACTION_ZIP_PATH, 'rb') as action_zip:
                action_bin = action_zip.read()
        except Exception as e:
            raise Exception('Unable to create the {} package: {}'
                            .format(aws_lambda_config.ACTION_ZIP_PATH, e))
        return action_bin

    def build_runtime(self):
        pass

    def update_runtime(self, runtime_name, code, memory=3008, timeout=900):
        '''
        Updates code, memory and time of existing lambda function
        '''
        function_name = self.__format_action_name(runtime_name, memory)
        logger.debug('Updating function {} code/config'.format(function_name))

        response = self.lambda_client.update_function_code(
            FunctionName=function_name,
            ZipFile=code,
            Publish=False
        )

        if response['ResponseMetadata']['HTTPStatusCode'] == 201:
            logger.debug(
                'OK --> Updated function code {}'.format(function_name))
        else:
            msg = 'An error occurred updating function code {}: {}'.format(
                function_name, response)
            raise Exception(msg)

        layers = self.__setup_layers(runtime_name)

        response = self.lambda_client.update_function_configuration(
            FunctionName=function_name,
            Role=self.role_arn,
            Timeout=timeout,
            MemorySize=memory,
            Layers=layers
        )

        if response['ResponseMetadata']['HTTPStatusCode'] == 201:
            logger.debug(
                'OK --> Updated function config {}'.format(function_name))
        else:
            msg = 'An error occurred updating function config {}: {}'.format(
                function_name, response)
            raise Exception(msg)

    def create_runtime(self, runtime_name, memory=3008, code=None, timeout=900):
        '''
        Create a Lithops runtime as an AWS Lambda function
        '''
        function_name = self.__format_action_name(runtime_name, memory)
        logger.debug('Creating new Lithops lambda runtime: {}'.format(function_name))

        runtime_meta = self.__generate_runtime_meta(runtime_name)

        if code is None:
            code = self.__create_handler_bin()

        layers = self.__setup_layers(runtime_name)
        try:
            response = self.lambda_client.create_function(
                FunctionName=function_name,
                Runtime=runtime_name,
                Role=self.role_arn,
                Handler='__main__.lambda_handler',
                Code={
                    'ZipFile': code
                },
                Description=self.package,
                Timeout=timeout,
                MemorySize=memory,
                Layers=layers
            )

            if response['ResponseMetadata']['HTTPStatusCode'] == 201:
                logger.debug('OK --> Created action {}'.format(runtime_name))
            else:
                msg = 'An error occurred creating/updating action {}: {}'.format(
                    runtime_name, response)
                raise Exception(msg)
        except self.lambda_client.exceptions.ResourceConflictException:
            logger.debug(
                '{} lambda function already exists. It will be replaced.')
            self.update_runtime(runtime_name, code, memory, timeout)

        return runtime_meta

    def delete_runtime(self, runtime_name, memory):
        '''
        Deletes lambda runtime from its runtime name and memory
        '''
        logger.debug('Deleting lambda runtime: {}'.format(runtime_name))

        response = self.lambda_client.delete_function(
            FunctionName=runtime_name
        )

        if response['ResponseMetadata']['HTTPStatusCode'] == 204:
            logger.debug('OK --> Deleted function {}'.format(runtime_name))
        else:
            msg = 'An error occurred creating/updating action {}: {}'.format(
                runtime_name, response)
            raise Exception(msg)

    def delete_all_runtimes(self):
        '''
        Deletes all Lithops Lambda runtimes
        '''
        logger.debug('Deleting all runtimes')

        response = self.lambda_client.list_functions(
            MasterRegion=self.region_name
        )

        for runtime in response['Functions']:
            if 'lithops' in runtime['FunctionName']:
                runtime_name, runtime_memory = self.__unformat_action_name(runtime['FunctionName'])
                self.delete_runtime(runtime_name, runtime_memory)

    def list_runtimes(self, docker_image_name='all'):
        '''
        List all the lambda runtimes deployed.
        return: Array of tuples (function_name, memory)
        '''
        functions = []
        response = self.lambda_client.list_functions()
        for function in response['Functions']:
            if 'lithops' in function['FunctionName']:
                functions.append((function['FunctionName'], function['MemorySize']))
        
        while 'NextMarker' in response:
            response = self.lambda_client.list_functions(Marker=response['NextMarker'])
            for function in response['Functions']:
                if 'lithops' in function['FunctionName']:
                    functions.append((function['FunctionName'], function['MemorySize']))

        return functions

    def create_layer(self, layer_name, runtime_name, zipfile):
        '''
        Creates lambda layer from bin code
        '''
        logger.debug('Creating lambda layer: {}'.format(layer_name))
        response = self.lambda_client.publish_layer_version(
            LayerName=layer_name,
            Description=self.package,
            Content={
                'ZipFile': zipfile
            },
            CompatibleRuntimes=[runtime_name]
        )

        if response['ResponseMetadata']['HTTPStatusCode'] == 201:
            logger.debug('OK --> Layer {} created'.format(layer_name))
            return response['LayerVersionArn']
        else:
            msg = 'An error occurred creating layer {}: {}'.format(
                layer_name, response)
            raise Exception(msg)

    def delete_layer(self, layer_arn, version_number=None):
        '''
        Deletes lambda layer from its arn
        '''
        logger.debug('Deleting lambda layer: {}'.format(layer_arn))

        if version_number is None:
            version_number = layer_arn.split(':')[-1]

        response = self.lambda_client.delete_layer_version(
            LayerName=layer_arn,
            VersionNumber=version_number
        )

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            logger.debug('OK --> Layer {} deleted'.format(layer_arn))
            return response['LayerVersionArn']
        else:
            msg = 'An error occurred deleting layer {}: {}'.format(
                layer_arn, response)
            raise Exception(msg)

    def list_layers(self, runtime_name=None):
        '''
        Gets all Lambda Layers available for the Python runtime selected
        '''
        logger.debug('Listing lambda layers: {}'.format(runtime_name))
        response = self.lambda_client.list_layers(
            CompatibleRuntime=runtime_name
        )

        layers = response['Layers'] if 'Layers' in response else []
        logger.debug('Layers: {}'.format(layers))
        return layers

    def invoke(self, runtime_name, runtime_memory, payload, self_invoked=False):
        '''
        Invoke lambda function asynchronously
        '''
        exec_id = payload['executor_id']
        call_id = payload['call_id']

        function_name = self.__format_action_name(runtime_name, runtime_memory)

        start = time.time()
        try:
            response = self.lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='Event',
                Payload=json.dumps(payload)
            )
        except Exception as e:
            log_msg = ('ExecutorID {} - Function {} invocation failed: {}'.format(exec_id, call_id, str(e)))
            logger.debug(log_msg)
            if self_invoked:
                return None
            return self.invoke(runtime_name, runtime_memory, payload, self_invoked=True)

        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        if response['ResponseMetadata']['HTTPStatusCode'] == 202:
            log_msg = ('ExecutorID {} - Function {} invocation done! ({}s) - Activation ID: '
                       '{}'.format(exec_id, call_id, resp_time, response['ResponseMetadata']['RequestId']))
            logger.debug(log_msg)
            return response['ResponseMetadata']['RequestId']
        else:
            logger.debug(response)
            if response['ResponseMetadata']['HTTPStatusCode'] == 401:
                raise Exception('Unauthorized - Invalid API Key')
            elif response['ResponseMetadata']['HTTPStatusCode'] == 404:
                raise Exception('Lithops Runtime: {} not deployed'.format(runtime_name))
            elif response['ResponseMetadata']['HTTPStatusCode'] == 429:
                # Too many concurrent requests in flight
                return None
            else:
                raise Exception(response)

    def invoke_with_result(self, runtime_name, runtime_memory, payload={}):
        '''
        Invoke lambda function and wait for result
        '''
        function_name = self.__format_action_name(runtime_name, runtime_memory)

        response = self.lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps(payload)
        )

        return json.loads(response['Payload'].read())

    def get_runtime_key(self, runtime_name, runtime_memory):
        '''
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        '''
        action_name = self.__format_action_name(runtime_name, runtime_memory)
        runtime_key = '/'.join([self.name, self.region_name, self.region_name, action_name])

        return runtime_key

    def __generate_runtime_meta(self, runtime_name):
        '''
        Extract preinstalled Python modules from lambda function execution environment
        return : runtime meta dictionary
        '''
        action_code = '''
        import sys
        import pkgutil

        def lambda_handler(event, context):
            runtime_meta = dict()
            mods = list(pkgutil.iter_modules())
            runtime_meta['preinstalls'] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
            python_version = sys.version_info
            runtime_meta['python_ver'] = str(python_version[0])+'.'+str(python_version[1])
            return runtime_meta
        '''
        action_location = os.path.join(tempfile.gettempdir(), 'extract_preinstalls_aws.py')
        with open(action_location, 'w') as f:
            f.write(textwrap.dedent(action_code))

        modules_zip_action = os.path.join(tempfile.gettempdir(), 'extract_preinstalls_aws.zip')
        with zipfile.ZipFile(modules_zip_action, 'w') as extract_modules_zip:
            extract_modules_zip.write(action_location, '__main__.py')
        with open(modules_zip_action, 'rb') as modules_zip:
            action_bytes = modules_zip.read()

        memory = 192
        try:
            self.lambda_client.create_function(
                FunctionName=self.__format_action_name(runtime_name, memory),
                Runtime=runtime_name,
                Role=self.role_arn,
                Handler='__main__.lambda_handler',
                Code={
                        'ZipFile': action_bytes
                },
                Description=self.package,
                Timeout=aws_lambda_config.RUNTIME_TIMEOUT_DEFAULT,
                MemorySize=memory
            )
        except Exception as e:
            raise Exception('Unable to deploy "modules" action: {}'.format(e))

        logger.debug('Extracting Python modules list from: {}'.format(runtime_name))

        runtime_meta = self.invoke_with_result(runtime_name, memory)
        self.delete_runtime(self.__format_action_name(runtime_name, memory), memory)

        if 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta
