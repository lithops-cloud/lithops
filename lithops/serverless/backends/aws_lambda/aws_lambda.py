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
import uuid

import boto3
import time
import json
import zipfile
import sys
import subprocess
import textwrap
import lithops
import botocore.exceptions
from . import config as lambda_config
from ....storage import InternalStorage
from ....utils import version_str
from ....constants import TEMP as TEMP_PATH

logger = logging.getLogger(__name__)

LAYER_DIR_PATH = os.path.join(TEMP_PATH, 'modules', 'python')
LAYER_ZIP_PATH = os.path.join(TEMP_PATH, 'lithops_layer.zip')
ACTION_ZIP_PATH = os.path.join(TEMP_PATH, 'lithops_runtime.zip')


# Auxiliary function to recursively add a directory to a zip archive
def add_directory_to_zip(zip_file, full_dir_path, sub_dir=''):
    for file in os.listdir(full_dir_path):
        full_path = os.path.join(full_dir_path, file)
        if os.path.isfile(full_path):
            zip_file.write(full_path, os.path.join(sub_dir, file), zipfile.ZIP_DEFLATED)
        elif os.path.isdir(full_path) and '__pycache__' not in full_path:
            add_directory_to_zip(zip_file, full_path, os.path.join(sub_dir, file))


class AWSLambdaBackend:
    """
    A wrap-up around AWS Boto3 API
    """

    def __init__(self, aws_lambda_config, storage_config):
        """
        Initialize AWS Lambda Backend
        """
        logger.debug('Creating AWS Lambda client')

        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.name = 'aws_lambda'
        self.aws_lambda_config = aws_lambda_config

        self.user_key = aws_lambda_config['access_key_id'][-4:]
        self.package = 'lithops_v{}_{}'.format(lithops.__version__, self.user_key)
        self.region_name = aws_lambda_config['region_name']
        self.role_arn = aws_lambda_config['execution_role']

        logger.debug('Creating Boto3 AWS Session and Lambda Client')
        self.aws_session = boto3.Session(aws_access_key_id=aws_lambda_config['access_key_id'],
                                         aws_secret_access_key=aws_lambda_config['secret_access_key'],
                                         region_name=self.region_name)
        self.lambda_client = self.aws_session.client('lambda', region_name=self.region_name)

        self.internal_storage = InternalStorage(storage_config)

        log_msg = 'Lithops v{} init for AWS Lambda - Region: {}'.format(lithops.__version__, self.region_name)
        logger.info(log_msg)
        if not self.log_active:
            print(log_msg)

    @property
    def _python_runtime_name(self):
        return 'python{}'.format(version_str(sys.version_info))

    @property
    def _numerics_layer_arn(self):
        """
        Returns arn for the existing numerics lambda layer based on region
        return : layer arn
        """
        fmt_python_version = self._python_runtime_name.replace('p', 'P').replace('.', '')
        arn = ':'.join([
            'arn',
            'aws',
            'lambda',
            self.region_name,
            lambda_config.NUMERICS_LAYERS[self.region_name],
            'layer',
            'AWSLambda-{}-SciPy1x'.format(fmt_python_version),
            '29'
        ])
        return arn

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = (self.package + '_' + runtime_name).replace('.', '-')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _unformat_action_name(self, action_name):
        split = action_name.split('_')
        runtime_name = '_'.join(split[3:-1])
        runtime_memory = int(split[-1].replace('MB', ''))
        return runtime_name, runtime_memory

    def _format_layer_name(self, runtime_name):
        return '_'.join([self.package, runtime_name, 'layer']).replace('.', '-')

    def _check_runtime_layer(self, runtime_name):
        # Check if Lithops dependencies layer for this runtime is already deployed
        layers = self._list_layers(runtime_name)
        dep_layer = [layer for layer in layers if layer[0] == self._format_layer_name(runtime_name)]
        if len(dep_layer) == 1:
            _, layer_arn = dep_layer.pop()
            return layer_arn
        else:
            return None

    def _create_handler_bin(self):
        """
        Creates Lithops handler zip
        return : zip binary
        """
        logger.debug('Creating function handler zip in {}'.format(ACTION_ZIP_PATH))

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
            with zipfile.ZipFile(ACTION_ZIP_PATH, 'w') as lithops_zip:
                current_location = os.path.dirname(os.path.abspath(__file__))
                module_location = os.path.dirname(os.path.abspath(lithops.__file__))
                main_file = os.path.join(current_location, 'entry_point.py')
                lithops_zip.write(main_file,
                                  '__main__.py',
                                  zipfile.ZIP_DEFLATED)
                add_folder_to_zip(lithops_zip, module_location)

            with open(ACTION_ZIP_PATH, 'rb') as action_zip:
                action_bin = action_zip.read()
        except Exception as e:
            raise Exception('Unable to create {} package: {}'.format(ACTION_ZIP_PATH, e))
        return action_bin

    def _create_layer(self, runtime_name):
        logger.debug('Creating lambda layer for runtime {}'.format(runtime_name))
        layer_modules = self._get_runtime_modules(runtime_name)

        # Delete layer directory if it exists
        if os.path.exists(LAYER_DIR_PATH):
            if os.path.isdir(LAYER_DIR_PATH):
                shutil.rmtree(LAYER_DIR_PATH)
            elif os.path.isfile(LAYER_DIR_PATH):
                os.remove(LAYER_DIR_PATH)

        # Create target layer directory
        os.makedirs(LAYER_DIR_PATH)

        # Install modules
        dependencies = [dependency.strip().replace(' ', '') for dependency in layer_modules]
        command = [sys.executable, '-m', 'pip', 'install', '-t', LAYER_DIR_PATH]
        command.extend(dependencies)
        subprocess.check_call(command)

        # Compress modules
        with zipfile.ZipFile(LAYER_ZIP_PATH, 'w') as layer_zip:
            add_directory_to_zip(layer_zip, os.path.join(TEMP_PATH, 'modules'))

        # Read zip as bytes
        with open(LAYER_ZIP_PATH, 'rb') as layer_zip:
            layer_bytes = layer_zip.read()

        layer_name = self._format_layer_name(runtime_name)
        self.internal_storage.put_data(layer_name, layer_bytes)
        response = self.lambda_client.publish_layer_version(
            LayerName=layer_name,
            Description=self.package,
            Content={
                'S3Bucket': self.internal_storage.bucket,
                'S3Key': layer_name
            },
            CompatibleRuntimes=[self._python_runtime_name]
        )
        self.internal_storage.storage.delete_object(self.internal_storage.bucket, layer_name)

        if response['ResponseMetadata']['HTTPStatusCode'] == 201:
            logger.debug('OK --> Layer {} created'.format(layer_name))
            return response['LayerVersionArn']
        else:
            msg = 'An error occurred creating layer {}: {}'.format(layer_name, response)
            raise Exception(msg)


    def _delete_layer(self, layer_name):
        """
        Deletes lambda layer from its arn
        """
        logger.debug('Deleting lambda layer: {}'.format(layer_name))

        versions = []
        response = self.lambda_client.list_layer_versions(LayerName=layer_name)
        versions.extend([layer['Version'] for layer in response['LayerVersions']])

        while 'NextMarker' in response:
            response = self.lambda_client.list_layer_versions(Marker=response['NextMarker'])
            versions.extend([layer['Version'] for layer in response['LayerVersions']])

        for version in versions:
            response = self.lambda_client.delete_layer_version(
                LayerName=layer_name,
                VersionNumber=version
            )
            if response['ResponseMetadata']['HTTPStatusCode'] == 204:
                logger.debug('OK --> Layer {} version {} deleted'.format(layer_name, version))

    def _list_layers(self, runtime_name=None):
        logger.debug('Listing lambda layers: {}'.format(runtime_name))
        response = self.lambda_client.list_layers()

        layers = response['Layers'] if 'Layers' in response else []
        logger.debug('Listed {} layers'.format(len(layers)))
        lithops_layers = []
        for layer in layers:
            if 'lithops' in layer['LayerName']:
                lithops_layers.append((layer['LayerName'], layer['LatestMatchingVersion']['LayerVersionArn']))
        return lithops_layers

    def _get_runtime_modules(self, runtime_name):
        if runtime_name in lambda_config.DEFAULT_RUNTIMES:
            return lambda_config.DEFAULT_REQUIREMENTS
        else:
            user_runtimes = self.internal_storage.storage.list_keys(self.internal_storage.bucket,
                                                                    prefix=lambda_config.USER_RUNTIME_PREFIX)
            user_runtimes_keys = {runtime.split('/', 1)[1]: runtime for runtime in user_runtimes}
            if runtime_name in user_runtimes_keys:
                reqs = self.internal_storage.get_data(key=user_runtimes_keys[runtime_name]).decode('utf-8')
                return reqs.splitlines()
            else:
                raise Exception('Runtime {} does not exist. Available runtimes: {}'.format(
                    runtime_name, lambda_config.DEFAULT_RUNTIMES + user_runtimes))

    def build_runtime(self, runtime_name, requirements_file):
        if self._python_runtime_name not in lambda_config.DEFAULT_RUNTIMES:
            raise Exception('Python runtime "{}" is not available for AWS Lambda, '
                            'please use one of {}'.format(self._python_runtime_name, lambda_config.DEFAULT_RUNTIMES))

        with open(requirements_file, 'r') as req_file:
            requirements = req_file.read()

        self.internal_storage.put_data('/'.join([lambda_config.USER_RUNTIME_PREFIX, runtime_name]), requirements)

    def create_runtime(self, runtime_name, memory=3008, timeout=900):
        """
        Create a Lithops runtime as an AWS Lambda function
        """
        function_name = self._format_action_name(runtime_name, memory)
        logger.debug('Creating new Lithops lambda runtime: {}'.format(function_name))

        runtime_meta = self._generate_runtime_meta(runtime_name)

        runtime_layer_arn = self._check_runtime_layer(runtime_name)
        if runtime_layer_arn is None:
            runtime_layer_arn = self._create_layer(runtime_name)

        code = self._create_handler_bin()
        python_runtime_ver = 'python{}'.format(version_str(sys.version_info))
        response = self.lambda_client.create_function(
            FunctionName=function_name,
            Runtime=python_runtime_ver,
            Role=self.role_arn,
            Handler='__main__.lambda_handler',
            Code={
                'ZipFile': code
            },
            Description=self.package,
            Timeout=timeout,
            MemorySize=memory,
            Layers=[runtime_layer_arn, self._numerics_layer_arn]
        )

        if response['ResponseMetadata']['HTTPStatusCode'] == 201:
            logger.debug('OK --> Created action {}'.format(runtime_name))
        else:
            msg = 'An error occurred creating/updating action {}: {}'.format(runtime_name, response)
            raise Exception(msg)

        return runtime_meta

    def delete_runtime(self, runtime_name, runtime_memory, delete_runtime_storage=True):
        """
        Deletes lambda runtime from its runtime name and memory
        """
        logger.debug('Deleting lambda runtime: {}'.format(runtime_name))

        try:
            response = self.lambda_client.delete_function(
                FunctionName=runtime_name
            )
        except botocore.exceptions.ClientError as err:
            raise err

        if response['ResponseMetadata']['HTTPStatusCode'] == 204:
            logger.debug('OK --> Deleted function {}'.format(runtime_name))
        elif response['ResponseMetadata']['HTTPStatusCode'] == 404:
            logger.debug('OK --> Function {} does not exist'.format(runtime_name))
        else:
            msg = 'An error occurred creating/updating action {}: {}'.format(runtime_name, response)
            raise Exception(msg)

        if runtime_name not in lambda_config.DEFAULT_RUNTIMES:
            build_name, _ = self._unformat_action_name(runtime_name)
            self.internal_storage.storage.delete_object(self.internal_storage.bucket,
                                                        '/'.join([lambda_config.USER_RUNTIME_PREFIX, build_name]))

    def clean(self):
        """
        Deletes all Lithops Lambda runtimes
        """
        logger.debug('Deleting all runtimes')

        runtimes = self.list_runtimes()

        for runtime in runtimes:
            runtime_name, runtime_memory = runtime
            self.delete_runtime(runtime_name, runtime_memory)

        layers = self._list_layers()
        for layer_name, _ in layers:
            self._delete_layer(layer_name)

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the lambda runtimes deployed.
        return: Array of tuples (function_name, memory)
        """
        logger.debug('Listing all functions deployed...')

        functions = []
        response = self.lambda_client.list_functions(FunctionVersion='ALL')
        for function in response['Functions']:
            if 'lithops' in function['FunctionName']:
                functions.append((function['FunctionName'], function['MemorySize']))

        while 'NextMarker' in response:
            response = self.lambda_client.list_functions(Marker=response['NextMarker'])
            for function in response['Functions']:
                if 'lithops' in function['FunctionName']:
                    functions.append((function['FunctionName'], function['MemorySize']))

        logger.debug('Listed {} functions'.format(len(functions)))
        return functions

    def invoke(self, runtime_name, runtime_memory, payload, self_invoked=False):
        """
        Invoke lambda function asynchronously
        """
        exec_id = payload['executor_id']
        call_id = payload['call_id']

        function_name = self._format_action_name(runtime_name, runtime_memory)

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
        """
        Invoke lambda function and wait for result
        """
        function_name = self._format_action_name(runtime_name, runtime_memory)

        response = self.lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps(payload)
        )

        return json.loads(response['Payload'].read())

    def get_runtime_key(self, runtime_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_action_name(runtime_name, runtime_memory)
        runtime_key = '/'.join([self.name, self.region_name, self.region_name, action_name])

        return runtime_key

    def _generate_runtime_meta(self, runtime_name):
        """
        Extract preinstalled Python modules from lambda function execution environment
        return : runtime meta dictionary
        """
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
        # Create function zip archive
        action_location = os.path.join(TEMP_PATH, 'extract_preinstalls_aws.py')
        with open(action_location, 'w') as f:
            f.write(textwrap.dedent(action_code))

        modules_zip_action = os.path.join(TEMP_PATH, 'extract_preinstalls_aws.zip')
        with zipfile.ZipFile(modules_zip_action, 'w') as extract_modules_zip:
            extract_modules_zip.write(action_location, '__main__.py')

        with open(modules_zip_action, 'rb') as modules_zip:
            action_bytes = modules_zip.read()

        # Create Layer for this runtime
        runtime_layer_arn = self._check_runtime_layer(runtime_name)
        if runtime_layer_arn is None:
            runtime_layer_arn = self._create_layer(runtime_name)

        memory = 192
        modules_function_name = '_'.join([self._format_action_name(runtime_name, memory),
                                          'preinstalls', uuid.uuid4().hex[:4]])
        python_runtime_ver = 'python{}'.format(version_str(sys.version_info))

        try:
            self.lambda_client.create_function(
                FunctionName=modules_function_name,
                Runtime=python_runtime_ver,
                Role=self.role_arn,
                Handler='__main__.lambda_handler',
                Code={
                    'ZipFile': action_bytes
                },
                Description=self.package,
                Timeout=lambda_config.RUNTIME_TIMEOUT_DEFAULT,
                MemorySize=memory,
                Layers=[runtime_layer_arn, self._numerics_layer_arn]
            )
        except Exception as e:
            raise Exception('Unable to deploy "modules" action: {}'.format(e))

        logger.debug('Extracting Python modules list from: {}'.format(runtime_name))

        try:
            response = self.lambda_client.invoke(
                FunctionName=modules_function_name,
                Payload=json.dumps({})
            )
            runtime_meta = json.loads(response['Payload'].read())
        except Exception as e:
            raise Exception('Unable to invoke "modules" action: {}'.format(e))

        try:
            response = self.lambda_client.delete_function(
                FunctionName=modules_function_name
            )
        except botocore.exceptions.ClientError as e:
            logger.debug('Could not delete "modules" action: {}'.format(e))

        if 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta
