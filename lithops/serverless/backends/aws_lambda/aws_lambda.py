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
import logging
import boto3
import time
import json
import zipfile
import subprocess
import lithops
import botocore.exceptions
import base64

from botocore.httpsession import URLLib3Session
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth

from lithops.constants import COMPUTE_CLI_MSG
from . import config as lambda_config
from lithops import utils

logger = logging.getLogger(__name__)

LITHOPS_FUNCTION_ZIP = 'lithops_lambda.zip'
BUILD_LAYER_FUNCTION_ZIP = 'build_layer.zip'


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
        self.package = 'lithops_v{}_{}'.format(lithops.__version__, self.user_key.lower()).replace('.', '-')
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
        runtime_name = runtime_name.replace('/', '__')
        runtime_name = runtime_name.replace('.', '')
        runtime_name = runtime_name.replace(':', '--')

        if not runtime_name.startswith('lithops_v'):
            runtime_name = self.package + '__' + runtime_name

        return '{}_{}MB'.format(runtime_name, runtime_memory)

    @staticmethod
    def _unformat_function_name(function_name):
        action_name = function_name.replace('__', '/')
        action_name = action_name.replace('--', ':')
        runtime_name, runtime_memory = action_name.rsplit('_', 1)
        return runtime_name, runtime_memory.replace('MB', '')

    def _format_layer_name(self, runtime_name):
        return '_'.join([self.package, runtime_name, 'layer'])

    @staticmethod
    def _is_container_runtime(runtime_name):
        name = runtime_name.split('/', 1)[-1]
        return name not in lambda_config.AVAILABLE_RUNTIMES

    def _format_repo_name(self, runtime_name):
        if ':' in runtime_name:
            base_image = runtime_name.split(':')[0]
        else:
            base_image = runtime_name
        return '/'.join([self.package, base_image]).lower()

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

    def _wait_for_function_deployed(self, func_name):
        """
        Helper function which waits for the lambda to be deployed (state is 'Active').
        Raises exception if waiting times out or if state is 'Failed' or 'Inactive'
        """
        retries, sleep_seconds = (15, 25) if 'vpc' in self.aws_lambda_config else (30, 5)

        while retries > 0:
            res = self.lambda_client.get_function(FunctionName=func_name)
            state = res['Configuration']['State']
            if state == 'Pending':
                time.sleep(sleep_seconds)
                logger.info('"{}" function is being deployed... '
                            '(status: {})'.format(func_name, res['Configuration']['State']))
                retries -= 1
                if retries == 0:
                    raise Exception('"{}" function not deployed (timed out): {}'.format(func_name, res))
            elif state == 'Failed' or state == 'Inactive':
                raise Exception('"{}" function not deployed (state is "{}"): {}'.format(func_name, state, res))
            elif state == 'Active':
                break

        logger.debug('Ok --> function "{}" is active'.format(func_name))

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

        with zipfile.ZipFile(BUILD_LAYER_FUNCTION_ZIP, 'w') as build_layer_zip:
            current_location = os.path.dirname(os.path.abspath(__file__))
            build_layer_file = os.path.join(current_location, 'build_layer.py')
            build_layer_zip.write(build_layer_file, 'build_layer.py', zipfile.ZIP_DEFLATED)

        func_name = '_'.join([self.package, 'layer_builder_512MB'])

        with open(BUILD_LAYER_FUNCTION_ZIP, 'rb') as build_layer_zip:
            build_layer_zip_bin = build_layer_zip.read()

        logger.debug('Creating "layer builder" function')

        try:
            resp = self.lambda_client.create_function(
                FunctionName=func_name,
                Runtime=lambda_config.LAMBDA_PYTHON_VER_KEY,
                Role=self.role_arn,
                Handler='build_layer.lambda_handler',
                Code={
                    'ZipFile': build_layer_zip_bin
                },
                Timeout=120,
                MemorySize=512
            )

            # wait until the function is created
            if resp['ResponseMetadata']['HTTPStatusCode'] not in (200, 201):
                msg = 'An error occurred creating/updating action {}: {}'.format(runtime_name, resp)
                raise Exception(msg)

            self._wait_for_function_deployed(func_name)
            logger.debug('OK --> Created "layer builder" function {}'.format(runtime_name))

            dependencies = [dependency.strip().replace(' ', '') for dependency in lambda_config.DEFAULT_REQUIREMENTS]
            layer_name = self._format_layer_name(runtime_name)
            payload = {
                'dependencies': dependencies,
                'bucket': self.internal_storage.bucket,
                'key': layer_name
            }

            logger.debug('Invoking "layer builder" function')
            response = self.lambda_client.invoke(FunctionName=func_name, Payload=json.dumps(payload))
            if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                logger.debug('OK --> Layer {} built'.format(layer_name))
            else:
                msg = 'An error occurred creating layer {}: {}'.format(layer_name, response)
                raise Exception(msg)
        finally:
            os.remove(BUILD_LAYER_FUNCTION_ZIP)
            logger.debug('Trying to delete "layer builder" function')
            try:
                self.lambda_client.delete_function(FunctionName=func_name)
            except botocore.exceptions.ClientError as err:
                if err.response['Error']['Code'] != 'ResourceNotFoundException':
                    raise

        # Publish layer from S3
        logger.debug('Creating layer {} ...'.format(layer_name))
        response = self.lambda_client.publish_layer_version(
            LayerName=layer_name,
            Description='Lithops Function for '+self.package,
            Content={
                'S3Bucket': self.internal_storage.bucket,
                'S3Key': layer_name
            },
            CompatibleRuntimes=[lambda_config.LAMBDA_PYTHON_VER_KEY]
        )

        try:
            self.internal_storage.storage.delete_object(self.internal_storage.bucket, layer_name)
        except Exception as e:
            logger.warning(e)

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

    def build_runtime(self, runtime_name, runtime_file, extra_args=[]):
        """
        Build Lithops container runtime for AWS lambda
        @param runtime_name: name of the runtime to be built
        @param runtime_file: path of a Dockerfile for a container runtime
        """
        logger.info(f'Going to create runtime {runtime_name} for AWS Lambda')

        if runtime_file:
            assert os.path.isfile(runtime_file), f'Cannot locate "{runtime_file}"'
            cmd = '{} build -t {} -f {} . '.format(lambda_config.DOCKER_PATH,
                                                   runtime_name,
                                                   runtime_file)
        else:
            cmd = '{} build -t {} . '.format(lambda_config.DOCKER_PATH, runtime_name)

        cmd = cmd+' '.join(extra_args)

        self._create_handler_bin(remove=False)

        subprocess.check_call(cmd.split())
        os.remove(LITHOPS_FUNCTION_ZIP)

        registry = '{}.dkr.ecr.{}.amazonaws.com'.format(self.account_id, self.region_name)

        res = self.ecr_client.get_authorization_token()
        if res['ResponseMetadata']['HTTPStatusCode'] != 200:
            raise Exception('Could not get ECR auth token: {}'.format(res))

        auth_data = res['authorizationData'].pop()
        ecr_token = base64.b64decode(auth_data['authorizationToken']).split(b':')[1]

        cmd = '{} login --username AWS --password-stdin {}'.format(lambda_config.DOCKER_PATH, registry)
        subprocess.check_output(cmd.split(), input=ecr_token)

        repo_name = self._format_repo_name(runtime_name)

        tag = 'latest' if ':' not in runtime_name else runtime_name.split(':')[1]

        try:
            self.ecr_client.create_repository(repositoryName=repo_name)
        except self.ecr_client.exceptions.RepositoryAlreadyExistsException:
            logger.info('Repository {} already exists'.format(repo_name))

        cmd = '{} tag {} {}/{}:{}'.format(lambda_config.DOCKER_PATH, runtime_name, registry, repo_name, tag)
        subprocess.check_call(cmd.split())

        cmd = '{} push {}/{}:{}'.format(lambda_config.DOCKER_PATH, registry, repo_name, tag)
        subprocess.check_call(cmd.split())

        logger.info('Ok - Created runtime {}'.format(runtime_name))

    def deploy_runtime(self, runtime_name, memory=3008, timeout=900):
        """
        Deploys a Lambda function with the Lithops handler
        @param runtime_name: name of the runtime
        @param memory: runtime memory in MB
        @param timeout: runtime timeout in seconds
        @return: runtime metadata
        """
        function_name = self._format_function_name(runtime_name, memory)
        logger.debug(f"Deploying runtime: {runtime_name} - Memory: {memory} Timeout: {timeout}")

        if self._is_container_runtime(runtime_name):
            # Container image runtime
            if ':' in runtime_name:
                image, tag = runtime_name.split(':')
            else:
                image, tag = runtime_name, 'latest'

            try:
                repo_name = self._format_repo_name(image)
                response = self.ecr_client.describe_images(repositoryName=repo_name)
                images = response['imageDetails']
                if not images:
                    raise Exception(f'Runtime {runtime_name} is not present in ECR.'
                                    'Consider running "lithops runtime build -b aws_lambda ..."')
                image = list(filter(lambda image: 'imageTags' in image and tag in image['imageTags'], images)).pop()
                image_digest = image['imageDigest']
            except botocore.exceptions.ClientError:
                raise Exception('Runtime {} is not deployed to ECR'.format(runtime_name))

            image_uri = '{}.dkr.ecr.{}.amazonaws.com/{}@{}'.format(self.account_id, self.region_name,
                                                                   repo_name, image_digest)

            try:
                response = self.lambda_client.create_function(
                    FunctionName=function_name,
                    Role=self.role_arn,
                    Code={
                        'ImageUri': image_uri
                    },
                    PackageType='Image',
                    Description='Lithops Worker for '+self.package,
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
                    ],
                    Tags={
                        'runtime_name': self.package+'/'+runtime_name
                    },
                    Architectures=[self.aws_lambda_config['architecture']]
                )
            except Exception as e:
                if 'ResourceConflictException' in str(e):
                    pass
                else:
                    raise e
        else:
            assert runtime_name in lambda_config.AVAILABLE_RUNTIMES, \
                'Runtime {} is not available, try one of {}'.format(runtime_name, lambda_config.AVAILABLE_RUNTIMES)

            layer_arn = self._get_layer(runtime_name)
            if not layer_arn:
                layer_arn = self._create_layer(runtime_name)

            code = self._create_handler_bin()

            try:
                response = self.lambda_client.create_function(
                    FunctionName=function_name,
                    Runtime=lambda_config.LAMBDA_PYTHON_VER_KEY,
                    Role=self.role_arn,
                    Handler='entry_point.lambda_handler',
                    Code={
                        'ZipFile': code
                    },
                    Description='Lithops Worker for '+self.package,
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
                    ],
                    Tags={
                        'runtime_name': runtime_name
                    },
                )
            except Exception as e:
                if 'ResourceConflictException' in str(e):
                    pass
                else:
                    raise e

        if response['ResponseMetadata']['HTTPStatusCode'] not in (200, 201):
            msg = 'An error occurred creating/updating action {}: {}'.format(runtime_name, response)
            raise Exception(msg)

        self._wait_for_function_deployed(function_name)
        logger.debug('OK --> Created lambda function {}'.format(function_name))

        runtime_meta = self._generate_runtime_meta(runtime_name, memory)

        return runtime_meta

    def delete_runtime(self, runtime_name, runtime_memory):
        """
        Delete a Lithops lambda runtime
        @param runtime_name: name of the runtime to be deleted
        @param runtime_memory: memory of the runtime to be deleted in MB
        """
        logger.info(f'Deleting lambda runtime: {runtime_name} - {runtime_memory}MB')
        func_name = self._format_function_name(runtime_name, runtime_memory)

        self._delete_function(func_name)

        # Check if layer/container image has to also be deleted
        if not self.list_runtimes(runtime_name):
            runtime_name = runtime_name.split('/', 1)[1] if '/' in runtime_name else runtime_name
            if self._is_container_runtime(runtime_name):
                if ':' in runtime_name:
                    image, tag = runtime_name.split(':')
                else:
                    image, tag = runtime_name, 'latest'
                package = '_'.join(func_name.split('_')[:3])
                repo_name = f"{package}/{image}"
                logger.info(f'Going to delete ECR repository {repo_name} tag {tag}')
                self.ecr_client.batch_delete_image(repositoryName=repo_name, imageIds=[{'imageTag': tag}])
                images = self.ecr_client.list_images(repositoryName=repo_name, filter={'tagStatus': 'TAGGED'})
                if not images['imageIds']:
                    logger.debug(f'Going to delete ECR repository {repo_name}')
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

    def list_runtimes(self, runtime_name='all'):
        """
        List all the Lithops lambda runtimes deployed for this user
        @param runtime_name: name of the runtime to list, 'all' to list all runtimes
        @return: list of tuples (runtime name, memory)
        """
        runtimes = []
        response = self.lambda_client.list_functions(FunctionVersion='ALL')
        for function in response['Functions']:
            if self.package in function['FunctionName']:
                rt_name, rt_memory = self._unformat_function_name(function['FunctionName'])
                runtimes.append((rt_name, rt_memory))

        while 'NextMarker' in response:
            response = self.lambda_client.list_functions(Marker=response['NextMarker'])
            for function in response['Functions']:
                if self.package in function['FunctionName']:
                    rt_name, rt_memory = self._unformat_function_name(function['FunctionName'])
                    runtimes.append((rt_name, rt_memory))

        if runtime_name != 'all':
            if self._is_container_runtime(runtime_name) and ':' not in runtime_name:
                runtime_name = runtime_name + ':latest'
            runtimes = [tup for tup in runtimes if runtime_name in tup[0]]

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
            raise Exception('An error occurred: {}'.format(result))
