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
import requests

from botocore.httpsession import URLLib3Session
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth

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
        self.internal_storage = internal_storage
        self.user_agent = aws_lambda_config['user_agent']

        self.user_key = aws_lambda_config['access_key_id'][-4:]
        self.package = 'lithops_v{}_{}'.format(lithops.__version__, self.user_key)
        self.region_name = aws_lambda_config['region_name']
        self.role_arn = aws_lambda_config['execution_role']

        logger.debug('Creating Boto3 AWS Session and Lambda Client')

        self.aws_session = boto3.Session(
            aws_access_key_id=aws_lambda_config['access_key_id'],
            aws_secret_access_key=aws_lambda_config['secret_access_key'],
            region_name=self.region_name
        )

        self.lambda_client = self.aws_session.client(
            'lambda', region_name=self.region_name,
            config=botocore.client.Config(
                       user_agent_extra=self.user_agent
                   )
        )

        self.credentials = self.aws_session.get_credentials()
        self.session = URLLib3Session()
        self.host = f'lambda.{self.region_name}.amazonaws.com'

        if self.aws_lambda_config['account_id']:
            self.account_id = self.aws_lambda_config['account_id']
        else:
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

    @staticmethod
    def _unformat_function_name(action_name):
        splits = action_name.split('_')
        runtime_name = '_'.join(splits[3:-1]).replace('--', ':')
        runtime_memory = int(splits[-1].replace('MB', ''))
        return runtime_name, runtime_memory

    def _format_layer_name(self, runtime_name):
        return '_'.join([self.package, runtime_name, 'layer']).replace('.', '-')

    @staticmethod
    def _is_container_runtime(runtime_name):
        return runtime_name not in lambda_config.AVAILABLE_RUNTIMES

    def _format_repo_name(self, runtime_name):
        if ':' in runtime_name:
            base_image = runtime_name.split(':')[0]
        else:
            base_image = runtime_name
        return '/'.join([self.package, base_image]).replace('.', '-').lower()

    @staticmethod
    def _create_handler_bin(remove=True):
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

    @staticmethod
    def _get_numpy_layer_arn(region_name):
        """
        Gets last pre-built numpy layer ARN using Klayers API (https://github.com/keithrozario/Klayers) based on region
        @return: Numpy Klayer ARN
        """
        res = requests.get('https://api.klayers.cloud/api/v1/layers/latest/{}/numpy'.format(region_name))
        res_json = res.json()
        logger.debug(res_json)
        if not res_json or 'arn' not in res_json:
            raise Exception('Could not get numpy layer ARN from Klayers - Response: {}'.format(res_json))
        return res_json['arn']

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
        logger.info('Creating default lambda layer for runtime {}'.format(runtime_name))

        if self.internal_storage.backend != "aws_s3":
            raise Exception('"aws_s3" is required as storage backend for publishing the lambda layer. '
                            'You can use "aws_s3" to create the runtime and then change the storage backend afterwards.')

        # Delete download and build target directory if it exists
        if os.path.exists(LAYER_DIR_PATH):
            if os.path.isdir(LAYER_DIR_PATH):
                shutil.rmtree(LAYER_DIR_PATH)
            elif os.path.isfile(LAYER_DIR_PATH):
                os.remove(LAYER_DIR_PATH)

        # Create target directory
        os.makedirs(LAYER_DIR_PATH)

        # Install and build modules to target directory
        dependencies = [dependency.strip().replace(' ', '') for dependency in lambda_config.DEFAULT_REQUIREMENTS]
        logger.debug('Going to download and build {} modules to {}'.format(len(dependencies), LAYER_DIR_PATH))
        command = [sys.executable, '-m', 'pip', 'install', '-t', LAYER_DIR_PATH]
        command.extend(dependencies)

        if logger.getEffectiveLevel() != logging.DEBUG:
            subprocess.check_call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
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

    def _delete_function(self, function_name):
        """
        Deletes a function by its formatted name
        @param function_name: function name to delete
        """
        try:
            response = self.lambda_client.delete_function(
                FunctionName=function_name
            )
        except botocore.exceptions.ClientError as err:
            raise err

        if response['ResponseMetadata']['HTTPStatusCode'] == 204:
            logger.debug('OK --> Deleted function {}'.format(function_name))
        elif response['ResponseMetadata']['HTTPStatusCode'] == 404:
            logger.debug('OK --> Function {} does not exist'.format(function_name))
        else:
            msg = 'An error occurred creating/updating action {}: {}'.format(function_name, response)
            raise Exception(msg)

    def build_runtime(self, runtime_name, runtime_file):
        """
        Build Lithops container runtime for AWS lambda
        @param runtime_name: name of the runtime to be built
        @param runtime_file: path of a Dockerfile for a container runtime
        """
        assert os.path.isfile(runtime_file), 'Dockerfile provided is not a file'.format(runtime_file)

        logger.info('Going to create runtime {} ({}) for AWS Lambda...'.format(runtime_name, runtime_file))

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

        registry = '{}.dkr.ecr.{}.amazonaws.com'.format(self.account_id, self.region_name)

        res = self.ecr_client.get_authorization_token()
        if res['ResponseMetadata']['HTTPStatusCode'] != 200:
            raise Exception('Could not get ECR auth token: {}'.format(res))

        auth_data = res['authorizationData'].pop()
        ecr_token = base64.b64decode(auth_data['authorizationToken']).split(b':')[1]

        cmd = '{} login --username AWS --password-stdin {}'.format(lambda_config.DOCKER_PATH, registry)
        subprocess.check_output(cmd.split(), input=ecr_token)

        repo_name = self._format_repo_name(image_name)

        tag = 'latest' if ':' not in image_name else image_name.split(':')[1]

        try:
            self.ecr_client.create_repository(repositoryName=repo_name)
        except self.ecr_client.exceptions.RepositoryAlreadyExistsException as e:
            logger.info('Repository {} already exists'.format(repo_name))

        cmd = '{} tag {} {}/{}:{}'.format(lambda_config.DOCKER_PATH, image_name, registry, repo_name, tag)
        subprocess.check_call(cmd.split())

        cmd = '{} push {}/{}:{}'.format(lambda_config.DOCKER_PATH, registry, repo_name, tag)
        subprocess.check_call(cmd.split())

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
                image, tag = image_name.split(':')
            else:
                image, tag = image_name, 'latest'

            try:
                repo_name = self._format_repo_name(image)
                response = self.ecr_client.describe_images(repositoryName=repo_name)
                images = response['imageDetails']
                image = list(filter(lambda image: tag in image['imageTags'], images)).pop()
                image_digest = image['imageDigest']
            except botocore.exceptions.ClientError:
                raise Exception('Runtime {} is not deployed to ECR'.format(runtime_name))

            image_uri = '{}.dkr.ecr.{}.amazonaws.com/{}@{}'.format(self.account_id, self.region_name,
                                                                   repo_name, image_digest)

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
            assert runtime_name in lambda_config.AVAILABLE_RUNTIMES, \
                'Runtime {} is not available, try one of {}'.format(runtime_name, lambda_config.AVAILABLE_RUNTIMES)

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

        func_name = self._format_function_name(runtime_name, runtime_memory)
        self._delete_function(func_name)

        # Check if layer/container image has to also be deleted
        if not self.list_runtimes(runtime_name):
            if self._is_container_runtime(runtime_name):
                repo_name = self._format_repo_name(runtime_name)
                logger.debug('Going to delete ECR repository {}'.format(repo_name))
                self.ecr_client.delete_repository(repositoryName=repo_name, force=True)
            else:
                layer = self._format_layer_name(runtime_name)
                self._delete_layer(layer)

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

    def list_runtimes(self, runtime_name=None):
        """
        List all the Lithops lambda runtimes deployed for this user
        @param runtime_name: name of the runtime to list, 'all' to list all runtimes
        @return: list of tuples (runtime name, memory)
        """
        logger.debug('Listing all functions deployed...')

        runtimes = []
        response = self.lambda_client.list_functions(FunctionVersion='ALL')
        key = self._format_function_name('', '')[:-4]
        for function in response['Functions']:
            if key in function['FunctionName']:
                rt_name, rt_memory = self._unformat_function_name(function['FunctionName'])
                runtimes.append((rt_name, rt_memory))

        while 'NextMarker' in response:
            response = self.lambda_client.list_functions(Marker=response['NextMarker'])
            for function in response['Functions']:
                if key in function['FunctionName']:
                    rt_name, rt_memory = self._unformat_function_name(function['FunctionName'])
                    runtimes.append((rt_name, rt_memory))

        if runtime_name:
            if self._is_container_runtime(runtime_name) and ':' not in runtime_name:
                runtime_name = runtime_name + ':latest'
            runtimes = [tup for tup in runtimes if tup[0] in runtime_name]

        logger.debug('Listed {} functions'.format(len(runtimes)))
        return runtimes

    def invoke(self, runtime_name, runtime_memory, payload):
        """
        Invoke lambda function asynchronously
        @param runtime_name: name of the runtime
        @param runtime_memory: memory of the runtime in MB
        @param payload: invoke dict payload
        @return: invocation ID
        """

        function_name = self._format_function_name(runtime_name, runtime_memory)

        headers = {'Host': self.host, 'X-Amz-Invocation-Type': 'Event', 'User-Agent': self.user_agent}
        url = f'https://{self.host}/2015-03-31/functions/{function_name}/invocations'
        request = AWSRequest(method="POST", url=url, data=json.dumps(payload, default=str), headers=headers)
        SigV4Auth(self.credentials, "lambda", self.region_name).add_auth(request)

        invoked = False
        while not invoked:
            try:
                r = self.session.send(request.prepare())
                invoked = True
            except Exception:
                pass

        if r.status_code == 202:
            return r.headers['x-amzn-RequestId']
        elif r.status_code == 401:
            logger.debug(r.text)
            raise Exception('Unauthorized - Invalid API Key')
        elif r.status_code == 404:
            logger.debug(r.text)
            raise Exception('Lithops Runtime: {} not deployed'.format(runtime_name))
        else:
            logger.debug(r.text)
            raise Exception('Error {}: {}'.format(r.status_code, r.text))

        # response = self.lambda_client.invoke(
        #    FunctionName=function_name,
        #     InvocationType='Event',
        #     Payload=json.dumps(payload, default=str)
        #  )

        # if response['ResponseMetadata']['HTTPStatusCode'] == 202:
        #     return response['ResponseMetadata']['RequestId']
        # else:
        #     logger.debug(response)
        #     if response['ResponseMetadata']['HTTPStatusCode'] == 401:
        #         raise Exception('Unauthorized - Invalid API Key')
        #     elif response['ResponseMetadata']['HTTPStatusCode'] == 404:
        #         raise Exception('Lithops Runtime: {} not deployed'.format(runtime_name))
        #     else:
        #         raise Exception(response)

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
            logger.error('An error occurred: {}, cleaning up...'.format(result))
            self.delete_runtime(runtime_name, runtime_memory)
            layer_name = self._format_layer_name(runtime_name)
            self._delete_layer(layer_name)
            raise Exception(result)
