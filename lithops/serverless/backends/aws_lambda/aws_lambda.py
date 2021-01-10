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

from lithops.storage import InternalStorage
from lithops.utils import version_str
from lithops.constants import TEMP as TEMP_PATH
from lithops.constants import COMPUTE_CLI_MSG
from . import config as lambda_config

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

        sts_client = self.aws_session.client('sts', region_name=self.region_name)
        self.account_id = sts_client.get_caller_identity()["Account"]

        self.ecr_client = self.aws_session.client('ecr', region_name=self.region_name)

        msg = COMPUTE_CLI_MSG.format('AWS Lambda')
        logger.info("{} - Region: {}".format(msg, self.region_name))

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
        if '/' in runtime_name:
            runtime_name = runtime_name.rsplit('/')[-1]
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

    def _create_handler_bin(self, remove=False):
        """
        Creates Lithops handler zip
        return : zip binary
        """
        logger.debug('Creating function handler zip in {}'.format(ACTION_ZIP_PATH))

        try:
            with zipfile.ZipFile('lithops_lambda.zip', 'w') as lithops_zip:
                current_location = os.path.dirname(os.path.abspath(__file__))
                module_location = os.path.dirname(os.path.abspath(lithops.__file__))
                main_file = os.path.join(current_location, 'entry_point.py')
                lithops_zip.write(main_file,
                                  '__main__.py',
                                  zipfile.ZIP_DEFLATED)
                add_directory_to_zip(lithops_zip, module_location, sub_dir='lithops')

            with open('lithops_lambda.zip', 'rb') as action_zip:
                action_bin = action_zip.read()

            if remove:
                os.remove('lithops_lambda.zip')
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
        logger.debug('Creating layer {} ...'.format(layer_name))
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

    def build_runtime(self, runtime_name, runtime_file):
        if runtime_file is None:
            raise Exception('Please provide a `requirements.txt` or Dockerfile')
        if self._python_runtime_name not in lambda_config.DEFAULT_RUNTIMES:
            raise Exception('Python runtime "{}" is not available for AWS Lambda, '
                            'please use one of {}'.format(self._python_runtime_name, lambda_config.DEFAULT_RUNTIMES))

        logger.info('Going to create runtime {} ({}) for AWS Lambda...'.format(runtime_name, runtime_file))

        if '/' in runtime_name:
            # Container runtime
            image_name = runtime_name.split('/')[1]
            self._create_handler_bin(remove=False)
            if runtime_file:
                cmd = '{} build -t {} -f {} .'.format(lambda_config.DOCKER_PATH,
                                                      image_name,
                                                      runtime_file)
            else:
                cmd = '{} build -t {} .'.format(lambda_config.DOCKER_PATH, image_name)

            res = os.system(cmd)
            if res != 0:
                raise Exception('There was an error building the runtime')

            ecr_repo = '{}.dkr.ecr.{}.amazonaws.com'.format(self.account_id, self.region_name)

            cmd = 'aws ecr get-login-password --region {} ' \
                  '| {} login --username AWS --password-stdin {}'.format(self.region_name,
                                                                         lambda_config.DOCKER_PATH, ecr_repo)

            res = os.system(cmd)
            if res != 0:
                raise Exception('Could not authorize Docker for ECR')

            self.ecr_client.create_repository(repositoryName=image_name)

            cmd = '{} tag {} {}/{} && {} push {}/{}'.format(lambda_config.DOCKER_PATH, image_name, ecr_repo, image_name,
                                                            lambda_config.DOCKER_PATH, ecr_repo, image_name)
            os.system(cmd)

            if res != 0:
                raise Exception('Could not push image {} to ECR repository {}'.format(image_name, ecr_repo))
        else:
            # requiremets.txt runtime
            with open(runtime_file, 'r') as req_file:
                requirements = req_file.read()
            self.internal_storage.put_data('/'.join([lambda_config.USER_RUNTIME_PREFIX, runtime_name]), requirements)

        logger.info('Ok - Created runtime {}'.format(runtime_name))

    def create_runtime(self, runtime_name, memory=3008, timeout=900):
        """
        Create a Lithops runtime as an AWS Lambda function
        """
        function_name = self._format_action_name(runtime_name, memory)
        logger.debug('Creating new Lithops lambda runtime: {}'.format(function_name))
        python_runtime_ver = 'python{}'.format(version_str(sys.version_info))

        if '/' in runtime_name:
            image_name = runtime_name.split('/')[1]

            try:
                response = self.ecr_client.describe_images(repositoryName=image_name)

                image = response['imageDetails'].pop()
                image_digest = image['imageDigest']
            except botocore.exceptions.ClientError:
                raise Exception('Runtime {} is not deployed to ECR')

            image_uri = '{}.dkr.ecr.{}.amazonaws.com/{}@{}'.format(self.account_id, self.region_name,
                                                                   image_name, image_digest)

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
            runtime_layer_arn = self._check_runtime_layer(runtime_name)
            if runtime_layer_arn is None:
                runtime_layer_arn = self._create_layer(runtime_name)

            code = self._create_handler_bin()
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
                Layers=[runtime_layer_arn, self._numerics_layer_arn],
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
            logger.debug('OK --> Created action {}'.format(runtime_name))

            retries = 45 if 'vpc' in self.aws_lambda_config else 30  # VPC lambdas take longer to deploy
            while retries > 0:
                response = self.lambda_client.get_function(
                    FunctionName=function_name
                )
                state = response['Configuration']['State']
                if state == 'Pending':
                    time.sleep(5)
                    logger.debug(
                        'Function is being deployed... (status: {})'.format(response['Configuration']['State']))
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

    def _generate_runtime_meta(self, runtime_name, runtime_memory):
        """
        Extract preinstalled Python modules from lambda function execution environment
        return : runtime meta dictionary
        """
        logger.debug('Extracting Python modules list from: {}'.format(runtime_name))

        meta = self.invoke_with_result(runtime_name, runtime_memory, payload={'get_preinstalls': {}})

        return meta
