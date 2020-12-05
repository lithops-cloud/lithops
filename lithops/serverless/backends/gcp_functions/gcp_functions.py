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
import sys
import zipfile
import time
import textwrap
import lithops
from google.cloud import pubsub_v1
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth import jwt

from lithops.version import __version__
from lithops.utils import version_str
from lithops.storage import InternalStorage
from lithops.constants import COMPUTE_CLI_MSG
from lithops.constants import TEMP as TEMP_PATH
from . import config as gcp_config

logger = logging.getLogger(__name__)

ZIP_LOCATION = os.path.join(TEMP_PATH, 'lithops_gcp.zip')
SCOPES = ('https://www.googleapis.com/auth/cloud-platform',
          'https://www.googleapis.com/auth/pubsub')
FUNCTIONS_API_VERSION = 'v1'
PUBSUB_API_VERSION = 'v1'
AUDIENCE = "https://pubsub.googleapis.com/google.pubsub.v1.Publisher"


class GCPFunctionsBackend:
    def __init__(self, gcp_functions_config, storage_config):
        self.name = 'gcp_functions'
        self.gcp_functions_config = gcp_functions_config
        self.package = 'lithops_v' + __version__

        self.region = gcp_functions_config['region']
        self.service_account = gcp_functions_config['service_account']
        self.project = gcp_functions_config['project_name']
        self.credentials_path = gcp_functions_config['credentials_path']
        self.num_retries = gcp_functions_config['retries']
        self.retry_sleep = gcp_functions_config['retry_sleep']

        # Instantiate storage client (used to upload function bin)
        self.internal_storage = InternalStorage(storage_config)

        # Setup Pub/Sub client
        try:  # Get credentials from JSON file
            service_account_info = json.load(open(self.credentials_path))
            credentials = jwt.Credentials.from_service_account_info(service_account_info,
                                                                    audience=AUDIENCE)
            credentials_pub = credentials.with_claims(audience=AUDIENCE)
        except:  # Get credentials from gcp function environment
            credentials_pub = None
        self.publisher_client = pubsub_v1.PublisherClient(credentials=credentials_pub)

        msg = COMPUTE_CLI_MSG.format('GCP Functions')
        logger.info("{} - Region: {} - Project: {}".format(msg, self.region, self.project))

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = (self.package + '_' + runtime_name).replace('.', '-')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _format_topic_name(self, runtime_name, runtime_memory):
        return self._format_action_name(runtime_name, runtime_memory) + '_topic'

    def _unformat_action_name(self, action_name):
        split = action_name.split('_')
        runtime_name = split[2].replace('-', '.')
        runtime_memory = int(split[3].replace('MB', ''))
        return runtime_name, runtime_memory

    def _full_function_location(self, function_name):
        return 'projects/{}/locations/{}/functions/{}'.format(self.project, self.region, function_name)

    def _full_topic_location(self, topic_name):
        return 'projects/{}/topics/{}'.format(self.project, topic_name)

    def _full_default_location(self):
        return 'projects/{}/locations/{}'.format(self.project, self.region)

    def _encode_payload(self, payload):
        return base64.b64encode(bytes(json.dumps(payload), 'utf-8')).decode('utf-8')

    def _get_auth_session(self):
        credentials = service_account.Credentials.from_service_account_file(self.credentials_path,
                                                                            scopes=SCOPES)
        http = httplib2.Http()
        return AuthorizedHttp(credentials, http=http)

    def _get_funct_conn(self):
        http = self._get_auth_session()
        return build('cloudfunctions', FUNCTIONS_API_VERSION, http=http, cache_discovery=False)

    def _get_default_runtime_image_name(self):
        return 'python' + version_str(sys.version_info)

    def _get_runtime_requirements(self, runtime_name):
        if runtime_name in gcp_config.DEFAULT_RUNTIMES:
            return gcp_config.DEFAULT_REQUIREMENTS
        else:
            user_runtimes = self._list_runtimes(default_runtimes=False)
            if runtime_name in user_runtimes:
                raw_reqs = self.internal_storage.get_data(key='/'.join([gcp_config.USER_RUNTIMES_PREFIX, runtime_name]))
                reqs = raw_reqs.decode('utf-8')
                return reqs.splitlines()
            else:
                raise Exception('Runtime {} does not exist. '
                                'Available runtimes: {}'.format(runtime_name,
                                                                gcp_config.DEFAULT_RUNTIMES + user_runtimes))

    def _list_runtimes(self, default_runtimes=True):
        runtimes = []

        if default_runtimes:
            runtimes.extend(gcp_config.DEFAULT_RUNTIMES)

        user_runtimes_keys = self.internal_storage.storage.list_keys(self.internal_storage.bucket,
                                                                     prefix=gcp_config.USER_RUNTIMES_PREFIX)
        runtimes.extend([runtime.split('/', 1)[-1] for runtime in user_runtimes_keys])
        return runtimes

    def _create_handler_zip(self, runtime_name):
        logger.debug("Creating function handler zip in {}".format(ZIP_LOCATION))

        def add_folder_to_zip(zip_file, full_dir_path, sub_dir=''):
            for file in os.listdir(full_dir_path):
                full_path = os.path.join(full_dir_path, file)
                if os.path.isfile(full_path):
                    zip_file.write(full_path, os.path.join('lithops', sub_dir, file), zipfile.ZIP_DEFLATED)
                elif os.path.isdir(full_path) and '__pycache__' not in full_path:
                    add_folder_to_zip(zip_file, full_path, os.path.join(sub_dir, file))

        # Get runtime requirements
        runtime_requirements = self._get_runtime_requirements(runtime_name)
        requirements_file_path = os.path.join(TEMP_PATH, '{}_requirements.txt'.format(runtime_name))
        with open(requirements_file_path, 'w') as reqs_file:
            for req in runtime_requirements:
                reqs_file.write('{}\n'.format(req))

        try:
            with zipfile.ZipFile(ZIP_LOCATION, 'w') as lithops_zip:
                # Add Lithops entryfile to zip archive
                current_location = os.path.dirname(os.path.abspath(__file__))
                main_file = os.path.join(current_location, 'entry_point.py')
                lithops_zip.write(main_file, 'main.py', zipfile.ZIP_DEFLATED)

                # Add runtime requirements.txt to zip archive
                lithops_zip.write(requirements_file_path, 'requirements.txt', zipfile.ZIP_DEFLATED)

                # Add Lithops to zip archive
                module_location = os.path.dirname(os.path.abspath(lithops.__file__))
                add_folder_to_zip(lithops_zip, module_location)
        except Exception as e:
            raise Exception('Unable to create Lithops package: {}'.format(e))

    def _create_function(self, runtime_name, memory, code, timeout=60, trigger='HTTP'):
        logger.debug("Creating function {} - Memory: {} Timeout: {} Trigger: {}".format(runtime_name,
                                                                                        memory, timeout, trigger))
        default_location = self._full_default_location()
        function_location = self._full_function_location(self._format_action_name(runtime_name, memory))
        bin_name = self._format_action_name(runtime_name, memory) + '_bin.zip'
        self.internal_storage.put_data(bin_name, code)

        python_runtime_ver = 'python{}'.format(version_str(sys.version_info))

        cloud_function = {
            'name': function_location,
            'description': self.package,
            'entryPoint': 'main',
            'runtime': python_runtime_ver.lower().replace('.', ''),
            'timeout': str(timeout) + 's',
            'availableMemoryMb': memory,
            'serviceAccountEmail': self.service_account,
            'maxInstances': 0,
            'sourceArchiveUrl': 'gs://{}/{}'.format(self.internal_storage.bucket, bin_name)
        }

        if trigger == 'HTTP':
            cloud_function['httpsTrigger'] = {}
        elif trigger == 'Pub/Sub':
            topic_location = self._full_topic_location(self._format_topic_name(runtime_name, memory))
            cloud_function['eventTrigger'] = {
                'eventType': 'providers/cloud.pubsub/eventTypes/topic.publish',
                'resource': topic_location,
                'failurePolicy': {}
            }

        response = self._get_funct_conn().projects().locations().functions().create(
            location=default_location,
            body=cloud_function
        ).execute(num_retries=self.num_retries)

        # Wait until function is completely deployed
        while True:
            response = self._get_funct_conn().projects().locations().functions().get(
                name=function_location
            ).execute(num_retries=self.num_retries)
            logger.debug('Function status is {}'.format(response['status']))
            if response['status'] == 'ACTIVE':
                break
            elif response['status'] == 'OFFLINE':
                raise Exception('Error while deploying Cloud Function')
            elif response['status'] == 'DEPLOY_IN_PROGRESS':
                time.sleep(self.retry_sleep)
            else:
                raise Exception('Unknown status {}'.format(response['status']))

        # Delete runtime bin archive from storage
        self.internal_storage.storage.delete_object(self.internal_storage.bucket, bin_name)

    def build_runtime(self, runtime_name, requirements_file):
        if requirements_file is None:
            raise Exception('Please provide a `requirements.txt` file with the necessary modules')
        logger.info('Going to create runtime {} ({}) for GCP Functions...'.format(runtime_name, requirements_file))
        runtime_python_ver = 'python{}'.format(version_str(sys.version_info))
        if runtime_python_ver not in gcp_config.DEFAULT_RUNTIMES:
            raise Exception('Runtime {} is not available for GCP Functions, '
                            'please use one of {}'.format(runtime_python_ver, gcp_config.DEFAULT_RUNTIMES))

        with open(requirements_file, 'r') as req_file:
            requirements = req_file.read()

        self.internal_storage.put_data('/'.join([gcp_config.USER_RUNTIMES_PREFIX, runtime_name]), requirements)
        logger.info('Ok - Created runtime {}'.format(runtime_name))
        logger.info('Available runtimes: {}'.format(self._list_runtimes(default_runtimes=True)))

    def create_runtime(self, runtime_name, memory, timeout=60):
        logger.debug("Creating runtime {} - Memory: {} Timeout: {}".format(runtime_name, memory, timeout))

        # Get runtime preinstalls
        runtime_meta = self._generate_runtime_meta(runtime_name)

        # Create topic
        topic_name = self._format_topic_name(runtime_name, memory)
        topic_list_request = self.publisher_client.list_topics(request={'project': 'projects/{}'.format(self.project)})
        topic_location = self._full_topic_location(topic_name)
        topics = [topic.name for topic in topic_list_request]
        if topic_location in topics:
            logger.info("Topic {} already exists - Restarting queue...".format(topic_location))
            self.publisher_client.delete_topic(topic=topic_location)
        logger.debug("Creating topic {}...".format(topic_location))
        self.publisher_client.create_topic(name=topic_location)

        # Create function
        self._create_handler_zip(runtime_name)
        with open(ZIP_LOCATION, "rb") as action_zip:
            action_bin = action_zip.read()

        self._create_function(runtime_name, memory, code=action_bin, timeout=timeout, trigger='Pub/Sub')

        return runtime_meta

    def delete_runtime(self, runtime_name, runtime_memory, delete_runtime_storage=True):
        action_name = self._format_action_name(runtime_name, runtime_memory)
        function_location = self._full_function_location(action_name)
        logger.debug('Going to delete runtime {}'.format(action_name))

        # Delete function
        self._get_funct_conn().projects().locations().functions().delete(
            name=function_location,
        ).execute(num_retries=self.num_retries)
        logger.debug('Request Ok - Waiting until function is completely deleted')

        # Wait until function is completely deleted
        while True:
            try:
                response = self._get_funct_conn().projects().locations().functions().get(
                    name=function_location
                ).execute(num_retries=self.num_retries)
                logger.debug('Function status is {}'.format(response['status']))
                if response['status'] == 'DELETE_IN_PROGRESS':
                    time.sleep(self.retry_sleep)
                else:
                    raise Exception('Unknown status: {}'.format(response['status']))
            except HttpError as e:
                logger.debug('Ok - {}'.format(e))
                break

        # Delete Pub/Sub topic attached as trigger for the cloud function
        logger.debug('Listing Pub/Sub topics...')
        topic_name = self._format_topic_name(runtime_name, runtime_memory)
        topic_location = self._full_topic_location(topic_name)
        topic_list_request = self.publisher_client.list_topics(request={'project': 'projects/{}'.format(self.project)})
        topics = [topic.name for topic in topic_list_request]
        logger.debug('Topics: {}'.format(topics))
        if topic_location in topics:
            logger.debug('Going to delete topic {}'.format(topic_name))
            self.publisher_client.delete_topic(topic=topic_location)
            logger.debug('Ok - topic {} deleted'.format(topic_name))

        # Delete user runtime from storage
        user_runtimes = self._list_runtimes(default_runtimes=False)
        if runtime_name in user_runtimes and delete_runtime_storage:
            self.internal_storage.storage.delete_object(self.internal_storage.bucket,
                                                        '/'.join([gcp_config.USER_RUNTIMES_PREFIX, runtime_name]))

    def clean(self):
        logger.debug('Going to delete all deployed runtimes...')
        runtimes = self.list_runtimes()
        for runtime in runtimes:
            if 'lithops_v' in runtime:
                runtime_name, runtime_memory = self._unformat_action_name(runtime)
                self.delete_runtime(runtime_name, runtime_memory)

    def list_runtimes(self, docker_image_name='all'):
        logger.debug('Listing deployed runtimes...')
        response = self._get_funct_conn().projects().locations().functions().list(
            parent=self._full_default_location()
        ).execute(num_retries=self.num_retries)

        runtimes = [function['name'].split('/')[-1] for function in response.get('functions', [])]
        logger.debug('Deployed runtimes: {}'.format(runtimes))
        return runtimes

    def invoke(self, runtime_name, runtime_memory, payload={}):
        exec_id = payload['executor_id']
        call_id = payload['call_id']
        topic_location = self._full_topic_location(
            self._format_topic_name(runtime_name, runtime_memory))

        start = time.time()
        try:
            # Publish message
            fut = self.publisher_client.publish(
                topic_location, bytes(json.dumps(payload).encode('utf-8')))
            invocation_id = fut.result()
        except Exception as e:
            logger.debug('ExecutorID {} - Function {} invocation failed: {}'.format(exec_id, call_id, str(e)))
            return None

        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        logger.debug('ExecutorID {} - Function {} invocation done! ({}s) - Activation ID: {}'.format(exec_id,
                                                                                                     call_id, resp_time,
                                                                                                     invocation_id))

        return invocation_id

    def invoke_with_result(self, runtime_name, runtime_memory, payload={}):
        action_name = self._format_action_name(runtime_name, runtime_memory)
        function_location = self._full_function_location(action_name)
        logger.debug('Going to synchronously invoke {} through developer API'.format(action_name))

        response = self._get_funct_conn().projects().locations().functions().call(
            name=function_location,
            body={'data': json.dumps({'data': self._encode_payload(payload)})}
        ).execute(num_retries=self.num_retries)

        logger.debug('Invocation {} success'.format(action_name))
        return json.loads(response['result'])

    def get_runtime_key(self, runtime_name, runtime_memory):
        action_name = self._format_action_name(runtime_name, runtime_memory)
        runtime_key = os.path.join(self.name, self.region, action_name)
        logger.debug('Runtime key: {}'.format(runtime_key))
        return runtime_key

    def _generate_runtime_meta(self, runtime_name):
        action_code = """
            import sys
            import pkgutil
            import json

            def main(request):
                runtime_meta = dict()
                mods = list(pkgutil.iter_modules())
                runtime_meta['preinstalls'] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
                python_version = sys.version_info
                runtime_meta['python_ver'] = str(python_version[0])+"."+str(python_version[1])
                return json.dumps(runtime_meta)
        """
        logger.debug('Generating runtime meta for {}...'.format(runtime_name))

        # Get runtime requirements
        runtime_requirements = self._get_runtime_requirements(runtime_name)
        requirements_file_path = os.path.join(TEMP_PATH, '{}_requirements.txt'.format(runtime_name))
        with open(requirements_file_path, 'w') as reqs_file:
            for req in runtime_requirements:
                reqs_file.write('{}\n'.format(req))

        extract_modules_zip_path = os.path.join(TEMP_PATH, 'extract_modules_gcp.zip')
        try:
            with zipfile.ZipFile(extract_modules_zip_path, 'w') as extract_modules_zip:

                # Add action_code entrypoint as main.py to zip archive
                extract_modules_entrypoint_filename = os.path.join(TEMP_PATH, 'extract_modules_entrypoint.py')
                with open(extract_modules_entrypoint_filename, 'w') as extract_mods_entrypoint_f:
                    extract_mods_entrypoint_f.write(textwrap.dedent(action_code))
                extract_modules_zip.write(extract_modules_entrypoint_filename, 'main.py', zipfile.ZIP_DEFLATED)

                # Add runtime requirements.txt to zip archive
                extract_modules_zip.write(requirements_file_path, 'requirements.txt', zipfile.ZIP_DEFLATED)

        except Exception as e:
            raise Exception('Unable to create Lithops extract_modules package: {}'.format(e))

        with open(extract_modules_zip_path, 'rb') as modules_zip:
            function_zip_bin = modules_zip.read()

        self._create_function(runtime_name, 128, function_zip_bin, trigger='HTTP')

        logger.debug("Extracting Python modules list from: {}".format(runtime_name))
        try:
            runtime_meta = self.invoke_with_result(runtime_name, 128)
        except Exception as e:
            raise Exception("Unable to invoke 'modules' action: {}".format(e))
        try:
            self.delete_runtime(runtime_name, 128, delete_runtime_storage=False)
        except Exception as e:
            raise Exception("Unable to delete 'modules' action: {}".format(e))

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta
