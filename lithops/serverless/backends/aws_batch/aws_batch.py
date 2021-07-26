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
import base64
import copy
import json
import os
import re
import logging
import subprocess
import sys
import time
import boto3

import lithops

from . import config as batch_config
from lithops.constants import COMPUTE_CLI_MSG
from lithops.utils import create_handler_zip, version_str
from lithops.storage.utils import StorageNoSuchKeyError

logger = logging.getLogger(__name__)

RUNTIME_ZIP = 'lithops_aws_batch.zip'


class AWSBatchBackend:
    def __init__(self, aws_batch_config, internal_storage):
        """
        Initialize AWS Batch Backend
        """
        logger.debug('Creating AWS Lambda client')

        self.name = 'aws_batch'
        self.type = 'batch'
        self.aws_batch_config = aws_batch_config

        self.user_key = aws_batch_config['access_key_id'][-4:]
        self.package = 'aws-batch_lithops_v{}_{}'.format(lithops.__version__, self.user_key)
        self.region_name = aws_batch_config['region_name']
        self.role_arn = aws_batch_config['service_role']

        self._queue_name = '{}_job_queue'.format(self.package.replace('.', '-'))
        self._compute_env_name = '{}_compute_env'.format(self.package.replace('.', '-'))

        logger.debug('Creating Boto3 AWS Session and Batch Client')
        self.aws_session = boto3.Session(aws_access_key_id=aws_batch_config['access_key_id'],
                                         aws_secret_access_key=aws_batch_config['secret_access_key'],
                                         region_name=self.region_name)
        self.batch_client = self.aws_session.client('batch', region_name=self.region_name)

        self.internal_storage = internal_storage

        if self.aws_batch_config['account_id']:
            self.account_id = self.aws_batch_config['account_id']
        else:
            sts_client = self.aws_session.client('sts', region_name=self.region_name)
            self.account_id = sts_client.get_caller_identity()["Account"]

        self.ecr_client = self.aws_session.client('ecr', region_name=self.region_name)

        msg = COMPUTE_CLI_MSG.format('AWS Batch')
        logger.info("{} - Region: {}".format(msg, self.region_name))

    def _get_default_runtime_image_name(self):
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in lithops.__version__ else lithops.__version__.replace('.', '')
        runtime_name = '{}-v{}:{}'.format(batch_config.DEFAULT_RUNTIME_NAME, python_version, revision)
        return runtime_name

    def _get_full_image_name(self, runtime_name):
        full_image_name = runtime_name if ':' in runtime_name else '{}:latest'.format(runtime_name)
        registry = '{}.dkr.ecr.{}.amazonaws.com'.format(self.account_id, self.region_name)
        full_image_name = '/'.join([registry, self.package, full_image_name]).lower()
        repo_name = full_image_name.split('/', 1)[1:].pop().split(':')[0]
        return full_image_name, registry, repo_name

    def _format_jobdef_name(self, runtime_name, runtime_memory):
        fmt_runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        return '{}-{}--{}mb'.format(self.package.replace('.', '-'), fmt_runtime_name, runtime_memory)

    def _build_default_runtime(self, default_runtime_img_name):
        """
        Builds the default runtime
        """
        if os.system('{} --version >{} 2>&1'.format(batch_config.DOCKER_PATH, os.devnull)) == 0:
            # Build default runtime using local docker
            python_version = version_str(sys.version_info)
            dockerfile = "Dockerfile.default-batch-runtime"
            with open(dockerfile, 'w') as f:
                f.write("FROM python:{}-slim-buster\n".format(python_version))
                f.write(batch_config.DOCKERFILE_DEFAULT)
            self.build_runtime(default_runtime_img_name, dockerfile)
            os.remove(dockerfile)
        else:
            raise Exception('docker command not found. Install docker or use '
                            'an already built runtime')

    def _create_compute_env(self):
        res = self.batch_client.describe_compute_environments()

        if res['ResponseMetadata']['HTTPStatusCode'] != 200:
            raise Exception(res)

        compute_env_names = [compute_env['computeEnvironmentName'] for compute_env in res['computeEnvironments']]
        if self._compute_env_name not in compute_env_names:
            logger.debug('Creating new Compute Environment {}'.format(self._compute_env_name))
            compute_resources_spec = {
                'type': self.aws_batch_config['env_type'],
                'maxvCpus': self.aws_batch_config['max_cpus'],
                'subnets': self.aws_batch_config['subnets'],
                'securityGroupIds': self.aws_batch_config['security_groups']
            }

            if self.aws_batch_config['env_type'] == 'SPOT':
                compute_resources_spec['allocationStrategy'] = 'SPOT_CAPACITY_OPTIMIZED'

            res = self.batch_client.create_compute_environment(
                computeEnvironmentName=self._compute_env_name,
                type='MANAGED',
                computeResources=compute_resources_spec,
                serviceRole=self.aws_batch_config['service_role']
            )

            if res['ResponseMetadata']['HTTPStatusCode'] != 200:
                raise Exception(res)
            logger.debug('Compute Environment {} successfully created'.format(self._compute_env_name))
        else:
            logger.debug('Using existing Compute Environment {}'.format(self._compute_env_name))

    def _create_queue(self):
        res = self.batch_client.describe_job_queues()

        if res['ResponseMetadata']['HTTPStatusCode'] != 200:
            raise Exception(res)

        queue_names = [queue['jobQueueName'] for queue in res['jobQueues']]
        if self._queue_name not in queue_names:
            logger.debug('Creating new Queue {}'.format(self._queue_name))
            res = self.batch_client.create_job_queue(
                jobQueueName=self._queue_name,
                priority=1,
                computeEnvironmentOrder=[
                    {
                        'order': 0,
                        'computeEnvironment': self._compute_env_name
                    },
                ],
            )

            if res['ResponseMetadata']['HTTPStatusCode'] != 200:
                raise Exception(res)
            logger.debug('Queue {} successfully created'.format(self._queue_name))
        else:
            logger.debug('Using existing Queue {}'.format(self._queue_name))

    def _create_job_def(self, runtime_name, runtime_memory):
        job_def_name = self._format_jobdef_name(runtime_name, runtime_memory)

        res = self.batch_client.describe_job_definitions()

        if res['ResponseMetadata']['HTTPStatusCode'] != 200:
            raise Exception(res)

        job_def_names = [job_def['jobDefinitionName'] for job_def in res['jobDefinitions']
                         if job_def['status'] == 'ACTIVE']

        if job_def_name not in job_def_names:
            logger.debug('Creating new Job Definition {}'.format(job_def_name))
            image_name, _, _ = self._get_full_image_name(runtime_name)
            res = self.batch_client.register_job_definition(
                jobDefinitionName=job_def_name,
                type='container',
                containerProperties={
                    'image': image_name,
                    'executionRoleArn': self.aws_batch_config['service_role'],
                    'resourceRequirements': [
                        {
                            'value': '0.25',
                            'type': 'VCPU'
                        },
                        {
                            'value': '512',
                            'type': 'MEMORY'
                        }
                    ]
                },
                platformCapabilities=['FARGATE']
            )

            if res['ResponseMetadata']['HTTPStatusCode'] != 200:
                raise Exception(res)
            logger.debug('Job Definition {} successfully created'.format(job_def_name))
        else:
            logger.debug('Using existing Job Definition {}'.format(job_def_name))

    def _generate_runtime_meta(self, runtime_name, runtime_memory):
        job_name = '{}_preinstalls'.format(self._format_jobdef_name(runtime_name, runtime_memory))

        payload = copy.deepcopy(self.internal_storage.storage.storage_config)
        payload['runtime_name'] = runtime_name
        payload['log_level'] = logger.getEffectiveLevel()

        res = self.batch_client.submit_job(
            jobName=job_name,
            jobQueue=self._queue_name,
            jobDefinition=self._format_jobdef_name(runtime_name, runtime_memory),
            containerOverrides={
                'environment': [
                    {
                        'name': 'LITHOPS_ACTION',
                        'value': 'get_preinstalls'
                    },
                    {
                        'name': 'LITHOPS_CONFIG',
                        'value': json.dumps(payload)
                    }
                ]
            }
        )

        status_key = runtime_name + '.meta'
        retry = 10
        while retry > 10:
            try:
                runtime_meta_json = self.internal_storage.get_data(key=status_key)
                runtime_meta = json.loads(runtime_meta_json)
                print(runtime_meta)
                return runtime_meta
            except StorageNoSuchKeyError:
                logger.debug('Get runtime meta retry {}...')
                time.sleep(5)
                retry -= 1

    def build_runtime(self, runtime_name, runtime_file):
        """
        Build Lithops container runtime for AWS Batch
        @param runtime_name: name of the runtime to be built
        @param runtime_file: path of a Dockerfile for a container runtime
        """
        logger.debug('Building new docker image from Dockerfile')
        logger.debug('Docker image name: {}'.format(runtime_name))

        expression = '^([a-zA-Z0-9_-]+)(:[a-zA-Z0-9_-]+)+$'
        result = re.match(expression, runtime_name)

        if not result or result.group() != runtime_name:
            raise Exception("Runtime name must satisfy regex {}".format(expression))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        create_handler_zip(os.path.join(os.getcwd(), RUNTIME_ZIP), entry_point)

        res = self.ecr_client.get_authorization_token()
        if res['ResponseMetadata']['HTTPStatusCode'] != 200:
            raise Exception('Could not get ECR auth token: {}'.format(res))

        auth_data = res['authorizationData'].pop()
        ecr_token = base64.b64decode(auth_data['authorizationToken']).split(b':')[1]

        full_image_name, registry, repo_name = self._get_full_image_name(runtime_name)
        if runtime_file:
            cmd = '{} build -t {} -f {} .'.format(batch_config.DOCKER_PATH, full_image_name, runtime_file)
        else:
            cmd = '{} build -t {} .'.format(batch_config.DOCKER_PATH, full_image_name)

        subprocess.check_call(cmd.split())
        os.remove(RUNTIME_ZIP)

        cmd = '{} login --username AWS --password-stdin {}'.format(batch_config.DOCKER_PATH, registry)
        subprocess.check_output(cmd.split(), input=ecr_token)

        try:
            self.ecr_client.create_repository(repositoryName=repo_name,
                                              imageTagMutability='MUTABLE')
        except self.ecr_client.exceptions.RepositoryAlreadyExistsException as e:
            logger.info('Repository {} already exists'.format(repo_name))

        cmd = '{} push {}'.format(batch_config.DOCKER_PATH, full_image_name)
        subprocess.check_call(cmd.split())
        logger.debug('Runtime {} built successfully'.format(runtime_name))

    def create_runtime(self, runtime_name, runtime_memory, timeout=900):
        """
        Create a Lambda function with Lithops handler
        @param runtime_name: name of the runtime
        @param runtime_memory: runtime memory in MB
        @param timeout: runtime timeout in seconds
        @return: runtime metadata
        """
        default_runtime_img_name = self._get_default_runtime_image_name()
        if runtime_name in ['default', default_runtime_img_name]:
            # We only build the default image. rest of images must already exist
            # in the docker registry.
            self._build_default_runtime(default_runtime_img_name)

        self._create_compute_env()
        self._create_queue()
        self._create_job_def(runtime_name, runtime_memory)

        runtime_meta = self._generate_runtime_meta(runtime_name, runtime_memory)
        return runtime_meta

    def delete_runtime(self, runtime_name, runtime_memory):
        """
        Delete a Lithops lambda runtime
        @param runtime_name: name of the runtime to be deleted
        @param runtime_memory: memory of the runtime to be deleted in MB
        """
        pass

    def clean(self):
        """
        Deletes all Lithops lambda runtimes for this user
        """
        pass

    def list_runtimes(self, runtime_name=None):
        """
        List all the Lithops lambda runtimes deployed for this user
        @param runtime_name: name of the runtime to list, 'all' to list all runtimes
        @return: list of tuples (runtime name, memory)
        """
        pass

    def invoke(self, runtime_name, runtime_memory, payload):
        """
        Invoke lambda function asynchronously
        @param runtime_name: name of the runtime
        @param runtime_memory: memory of the runtime in MB
        @param payload: invoke dict payload
        @return: invocation ID
        """
        pass

    def get_runtime_key(self, runtime_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        jobdef_name = self._format_jobdef_name(runtime_name, runtime_memory)
        runtime_key = os.path.join(self.name, self.package, self.region_name, jobdef_name)
        return runtime_key