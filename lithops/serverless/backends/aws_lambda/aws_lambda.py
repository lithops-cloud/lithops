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
import botocore.exceptions
import base64

from botocore.httpsession import URLLib3Session
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG

from . import config

logger = logging.getLogger(__name__)

LITHOPS_FUNCTION_ZIP = 'lithops_lambda.zip'
BUILD_LAYER_FUNCTION_ZIP = 'build_layer.zip'


class AWSLambdaBackend:
    """
    A wrap-up around AWS Boto3 API
    """

    def __init__(self, lambda_config, internal_storage):
        """
        Initialize AWS Lambda Backend
        """
        logger.debug('Creating AWS Lambda client')
        self.name = 'aws_lambda'
        self.type = 'faas'
        self.internal_storage = internal_storage
        self.user_agent = lambda_config['user_agent']
        self.region_name = lambda_config['region']

        if "config_profile" in lambda_config["aws"]:
            logger.debug("Creating boto3 client using profile %s", lambda_config["aws"]["config_profile"])
            self.aws_session = boto3.Session(
                profile_name=lambda_config["aws"]["config_profile"],
                region_name=self.region_name
            )
        else:
            self.aws_session = boto3.Session(
                aws_access_key_id=lambda_config["aws"].get('access_key_id'),
                aws_secret_access_key=lambda_config["aws"].get('secret_access_key'),
                aws_session_token=lambda_config["aws"].get('session_token'),
                region_name=self.region_name
            )

        sts_client = self.aws_session.client('sts', region_name=self.region_name)
        caller_id = sts_client.get_caller_identity()

        self.user_key = caller_id["UserId"].split(":")[1]

        self.lambda_client = self.aws_session.client(
            'lambda', region_name=self.region_name,
            config=botocore.client.Config(
                user_agent_extra=self.user_agent
            )
        )

        self.credentials = self.aws_session.get_credentials()
        self.session = URLLib3Session()
        self.host = f'lambda.{self.region_name}.amazonaws.com'
        self.package = f'lithops_v{__version__.replace(".", "-")}_{self.user_key}'

        if 'account_id' in lambda_config["aws"]:
            self.account_id = lambda_config["aws"]['account_id']
        else:
            self.account_id = caller_id["Account"]

        self.ecr_client = self.aws_session.client('ecr', region_name=self.region_name)

        # Remove "aws" section from lambda config to avoid storing secrets
        lambda_config["aws"] = {}
        self.lambda_config = lambda_config

        msg = COMPUTE_CLI_MSG.format('AWS Lambda')
        logger.info("%s - Region: %s", msg, self.region_name)

    def _format_function_name(self, runtime_name, runtime_memory, version=__version__):
        runtime_name = runtime_name.replace('/', '__').replace('.', '').replace(':', '--')
        package = self.package.replace(__version__.replace(".", "-"), version.replace(".", "-"))
        runtime_name = package + '__' + runtime_name

        return f'{runtime_name}_{runtime_memory}MB'

    @staticmethod
    def _unformat_function_name(function_name):
        version, runtime = function_name.split('__', 1)
        version = version.replace('lithops_v', '').split('_')[0].replace('-', '.')
        runtime = runtime.replace('__', '/')
        runtime = runtime.replace('--', ':')
        runtime_name, runtime_memory = runtime.rsplit('_', 1)
        return version, runtime_name, runtime_memory.replace('MB', '')

    def _format_layer_name(self, runtime_name, version=__version__):
        package = self.package.replace(__version__.replace(".", ""), version.replace(".", ""))
        return '_'.join([package, runtime_name, 'layer'])

    def _get_default_runtime_name(self):
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        return f'default-v{py_version}'

    def _is_container_runtime(self, runtime_name):
        name = runtime_name.split('/', 1)[-1]
        return 'default-v' not in name

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
        retries, sleep_seconds = (15, 25) if 'vpc' in self.lambda_config else (30, 5)

        while retries > 0:
            res = self.lambda_client.get_function(FunctionName=func_name)
            state = res['Configuration']['State']
            if state == 'Pending':
                time.sleep(sleep_seconds)
                logger.debug('"%s" function is being deployed (status: %s)', func_name, res['Configuration']['State'])
                retries -= 1
                if retries == 0:
                    raise Exception(f'"{func_name}" function not deployed (timed out): {res}')
            elif state == 'Failed' or state == 'Inactive':
                raise Exception(f'"{func_name}" function not deployed (state is "{state}"): {res}')
            elif state == 'Active':
                break

        logger.debug('Function "%s" is active', func_name)

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
        logger.info('Creating default lambda layer for runtime %s', runtime_name)

        with zipfile.ZipFile(BUILD_LAYER_FUNCTION_ZIP, 'w') as build_layer_zip:
            current_location = os.path.dirname(os.path.abspath(__file__))
            build_layer_file = os.path.join(current_location, 'build_layer.py')
            build_layer_zip.write(build_layer_file, 'build_layer.py', zipfile.ZIP_DEFLATED)

        func_name = '_'.join([self.package, 'layer_builder_512MB'])

        with open(BUILD_LAYER_FUNCTION_ZIP, 'rb') as build_layer_zip:
            build_layer_zip_bin = build_layer_zip.read()

        logger.debug('Creating "layer builder" function')

        try:
            res = self.lambda_client.create_function(
                FunctionName=func_name,
                Runtime=config.AVAILABLE_PY_RUNTIMES[utils.CURRENT_PY_VERSION],
                Role=self.lambda_config["execution_role"],
                Handler='build_layer.lambda_handler',
                Code={
                    'ZipFile': build_layer_zip_bin
                },
                Timeout=120,
                MemorySize=512
            )

            # wait until the function is created
            if res['ResponseMetadata']['HTTPStatusCode'] not in (200, 201):
                msg = f'An error occurred creating/updating action {runtime_name}: {res}'
                raise Exception(msg)

            self._wait_for_function_deployed(func_name)
            logger.debug('Created "layer builder" function %s', runtime_name)

            dependencies = [dependency.strip().replace(' ', '') for dependency in config.DEFAULT_REQUIREMENTS]
            layer_name = self._format_layer_name(runtime_name)
            payload = {
                'dependencies': dependencies,
                'bucket': self.internal_storage.bucket,
                'key': layer_name
            }

            logger.debug('Invoking "layer builder" function')
            response = self.lambda_client.invoke(FunctionName=func_name, Payload=json.dumps(payload))
            if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                logger.debug('Layer %s built', layer_name)
            else:
                msg = f'An error occurred creating layer {layer_name}: {response}'
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
        logger.debug('Creating layer %s', layer_name)
        response = self.lambda_client.publish_layer_version(
            LayerName=layer_name,
            Description='Lithops Function for ' + self.package,
            Content={
                'S3Bucket': self.internal_storage.bucket,
                'S3Key': layer_name
            },
            CompatibleRuntimes=[config.AVAILABLE_PY_RUNTIMES[utils.CURRENT_PY_VERSION]]
        )

        try:
            self.internal_storage.storage.delete_object(self.internal_storage.bucket, layer_name)
        except Exception as e:
            logger.warning(e)

        if response['ResponseMetadata']['HTTPStatusCode'] == 201:
            logger.debug('Layer %s created', layer_name)
            return response['LayerVersionArn']
        else:
            raise Exception(f'An error occurred creating layer {layer_name}: {response}')

    def _delete_layer(self, layer_name):
        """
        Delete a layer
        @param layer_name: Formatted layer name
        """
        logger.debug('Deleting lambda layer %s', layer_name)

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
                logger.debug('Layer %s version %s deleted', layer_name, version)

    def _list_layers(self):
        """
        List all Lithops layers deployed for this user
        @return: list of Lithops layer ARNs
        """
        logger.debug('Listing lambda layers')
        response = self.lambda_client.list_layers()

        layers = response['Layers'] if 'Layers' in response else []
        logger.debug('Listed %d layers', len(layers))
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
        logger.info('Deleting function "%s"', function_name)
        try:
            response = self.lambda_client.delete_function(
                FunctionName=function_name
            )
        except botocore.exceptions.ClientError as err:
            raise err

        if response['ResponseMetadata']['HTTPStatusCode'] == 204:
            logger.debug('Deleted function "%s"', function_name)
        elif response['ResponseMetadata']['HTTPStatusCode'] == 404:
            logger.debug('Function "%s" does not exist', function_name)
        else:
            msg = f'An error occurred creating/updating action {function_name}: {response}'
            raise Exception(msg)

    def build_runtime(self, runtime_name, runtime_file, extra_args=[]):
        """
        Build Lithops container runtime for AWS lambda
        @param runtime_name: name of the runtime to be built
        @param runtime_file: path of a Dockerfile for a container runtime
        """
        logger.info('Building runtime %s from %s', runtime_name, runtime_file)

        docker_path = utils.get_docker_path()
        if runtime_file:
            assert os.path.isfile(runtime_file), f'Cannot locate "{runtime_file}"'
            cmd = f'{docker_path} build -t {runtime_name} -f {runtime_file} . '
        else:
            cmd = f'{docker_path} build -t {runtime_name} . '
        cmd = cmd + ' '.join(extra_args)

        try:
            self._create_handler_bin(remove=False)
            utils.run_command(cmd)
        finally:
            os.remove(LITHOPS_FUNCTION_ZIP)

        registry = f'{self.account_id}.dkr.ecr.{self.region_name}.amazonaws.com'

        res = self.ecr_client.get_authorization_token()
        if res['ResponseMetadata']['HTTPStatusCode'] != 200:
            raise Exception(f'Could not get ECR auth token: {res}')

        auth_data = res['authorizationData'].pop()
        ecr_token = base64.b64decode(auth_data['authorizationToken']).split(b':')[1]

        cmd = f'{docker_path} login --username AWS --password-stdin {registry}'
        subprocess.check_output(cmd.split(), input=ecr_token)

        repo_name = self._format_repo_name(runtime_name)

        tag = 'latest' if ':' not in runtime_name else runtime_name.split(':')[1]

        try:
            self.ecr_client.create_repository(repositoryName=repo_name)
        except self.ecr_client.exceptions.RepositoryAlreadyExistsException:
            logger.debug('Repository "%s" already exists', repo_name)

        image_name = f'{registry}/{repo_name}:{tag}'
        logger.debug('Pushing runtime "%s" to AWS container registry', image_name)
        cmd = f'{docker_path} tag {runtime_name} {image_name}'
        utils.run_command(cmd)
        if utils.is_podman(docker_path):
            cmd = f'{docker_path} push {image_name} --format docker --remove-signatures'
        else:
            cmd = f'{docker_path} push {image_name}'
        utils.run_command(cmd)

        logger.debug('Building done!')

    def _deploy_default_runtime(self, runtime_name, memory, timeout):
        """
        Deploy the default runtime based on layers
        """
        logger.info("Deploying runtime: %s - Memory: %d - Timeout: %d", runtime_name, memory, timeout)
        function_name = self._format_function_name(runtime_name, memory)

        layer_arn = self._get_layer(runtime_name)
        if not layer_arn:
            layer_arn = self._create_layer(runtime_name)

        code = self._create_handler_bin()
        env_vars = {t['name']: t['value'] for t in self.lambda_config['env_vars']}

        try:
            response = self.lambda_client.create_function(
                FunctionName=function_name,
                Runtime=config.AVAILABLE_PY_RUNTIMES[utils.CURRENT_PY_VERSION],
                Role=self.lambda_config["execution_role"],
                Handler='entry_point.lambda_handler',
                Code={
                    'ZipFile': code
                },
                Description='Lithops Worker for ' + self.package,
                Timeout=timeout,
                MemorySize=memory,
                Layers=[layer_arn],
                VpcConfig={
                    'SubnetIds': self.lambda_config['vpc']['subnets'],
                    'SecurityGroupIds': self.lambda_config['vpc']['security_groups']
                },
                FileSystemConfigs=[
                    {'Arn': efs_conf['access_point'],
                     'LocalMountPath': efs_conf['mount_path']}
                    for efs_conf in self.lambda_config['efs']
                ],
                Tags={
                    'runtime_name': runtime_name,
                    'lithops_version': __version__
                },
                EphemeralStorage={
                    'Size': self.lambda_config['ephemeral_storage']
                },
                Environment={
                    'Variables': env_vars
                }
            )

            if response['ResponseMetadata']['HTTPStatusCode'] not in (200, 201):
                raise Exception(f'An error occurred creating/updating action {runtime_name}: {response}')

        except Exception as e:
            if 'ResourceConflictException' in str(e):
                pass
            else:
                raise e

        self._wait_for_function_deployed(function_name)
        logger.debug('Created lambda function "%s"', function_name)

    def _deploy_container_runtime(self, runtime_name, memory, timeout):
        """
        Deploy a runtime based on a container
        """
        logger.info("Deploying runtime: %s - Memory: %d Timeout: %d", runtime_name, memory, timeout)
        function_name = self._format_function_name(runtime_name, memory)

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
            raise Exception(f'Runtime "{runtime_name}" is not deployed to ECR')

        registry = f'{self.account_id}.dkr.ecr.{self.region_name}.amazonaws.com'
        image_uri = f'{registry}/{repo_name}@{image_digest}'

        env_vars = {t['name']: t['value'] for t in self.lambda_config['env_vars']}

        try:
            response = self.lambda_client.create_function(
                FunctionName=function_name,
                Role=self.lambda_config["execution_role"],
                Code={
                    'ImageUri': image_uri
                },
                PackageType='Image',
                Description='Lithops Worker for ' + self.package,
                Timeout=timeout,
                MemorySize=memory,
                VpcConfig={
                    'SubnetIds': self.lambda_config['vpc']['subnets'],
                    'SecurityGroupIds': self.lambda_config['vpc']['security_groups']
                },
                FileSystemConfigs=[
                    {'Arn': efs_conf['access_point'],
                     'LocalMountPath': efs_conf['mount_path']}
                    for efs_conf in self.lambda_config['efs']
                ],
                Tags={
                    'runtime_name': self.package + '/' + runtime_name,
                    'lithops_version': __version__
                },
                Architectures=[self.lambda_config['architecture']],
                EphemeralStorage={
                    'Size': self.lambda_config['ephemeral_storage']
                },
                Environment={
                    'Variables': env_vars
                }
            )

            if response['ResponseMetadata']['HTTPStatusCode'] not in (200, 201):
                raise Exception(f'An error occurred creating/updating action {runtime_name}: {response}')

        except Exception as e:
            if 'ResourceConflictException' in str(e):
                pass
            else:
                raise e

        self._wait_for_function_deployed(function_name)
        logger.debug('Created lambda function "%s"', function_name)

    def deploy_runtime(self, runtime_name, memory, timeout):
        """
        Deploys a Lambda function with the Lithops handler
        @param runtime_name: name of the runtime
        @param memory: runtime memory in MB
        @param timeout: runtime timeout in seconds
        @return: runtime metadata
        """
        if runtime_name == self._get_default_runtime_name():
            self._deploy_default_runtime(runtime_name, memory, timeout)
        else:
            self._deploy_container_runtime(runtime_name, memory, timeout)

        runtime_meta = self._generate_runtime_meta(runtime_name, memory)

        return runtime_meta

    def delete_runtime(self, runtime_name, runtime_memory, version=__version__):
        """
        Delete a Lithops lambda runtime
        @param runtime_name: name of the runtime to be deleted
        @param runtime_memory: memory of the runtime to be deleted in MB
        """
        logger.info('Deleting lambda runtime: %s - %d MB',runtime_name, runtime_memory)
        func_name = self._format_function_name(runtime_name, runtime_memory, version)

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
                logger.debug('Going to delete ECR repository "%s" with tag "%s"', repo_name, tag)
                try:
                    self.ecr_client.batch_delete_image(repositoryName=repo_name, imageIds=[{'imageTag': tag}])
                    images = self.ecr_client.list_images(repositoryName=repo_name, filter={'tagStatus': 'TAGGED'})
                    if not images['imageIds']:
                        logger.debug('Going to delete ECR repository %s', repo_name)
                        self.ecr_client.delete_repository(repositoryName=repo_name, force=True)
                except:
                    pass
            else:
                layer = self._format_layer_name(runtime_name, version)
                self._delete_layer(layer)

    def clean(self, **kwargs):
        """
        Deletes all Lithops lambda runtimes for this user
        """
        logger.debug('Deleting all runtimes')

        def delete_runtimes(response):
            for function in response['Functions']:
                if function['FunctionName'].startswith('lithops_v') and self.user_key in function['FunctionName']:
                    self._delete_function(function['FunctionName'])

        response = self.lambda_client.list_functions(FunctionVersion='ALL')
        delete_runtimes(response)
        while 'NextMarker' in response:
            response = self.lambda_client.list_functions(Marker=response['NextMarker'])
            delete_runtimes(response)

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

        def get_runtimes(response):
            for function in response['Functions']:
                if function['FunctionName'].startswith('lithops_v') and self.user_key in function['FunctionName']:
                    version, rt_name, rt_memory = self._unformat_function_name(function['FunctionName'])
                    runtimes.append((rt_name, rt_memory, version))

        response = self.lambda_client.list_functions(FunctionVersion='ALL')
        get_runtimes(response)
        while 'NextMarker' in response:
            response = self.lambda_client.list_functions(Marker=response['NextMarker'])
            get_runtimes(response)

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
            except:
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

    def get_runtime_key(self, runtime_name, runtime_memory, version=__version__):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_function_name(runtime_name, runtime_memory, version)
        runtime_key = os.path.join(self.name, version, self.region_name, action_name)

        return runtime_key

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if 'runtime' not in self.lambda_config or self.lambda_config['runtime'] == 'default':
            if utils.CURRENT_PY_VERSION not in config.AVAILABLE_PY_RUNTIMES:
                raise Exception(
                    f'Python {utils.CURRENT_PY_VERSION} is not available '
                    f'for AWS Lambda, please use one of {list(config.AVAILABLE_PY_RUNTIMES.keys())},'
                    ' or use a container runtime.'
                )
            self.lambda_config['runtime'] = self._get_default_runtime_name()

        runtime_info = {
            'runtime_name': self.lambda_config['runtime'],
            'runtime_memory': self.lambda_config['runtime_memory'],
            'runtime_timeout': self.lambda_config['runtime_timeout'],
            'max_workers': self.lambda_config['max_workers'],
        }

        return runtime_info

    def _generate_runtime_meta(self, runtime_name, runtime_memory):
        """
        Extract preinstalled Python modules from lambda function execution environment
        return : runtime meta dictionary
        """
        logger.debug('Extracting runtime metadata from runtime "%s"', runtime_name)

        function_name = self._format_function_name(runtime_name, runtime_memory)

        response = self.lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({'get_metadata': {}})
        )

        result = json.loads(response['Payload'].read())

        if 'lithops_version' in result:
            return result
        else:
            raise Exception('An error occurred: {}'.format(result))
