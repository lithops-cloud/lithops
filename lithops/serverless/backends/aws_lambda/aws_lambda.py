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
import time
import json
import zipfile
import sys
import subprocess
import lithops
import botocore.exceptions
import base64

from lithops.constants import TEMP as TEMP_PATH
from lithops.constants import COMPUTE_CLI_MSG
from . import config as lambda_config

logger = logging.getLogger(__name__)

LAYER_DIR_PATH = os.path.join(TEMP_PATH, 'modules', 'python')
LAYER_ZIP_PATH = os.path.join(TEMP_PATH, 'lithops_layer.zip')
FUNCTION_ZIP = 'lithops_lambda.zip'


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

    def __init__(self, aws_lambda_config, internal_storage):
        """
        Initialize AWS Lambda Backend
        """
        logger.debug('Creating AWS Lambda client')

        self.name = 'aws_lambda'
        self.type = 'faas'
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

        self.internal_storage = internal_storage

        sts_client = self.aws_session.client('sts', region_name=self.region_name)
        self.account_id = sts_client.get_caller_identity()["Account"]

        self.ecr_client = self.aws_session.client('ecr', region_name=self.region_name)

        msg = COMPUTE_CLI_MSG.format('AWS Lambda')
        logger.info("{} - Region: {}".format(msg, self.region_name))

    def _format_function_name(self, runtime_name, runtime_memory):
        if '/' in runtime_name:
            runtime_name = runtime_name.rsplit('/')[-1]
        runtime_name = self.package.replace('.', '-') + '_' + runtime_name.replace(':', '--')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _unformat_function_name(self, action_name):
        splits = action_name.split('_')
        runtime_name = '_'.join(splits[3:-1]).replace('--', ':')
        runtime_memory = int(splits[-1].replace('MB', ''))
        return runtime_name, runtime_memory

    def _format_layer_name(self, runtime_name):
        return '_'.join([self.package, runtime_name, 'layer']).replace('.', '-')

    def _create_handler_bin(self, remove=True):
        """
        Create and return Lithops handler function as zip bytes
        @param remove: True to delete the zip archive after building
        @return: Lithops handler function as zip bytes
        """
        logger.debug('Creating function handler zip in {}'.format(FUNCTION_ZIP))

        with zipfile.ZipFile(FUNCTION_ZIP, 'w') as lithops_zip:
            current_location = os.path.dirname(os.path.abspath(__file__))
            module_location = os.path.dirname(os.path.abspath(lithops.__file__))
            main_file = os.path.join(current_location, 'entry_point.py')
            lithops_zip.write(main_file,
                              '__main__.py',
                              zipfile.ZIP_DEFLATED)
            add_directory_to_zip(lithops_zip, module_location, sub_dir='lithops')

        with open(FUNCTION_ZIP, 'rb') as action_zip:
            action_bin = action_zip.read()

        if remove:
            os.remove(FUNCTION_ZIP)

        return action_bin

    def _get_layer(self, runtime_name):
        """
        Get layer ARN for a specific runtime
        @param runtime_name: runtime name from which to return its layer ARN
        @return: layer ARN for the specified runtime or None if it is not deployed
        """
        layers = self._list_layers()
        dep_layer = [layer for layer in layers if layer[0] == self._format_layer_name(runtime_name)]
        if len(dep_layer) == 1:
            _, layer_arn = dep_layer.pop()
            return layer_arn
        else:
            return None

    def _create_layer(self, runtime_name):
        """
        Create layer for the specified runtime
        @param runtime_name: runtime name from which to create the layer
        @return: ARN of the created layer
        """
        logger.debug('Creating lambda layer for runtime {}'.format(runtime_name))

        if self.internal_storage.backend != "aws_s3":
            raise Exception('"aws_s3" is required as storage backend for publising the lambda layer. '
                            'You can use "aws_s3" to create the runtime and then change the storage backend afterwards.')

        # Get list of modules that will compose the layer
        modules = lambda_config.DEFAULT_REQUIREMENTS
        if runtime_name not in lambda_config.DEFAULT_RUNTIMES:
            user_runtimes = self.internal_storage.storage.list_keys(self.internal_storage.bucket,
                                                                    prefix=lambda_config.USER_RUNTIME_PREFIX)
            user_runtimes_keys = {runtime.split('/', 1)[1]: runtime for runtime in user_runtimes}
            if runtime_name in user_runtimes_keys:
                reqs = self.internal_storage.get_data(key=user_runtimes_keys[runtime_name]).decode('utf-8')
                modules.extend(reqs.splitlines())
            else:
                raise Exception('Runtime {} does not exist. Available runtimes: {}'.format(
                    runtime_name, lambda_config.DEFAULT_RUNTIMES + list(user_runtimes_keys.values())))

        # Delete download and build target directory if it exists
        if os.path.exists(LAYER_DIR_PATH):
            if os.path.isdir(LAYER_DIR_PATH):
                shutil.rmtree(LAYER_DIR_PATH)
            elif os.path.isfile(LAYER_DIR_PATH):
                os.remove(LAYER_DIR_PATH)

        # Create target directory
        os.makedirs(LAYER_DIR_PATH)

        # Install and build modules to target directory
        logger.info('Going to download and build {} modules to {}...'.format(len(modules), LAYER_DIR_PATH))
        dependencies = [dependency.strip().replace(' ', '') for dependency in modules]
        command = [sys.executable, '-m', 'pip', 'install', '-t', LAYER_DIR_PATH]
        command.extend(dependencies)
        subprocess.check_call(command)

        # Compress modules
        with zipfile.ZipFile(LAYER_ZIP_PATH, 'w') as layer_zip:
            add_directory_to_zip(layer_zip, os.path.join(TEMP_PATH, 'modules'))

        # Read zip as bytes
        with open(LAYER_ZIP_PATH, 'rb') as layer_zip:
            layer_bytes = layer_zip.read()

        # Publish layer from S3
        layer_name = self._format_layer_name(runtime_name)
        logger.debug('Creating layer {} ...'.format(layer_name))
        self.internal_storage.put_data(layer_name, layer_bytes)
        response = self.lambda_client.publish_layer_version(
            LayerName=layer_name,
            Description=self.package,
            Content={
                'S3Bucket': self.internal_storage.bucket,
                'S3Key': layer_name
            },
            CompatibleRuntimes=[lambda_config.LAMBDA_PYTHON_VER_KEY]
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
        Delete a layer
        @param layer_name: Formatted layer name
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

    def _list_layers(self):
        """
        List all Lithops layers deployed for this user
        @return: list of Lithops layer ARNs
        """
        logger.debug('Listing lambda layers')
        response = self.lambda_client.list_layers()

        layers = response['Layers'] if 'Layers' in response else []
        logger.debug('Listed {} layers'.format(len(layers)))
        lithops_layers = []
        for layer in layers:
            if 'lithops' in layer['LayerName'] and self.user_key in layer['LayerName']:
                lithops_layers.append((layer['LayerName'], layer['LatestMatchingVersion']['LayerVersionArn']))
        return lithops_layers

    def build_runtime(self, runtime_name, runtime_file):
        """
        Build Lithops runtime for AWS lambda
        @param runtime_name: name of the runtime to be built
        @param runtime_file: path of a requirements.txt file for a layer runtime or Dockerfile for a container runtime
        """
        if runtime_file is None:
            raise Exception('Please provide a `requirements.txt` or Dockerfile')
        if lambda_config.LAMBDA_PYTHON_VER_KEY.replace('.', '') not in lambda_config.DEFAULT_RUNTIMES:
            raise Exception('Python version "{}" is not available for AWS Lambda, '
                            'please use one of {}'.format(lambda_config.LAMBDA_PYTHON_VER_KEY,
                                                          lambda_config.DEFAULT_RUNTIMES))

        logger.info('Going to create runtime {} ({}) for AWS Lambda...'.format(runtime_name, runtime_file))

        if '/' in runtime_name:
            # Container runtime
            _, image_name = runtime_name.split('/')

            self._create_handler_bin(remove=False)
            if runtime_file:
                cmd = '{} build -t {} -f {} .'.format(lambda_config.DOCKER_PATH,
                                                      image_name,
                                                      runtime_file)
            else:
                cmd = '{} build -t {} .'.format(lambda_config.DOCKER_PATH, image_name)

            subprocess.check_call(cmd.split())
            os.remove(FUNCTION_ZIP)

            ecr_repo = '{}.dkr.ecr.{}.amazonaws.com'.format(self.account_id, self.region_name)

            res = self.ecr_client.get_authorization_token()
            if res['ResponseMetadata']['HTTPStatusCode'] != 200:
                raise Exception('Could not get ECR auth token: {}'.format(res))

            auth_data = res['authorizationData'].pop()
            ecr_token = base64.b64decode(auth_data['authorizationToken']).split(b':')[1]

            cmd = '{} login --username AWS --password-stdin {}'.format(lambda_config.DOCKER_PATH, ecr_repo)
            subprocess.check_output(cmd.split(), input=ecr_token)

            if ':' in image_name:
                image_repo, tag = image_name.split(':')
            else:
                image_repo = image_name

            try:
                self.ecr_client.create_repository(repositoryName=image_repo)
            except self.ecr_client.exceptions.RepositoryAlreadyExistsException as e:
                logger.info('Repository {} already exists'.format(image_repo))

            cmd = '{} tag {} {}/{}'.format(lambda_config.DOCKER_PATH, image_name, ecr_repo, image_name)
            subprocess.check_call(cmd.split())

            cmd = '{} push {}/{}'.format(lambda_config.DOCKER_PATH, ecr_repo, image_name)
            subprocess.check_call(cmd.split())
        else:
            # requirements.txt runtime
            with open(runtime_file, 'r') as req_file:
                requirements = req_file.read()
            self.internal_storage.put_data('/'.join([lambda_config.USER_RUNTIME_PREFIX, runtime_name]), requirements)

        logger.info('Ok - Created runtime {}'.format(runtime_name))

    def create_runtime(self, runtime_name, memory=3008, timeout=900):
        """
        Create a Lambda function with Lithops handler
        @param runtime_name: name of the runtime
        @param memory: runtime memory in MB
        @param timeout: runtime timeout in seconds
        @return: runtime metadata
        """
        function_name = self._format_function_name(runtime_name, memory)
        logger.debug('Creating new Lithops lambda function: {}'.format(function_name))

        if '/' in runtime_name:
            # Container image runtime
            image_name = runtime_name.split('/')[1]

            if ':' in image_name:
                image_repo, tag = image_name.split(':')
            else:
                image_repo, tag = image_name, 'latest'

            try:
                response = self.ecr_client.describe_images(repositoryName=image_repo)
                images = response['imageDetails']
                image = list(filter(lambda image: tag in image['imageTags'], images)).pop()
                image_digest = image['imageDigest']
            except botocore.exceptions.ClientError:
                raise Exception('Runtime {} is not deployed to ECR')

            image_uri = '{}.dkr.ecr.{}.amazonaws.com/{}@{}'.format(self.account_id, self.region_name,
                                                                   image_repo, image_digest)

            response = self.lambda_client.create_function(
                FunctionName=function_name,
                Role=self.role_arn,
                Code={
                    'ImageUri': image_uri
                },
                PackageType='Image',
                Description=self.package,
                Timeout=timeout,
                MemorySize=memory,
                VpcConfig={
                    'SubnetIds': self.aws_lambda_config['vpc']['subnets'],
                    'SecurityGroupIds': self.aws_lambda_config['vpc']['security_groups']
                },
                FileSystemConfigs=[
                    {'Arn': efs_conf['access_point'],
                     'LocalMountPath': efs_conf['mount_path']}
                    for efs_conf in self.aws_lambda_config['efs']
                ]
            )
        else:
            layer_arn = self._get_layer(runtime_name)
            if not layer_arn:
                layer_arn = self._create_layer(runtime_name)

            code = self._create_handler_bin()
            response = self.lambda_client.create_function(
                FunctionName=function_name,
                Runtime=lambda_config.LAMBDA_PYTHON_VER_KEY,
                Role=self.role_arn,
                Handler='__main__.lambda_handler',
                Code={
                    'ZipFile': code
                },
                Description=self.package,
                Timeout=timeout,
                MemorySize=memory,
                Layers=[layer_arn],
                VpcConfig={
                    'SubnetIds': self.aws_lambda_config['vpc']['subnets'],
                    'SecurityGroupIds': self.aws_lambda_config['vpc']['security_groups']
                },
                FileSystemConfigs=[
                    {'Arn': efs_conf['access_point'],
                     'LocalMountPath': efs_conf['mount_path']}
                    for efs_conf in self.aws_lambda_config['efs']
                ]
            )

        if response['ResponseMetadata']['HTTPStatusCode'] in [200, 201]:
            logger.debug('OK --> Created lambda function {}'.format(runtime_name))

            retries, sleep_seconds = (15, 25) if 'vpc' in self.aws_lambda_config else (30, 5)
            while retries > 0:
                response = self.lambda_client.get_function(
                    FunctionName=function_name
                )
                state = response['Configuration']['State']
                if state == 'Pending':
                    time.sleep(sleep_seconds)
                    logger.info('Function is being deployed... '
                                 '(status: {})'.format(response['Configuration']['State']))
                    retries -= 1
                    if retries == 0:
                        raise Exception('Function not deployed: {}'.format(response))
                elif state == 'Active':
                    break

            logger.debug('Ok --> Function active')
        else:
            msg = 'An error occurred creating/updating action {}: {}'.format(runtime_name, response)
            raise Exception(msg)

        runtime_meta = self._generate_runtime_meta(runtime_name, memory)

        return runtime_meta

    def delete_runtime(self, runtime_name, runtime_memory):
        """
        Delete a Lithops lambda runtime
        @param runtime_name: name of the runtime to be deleted
        @param runtime_memory: memory of the runtime to be deleted in MB
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
            build_name, _ = self._unformat_function_name(runtime_name)
            self.internal_storage.storage.delete_object(self.internal_storage.bucket,
                                                        '/'.join([lambda_config.USER_RUNTIME_PREFIX, build_name]))

    def clean(self):
        """
        Deletes all Lithops lambda runtimes for this user
        """
        logger.debug('Deleting all runtimes')

        runtimes = self.list_runtimes()

        for runtime in runtimes:
            runtime_name, runtime_memory = runtime
            self.delete_runtime(runtime_name, runtime_memory)

        layers = self._list_layers()
        for layer_name, _ in layers:
            self._delete_layer(layer_name)

        custom_layer_runtime_keys = self.internal_storage.storage.list_keys(bucket=self.internal_storage.bucket,
                                                                            prefix=lambda_config.USER_RUNTIME_PREFIX)
        self.internal_storage.storage.delete_objects(bucket=self.internal_storage.bucket,
                                                     key_list=custom_layer_runtime_keys)

    def list_runtimes(self, runtime_name='all', unformat_name=False):
        """
        List all the Lithops lambda runtimes deployed for this user
        @param runtime_name: name of the runtime to list, 'all' to list all runtimes
        @param unformat_name: True to unformat the name
        @return: list of tuples (runtime name, memory)
        """
        logger.debug('Listing all functions deployed...')

        functions = []
        response = self.lambda_client.list_functions(FunctionVersion='ALL')
        for function in response['Functions']:
            if 'lithops' in function['FunctionName'] and self.user_key in function['FunctionName']:
                functions.append((function['FunctionName'], function['MemorySize']))

        while 'NextMarker' in response:
            response = self.lambda_client.list_functions(Marker=response['NextMarker'])
            for function in response['Functions']:
                if 'lithops' in function['FunctionName']:
                    functions.append((function['FunctionName'], function['MemorySize']))

        logger.debug('Listed {} functions'.format(len(functions)))

        if unformat_name:
            functions = [(self._unformat_function_name(func_name)[0], mem) for (func_name, mem) in functions]

        return functions

    def invoke(self, runtime_name, runtime_memory, payload):
        """
        Invoke lambda function asynchronously
        @param runtime_name: name of the runtime
        @param runtime_memory: memory of the runtime in MB
        @param payload: invoke dict payload
        @return: invocation ID
        """
        function_name = self._format_function_name(runtime_name, runtime_memory)

        response = self.lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='Event',
            Payload=json.dumps(payload)
        )

        if response['ResponseMetadata']['HTTPStatusCode'] == 202:
            return response['ResponseMetadata']['RequestId']
        else:
            logger.debug(response)
            if response['ResponseMetadata']['HTTPStatusCode'] == 401:
                raise Exception('Unauthorized - Invalid API Key')
            elif response['ResponseMetadata']['HTTPStatusCode'] == 404:
                raise Exception('Lithops Runtime: {} not deployed'.format(runtime_name))
            else:
                raise Exception(response)

    def get_runtime_key(self, runtime_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_function_name(runtime_name, runtime_memory)
        runtime_key = '/'.join([self.name, self.region_name, action_name])

        return runtime_key

    def _generate_runtime_meta(self, runtime_name, runtime_memory):
        """
        Extract preinstalled Python modules from lambda function execution environment
        return : runtime meta dictionary
        """
        logger.debug('Extracting Python modules list from: {}'.format(runtime_name))

        function_name = self._format_function_name(runtime_name, runtime_memory)

        response = self.lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({'get_preinstalls': {}})
        )

        result = json.loads(response['Payload'].read())
        if 'lithops_version' in result:
            return result
        else:
            raise Exception(result)
