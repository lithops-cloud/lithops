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
import json
import base64
import httplib2
import zipfile
import time
import google.auth
from google.cloud import pubsub_v1
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from google.auth import jwt

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG, JOBS_PREFIX, TEMP_DIR

from . import config

logger = logging.getLogger(__name__)


class GCPFunctionsBackend:
    def __init__(self, gcf_config, internal_storage):
        self.name = 'gcp_functions'
        self.type = 'faas'
        self.gcf_config = gcf_config
        self.region = gcf_config['region']
        self.num_retries = gcf_config['retries']
        self.retry_sleep = gcf_config['retry_sleep']
        self.trigger = gcf_config['trigger']
        self.credentials_path = gcf_config.get('credentials_path')

        self.internal_storage = internal_storage

        self._build_api_resource()

        msg = COMPUTE_CLI_MSG.format('Google Cloud Functions')
        logger.info(f"{msg} - Region: {self.region} - Project: {self.project_name}")

    def _format_function_name(self, runtime_name, runtime_memory=None):
        version = 'lithops_v' + __version__
        runtime_name = (version + '_' + runtime_name).replace('.', '-')

        if runtime_memory:
            return f'{runtime_name}_{runtime_memory}MB'
        else:
            return f'{runtime_name}'
    
    def _unformat_function_name(self, function_name):
        runtime_name, runtime_memory = function_name.rsplit('_', 1)
        runtime_name = runtime_name.replace('lithops_v', '')
        version, runtime_name = runtime_name.split('_', 1)
        version = version.replace('-', '.')
        return version, runtime_name, runtime_memory.replace('MB', '')

    def _build_api_resource(self):
        """
        Setup Credentials and resources
        """
        if self.credentials_path and os.path.isfile(self.credentials_path):
            logger.debug(f'Getting GCP credentials from {self.credentials_path}')
            
            api_cred = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=config.SCOPES
            )
            self.project_name = api_cred.project_id
            self.service_account = api_cred.service_account_email
            
            pubsub_cred = jwt.Credentials.from_service_account_file(
                self.credentials_path,
                audience=config.AUDIENCE
            ) 
        else:
            logger.debug(f'Getting GCP credentials from the environment')
            api_cred, self.project_name = google.auth.default(scopes=config.SCOPES)
            self.service_account = api_cred.service_account_email
            pubsub_cred = None

        self._pub_client = pubsub_v1.PublisherClient(credentials=pubsub_cred)

        http = AuthorizedHttp(api_cred, http=httplib2.Http())
        self._api_resource = build(
            'cloudfunctions', config.FUNCTIONS_API_VERSION,
            http=http, cache_discovery=False
        )

    @property
    def _default_location(self):
        return f'projects/{self.project_name}/locations/{self.region}'

    def _format_topic_name(self, runtime_name, runtime_memory):
        return self._format_function_name(runtime_name, runtime_memory) +'_'+ self.region + '_topic'

    def _get_default_runtime_name(self):
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        return  f'lithops-default-runtime-v{py_version}'

    def _get_topic_location(self, topic_name):
        return f'projects/{self.project_name}/topics/{topic_name}'

    def _get_function_location(self, function_name):
        return f'{self._default_location}/functions/{function_name}'

    def _get_runtime_bin_location(self, runtime_name):
        function_name =  self._format_function_name(runtime_name)
        return config.USER_RUNTIMES_PREFIX + '/' + function_name + '_bin.zip'

    def _encode_payload(self, payload):
        return base64.b64encode(bytes(json.dumps(payload), 'utf-8')).decode('utf-8')

    def _list_built_runtimes(self, default_runtimes=True):
        """
        Lists all the built runtimes uploaded by self.build_runtime()
        """
        runtimes = []

        if default_runtimes:
            runtimes.extend(self._get_default_runtime_name())

        user_runtimes_keys = self.internal_storage.storage.list_keys(
            self.internal_storage.bucket, prefix=config.USER_RUNTIMES_PREFIX
        )
        runtimes.extend([runtime for runtime in user_runtimes_keys])
        return runtimes

    def _wait_function_deleted(self, function_location):
        # Wait until function is completely deleted
        while True:
            try:
                response = self._api_resource.projects().locations().functions().get(
                    name=function_location
                ).execute(num_retries=self.num_retries)
                logger.debug(f'Function status is {response["status"]}')
                if response['status'] == 'DELETE_IN_PROGRESS':
                    time.sleep(self.retry_sleep)
                else:
                    raise Exception(f'Unknown status: {response["status"]}')
            except Exception as e:
                logger.debug(f'Function status is DELETED')
                break

    def _create_function(self, runtime_name, memory, timeout=60):
        """
        Creates all the resources needed by a function
        """
        # Create topic
        topic_name = self._format_topic_name(runtime_name, memory)
        topic_location = self._get_topic_location(topic_name)
        logger.debug(f"Creating topic {topic_location}")
        topic_list_response = self._pub_client.list_topics(
            request={'project': f'projects/{self.project_name}'})
        topics = [topic.name for topic in topic_list_response]
        if topic_location in topics:
            logger.debug(f"Topic {topic_location} already exists - Restarting queue")
            self._pub_client.delete_topic(topic=topic_location)
        self._pub_client.create_topic(name=topic_location)

        # Create the function
        function_name = self._format_function_name(runtime_name, memory)
        function_location = self._get_function_location(function_name)
        logger.debug(f"Creating function {topic_location}")

        fn_list_response = self._api_resource.projects().locations().functions().list(
            parent=self._default_location
        ).execute(num_retries=self.num_retries)
        if 'functions' in fn_list_response:
            deployed_functions = [fn['name'] for fn in fn_list_response['functions']]
            if function_location in deployed_functions:
                logger.debug(f"Function {function_location} already exists - Deleting function")
                self._api_resource.projects().locations().functions().delete(
                    name=function_location,
                ).execute(num_retries=self.num_retries)
                self._wait_function_deleted(function_location)

        bin_location = self._get_runtime_bin_location(runtime_name)
        cloud_function = {
            'name': function_location,
            'description': 'Lithops Worker for Lithops v'+ __version__,
            'entryPoint': 'main',
            'runtime': config.AVAILABLE_PY_RUNTIMES[utils.CURRENT_PY_VERSION],
            'timeout': str(timeout) + 's',
            'availableMemoryMb': memory,
            'serviceAccountEmail': self.service_account,
            'maxInstances': 0,
            'sourceArchiveUrl': f'gs://{self.internal_storage.bucket}/{bin_location}'
        }

        if self.trigger == 'http':
            cloud_function['httpsTrigger'] = {}

        elif self.trigger == 'pub/sub':
            topic_name = self._format_topic_name(runtime_name, memory)
            topic_location = self._get_topic_location(topic_name)
            cloud_function['eventTrigger'] = {
                'eventType': 'providers/cloud.pubsub/eventTypes/topic.publish',
                'resource': topic_location,
                'failurePolicy': {}
            }

        logger.debug(f'Creating function {function_location}')
        response = self._api_resource.projects().locations().functions().create(
            location=self._default_location,
            body=cloud_function
        ).execute(num_retries=self.num_retries)

        # Wait until function is completely deployed
        logger.info('Waiting for the function to be deployed')
        while True:
            response = self._api_resource.projects().locations().functions().get(
                name=function_location
            ).execute(num_retries=self.num_retries)
            logger.debug(f'Function status is {response["status"]}')
            if response['status'] == 'ACTIVE':
                break
            elif response['status'] == 'OFFLINE':
                raise Exception('Error while deploying Cloud Function')
            elif response['status'] == 'DEPLOY_IN_PROGRESS':
                time.sleep(self.retry_sleep)
            else:
                raise Exception(f"Unknown status {response['status']}")

    def build_runtime(self, runtime_name, requirements_file, extra_args=[]):
        logger.info(f'Building runtime {runtime_name} from {requirements_file}')

        if not requirements_file:
            raise Exception('Please provide a "requirements.txt" file with the necessary modules')

        try:
            entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
            utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, 'main.py')
            with zipfile.ZipFile(config.FH_ZIP_LOCATION, 'a') as lithops_zip:
                lithops_zip.write(requirements_file, 'requirements.txt', zipfile.ZIP_DEFLATED)
            with open(config.FH_ZIP_LOCATION, "rb") as action_zip:
                action_bin = action_zip.read()
            bin_location = self._get_runtime_bin_location(runtime_name)
            self.internal_storage.put_data(bin_location, action_bin)
        finally:
            os.remove(config.FH_ZIP_LOCATION)

        logger.debug(f'Runtime {runtime_name} built successfuly')

    def _build_default_runtime(self, runtime_name):
        """
        Builds the default runtime
        """
        requirements_file = os.path.join(TEMP_DIR, 'gcf_default_requirements.txt')
        with open(requirements_file, 'w') as reqf:
            reqf.write(config.REQUIREMENTS_FILE)
        try:
            self.build_runtime(runtime_name, requirements_file)
        finally:
            os.remove(requirements_file)

    def deploy_runtime(self, runtime_name, memory, timeout):
        logger.info(f"Deploying runtime: {runtime_name} - Memory: {memory} Timeout: {timeout}")

        if runtime_name == self._get_default_runtime_name():
            self._build_default_runtime(runtime_name)

        self._create_function(runtime_name, memory, timeout)

        # Get runtime metadata
        runtime_meta = self._generate_runtime_meta(runtime_name, memory)

        return runtime_meta

    def delete_runtime(self, runtime_name, runtime_memory):
        function_name = self._format_function_name(runtime_name, runtime_memory)
        function_location = self._get_function_location(function_name)
        logger.info(f'Deleting runtime: {runtime_name} - {runtime_memory}MB')

        # Delete function
        self._api_resource.projects().locations().functions().delete(
            name=function_location,
        ).execute(num_retries=self.num_retries)
        logger.debug('Request Ok - Waiting until function is completely deleted')

        self._wait_function_deleted(function_location)

        # Delete Pub/Sub topic attached as trigger for the cloud function
        logger.debug('Listing Pub/Sub topics')
        topic_name = self._format_topic_name(runtime_name, runtime_memory)
        topic_location = self._get_topic_location(topic_name)
        topic_list_request = self._pub_client.list_topics(
            request={'project': f'projects/{self.project_name}'}
        )
        topics = [topic.name for topic in topic_list_request]
        if topic_location in topics:
            logger.debug(f'Going to delete topic {topic_name}')
            self._pub_client.delete_topic(topic=topic_location)
            logger.debug(f'Ok - topic {topic_name} deleted')

        # Delete user runtime from storage
        bin_location = self._get_runtime_bin_location(runtime_name)
        user_runtimes = self._list_built_runtimes(default_runtimes=False)
        if bin_location in user_runtimes:
            self.internal_storage.storage.delete_object(
                self.internal_storage.bucket, bin_location)

    def clean(self):
        logger.debug('Going to delete all deployed runtimes')
        runtimes = self.list_runtimes()
        for runtime_name, runtime_memory, version in runtimes:
            self.delete_runtime(runtime_name, runtime_memory)

    def list_runtimes(self, runtime_name='all'):
        logger.debug('Listing deployed runtimes')
        response = self._api_resource.projects().locations().functions().list(
            parent=self._default_location
        ).execute(num_retries=self.num_retries)

        deployed_runtimes = [f['name'].split('/')[-1] for f in response.get('functions', [])]
        runtimes = []
        for func_runtime in deployed_runtimes:
            if 'lithops_v' in func_runtime:
                version, fn_name, memory = self._unformat_function_name(func_runtime)
                if runtime_name == fn_name or runtime_name == 'all':
                    runtimes.append((fn_name, memory, version))

        return runtimes

    def invoke(self, runtime_name, runtime_memory, payload={}):
        topic_location = self._get_topic_location(self._format_topic_name(runtime_name, runtime_memory))

        fut = self._pub_client.publish(
            topic_location,
            bytes(json.dumps(payload, default=str).encode('utf-8'))
        )
        invocation_id = fut.result()

        return invocation_id

    def _generate_runtime_meta(self, runtime_name, memory):
        logger.debug(f'Extracting runtime metadata from: {runtime_name}')

        function_name = self._format_function_name(runtime_name, memory)
        function_location = self._get_function_location(function_name)

        payload = {
            'get_metadata': {
                'runtime_name': runtime_name,
                'storage_config': self.internal_storage.storage.storage_config
            }
        }

        # Data is b64 encoded so we can treat REST call the same as async pub/sub event trigger
        response = self._api_resource.projects().locations().functions().call(
            name=function_location,
            body={'data': json.dumps({'data': self._encode_payload(payload)})}
        ).execute(num_retries=self.num_retries)

        if 'result' in response and response['result'] == 'OK':
            object_key = '/'.join([JOBS_PREFIX, runtime_name + '.meta'])

            runtime_meta_json = self.internal_storage.get_data(object_key)
            runtime_meta = json.loads(runtime_meta_json)
            self.internal_storage.storage.delete_object(self.internal_storage.bucket, object_key)
            return runtime_meta
        elif 'error' in response:
            raise Exception(response['error'])
        else:
            raise Exception(f'Error at retrieving runtime meta: {response}')

    def get_runtime_key(self, runtime_name, runtime_memory):
        function_name = self._format_function_name(runtime_name, runtime_memory)
        runtime_key = os.path.join(self.name, __version__, self.project_name, self.region, function_name)
        logger.debug(f'Runtime key: {runtime_key}')

        return runtime_key

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if utils.CURRENT_PY_VERSION not in config.AVAILABLE_PY_RUNTIMES:
            raise Exception(f'Python {utils.CURRENT_PY_VERSION} is not available for Google '
             f'Cloud Functions. Please use one of {config.AVAILABLE_PY_RUNTIMES.keys()}')

        if 'runtime' not in self.gcf_config or self.gcf_config['runtime'] == 'default':
            self.gcf_config['runtime'] = self._get_default_runtime_name()
        
        runtime_info = {
            'runtime_name': self.gcf_config['runtime'],
            'runtime_memory': self.gcf_config['runtime_memory'],
            'runtime_timeout': self.gcf_config['runtime_timeout'],
            'max_workers': self.gcf_config['max_workers'],
        }

        return runtime_info
