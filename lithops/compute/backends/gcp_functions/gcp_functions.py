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
import urllib
import sys
import zipfile
import time
import random
import tempfile
import textwrap
from google.cloud import pubsub_v1
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth import jwt
import google.api_core.exceptions

import lithops
from lithops.version import __version__
from lithops.utils import version_str
from lithops import config
from lithops.storage import InternalStorage

logger = logging.getLogger(__name__)
logging.getLogger('googleapiclient').setLevel(logging.CRITICAL)
logging.getLogger('google_auth_httplib2').setLevel(logging.CRITICAL)
logging.getLogger('google.auth.transport.requests').setLevel(logging.CRITICAL)
logging.getLogger('google.cloud.pubsub_v1.publisher').setLevel(logging.CRITICAL)

ZIP_LOCATION = os.path.join(tempfile.gettempdir(), 'lithops_gcp.zip')
SCOPES = ('https://www.googleapis.com/auth/cloud-platform',
          'https://www.googleapis.com/auth/pubsub')
FUNCTIONS_API_VERSION = 'v1'
PUBSUB_API_VERSION = 'v1'
AUDIENCE = "https://pubsub.googleapis.com/google.pubsub.v1.Publisher"


class GCPFunctionsBackend:
    def __init__(self, gcp_functions_config, storage_config):
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.name = 'gcp_functions'
        self.gcp_functions_config = gcp_functions_config
        self.package = 'lithops_v'+__version__

        self.region = gcp_functions_config['region']
        self.service_account = gcp_functions_config['service_account']
        self.project = gcp_functions_config['project_name']
        self.credentials_path = gcp_functions_config['credentials_path']
        self.num_retries = gcp_functions_config['retries']
        self.retry_sleeps = gcp_functions_config['retry_sleeps']

        # Instantiate storage client (to upload function bin)
        self.internal_storage = InternalStorage(gcp_functions_config['storage'])

        # Setup pubsub client
        try:  # Get credenitals from JSON file
            service_account_info = json.load(open(self.credentials_path))
            credentials = jwt.Credentials.from_service_account_info(service_account_info,
                                                                    audience=AUDIENCE)
            credentials_pub = credentials.with_claims(audience=AUDIENCE)
        except Exception:  # Get credentials from gcp function environment
            credentials_pub = None
        self.publisher_client = pubsub_v1.PublisherClient(credentials=credentials_pub)

        log_msg = 'lithops v{} init for GCP Functions - Project: {} - Region: {}'.format(
            __version__, self.project, self.region)
        logger.info(log_msg)

        if not self.log_active:
            print(log_msg)

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = (self.package+'_'+runtime_name).replace('.', '-')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _format_topic_name(self, runtime_name, runtime_memory):
        return self._format_action_name(runtime_name, runtime_memory)+'_topic'

    def _unformat_action_name(self, action_name):
        split = action_name.split('_')
        runtime_name = split[1].replace('-', '.')
        runtime_memory = int(split[2].replace('MB', ''))
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
        return 'python'+version_str(sys.version_info)

    def _create_handler_zip(self):
        logger.debug("Creating function \
            handler zip in {}".format(ZIP_LOCATION))

        def add_folder_to_zip(zip_file, full_dir_path, sub_dir=''):
            for file in os.listdir(full_dir_path):
                full_path = os.path.join(full_dir_path, file)
                if os.path.isfile(full_path):
                    zip_file.write(full_path, os.path.join(
                        'lithops', sub_dir, file), zipfile.ZIP_DEFLATED)
                elif os.path.isdir(full_path) and '__pycache__' not in full_path:
                    add_folder_to_zip(zip_file, full_path,
                                      os.path.join(sub_dir, file))

        try:
            with zipfile.ZipFile(ZIP_LOCATION, 'w') as lithops_zip:
                current_location = os.path.dirname(os.path.abspath(__file__))
                module_location = os.path.dirname(os.path.abspath(lithops.__file__))
                main_file = os.path.join(current_location, 'entry_point.py')
                lithops_zip.write(main_file, 'main.py', zipfile.ZIP_DEFLATED)
                req_file = os.path.join(current_location, 'requirements.txt')
                lithops_zip.write(req_file, 'requirements.txt',
                                 zipfile.ZIP_DEFLATED)
                add_folder_to_zip(lithops_zip, module_location)
        except Exception as e:
            raise Exception(
                'Unable to create the {} package: {}'.format(ZIP_LOCATION, e))

    def _create_function(self, runtime_name, memory, code, timeout=60, trigger='HTTP'):
        logger.debug("Creating function {} - Memory: {} Timeout: {} Trigger: {}".format(
            runtime_name, memory, timeout, trigger))
        default_location = self._full_default_location()
        function_location = self._full_function_location(
            self._format_action_name(runtime_name, memory))
        bin_name = self._format_action_name(runtime_name, memory)+'_bin.zip'
        self.internal_storage.put_data(bin_name, code)

        cloud_function = {
            'name': function_location,
            'description': self.package,
            'entryPoint': 'main',
            'runtime': runtime_name.lower().replace('.', ''),
            'timeout': str(timeout)+'s',
            'availableMemoryMb': memory,
            'serviceAccountEmail': self.service_account,
            'maxInstances': 0,
            'sourceArchiveUrl': 'gs://{}/{}'.format(self.internal_storage.bucket, bin_name)
        }

        if trigger == 'HTTP':
            cloud_function['httpsTrigger'] = {}
        elif trigger == 'Pub/Sub':
            topic_location = self._full_topic_location(
                self._format_topic_name(runtime_name, memory))
            cloud_function['eventTrigger'] = {
                'eventType': 'providers/cloud.pubsub/eventTypes/topic.publish',
                'resource': topic_location,
                'failurePolicy': {}
            }

        response = self._get_funct_conn().projects().locations().functions().create(  # pylint: disable=no-member
            location=default_location,
            body=cloud_function
        ).execute(num_retries=self.num_retries)

        # Wait until function is completely deployed
        while True:
            response = self._get_funct_conn().projects().locations().functions().get(  # pylint: disable=no-member
                name=function_location
            ).execute(num_retries=self.num_retries)
            if response['status'] == 'ACTIVE':
                break
            else:
                time.sleep(random.choice(self.retry_sleeps))

    def build_runtime(self):
        pass

    def update_runtime(self, runtime_name, code, memory=3008, timeout=900):
        pass

    def create_runtime(self, runtime_name, memory, timeout=60):
        logger.debug("Creating runtime {} - \
            Memory: {} Timeout: {}".format(runtime_name, memory, timeout))

        # Get runtime preinstalls
        runtime_meta = self._generate_runtime_meta(runtime_name)

        # Create topic
        topic_name = self._format_topic_name(runtime_name, memory)
        topic_location = self._full_topic_location(topic_name)
        try:
            # Try getting topic config # pylint: disable=no-member
            self.publisher_client.get_topic(topic_location)
            # If no exception is raised, then the topic exists
            logger.info(
                "Topic {} already exists - Restarting queue...".format(topic_location))
            self.publisher_client.delete_topic(topic_location)
        except google.api_core.exceptions.GoogleAPICallError:
            pass
        logger.debug("Creating topic {}...".format(topic_location))
        self.publisher_client.create_topic(topic_location)

        # Create function
        self._create_handler_zip()
        with open(ZIP_LOCATION, "rb") as action_zip:
            action_bin = action_zip.read()

        self._create_function(runtime_name, memory,
                              action_bin, timeout=timeout, trigger='Pub/Sub')

        return runtime_meta

    def delete_runtime(self, runtime_name, runtime_memory):
        function_location = self._full_function_location(
            self._format_action_name(runtime_name, runtime_memory))

        self._get_funct_conn().projects().locations().functions().delete(  # pylint: disable=no-member
            name=function_location,
        ).execute(num_retries=self.num_retries)

        # Wait until function is completely deleted
        while True:
            try:
                response = self._get_funct_conn().projects().locations().functions().get(  # pylint: disable=no-member
                    name=function_location
                ).execute(num_retries=self.num_retries)
            except HttpError:
                break
            if response['status'] == 'DELETE_IN_PROGRESS':
                time.sleep(random.choice(self.retry_sleeps))

    def delete_all_runtimes(self):
        runtimes = self.list_runtimes()
        for runtime in runtimes:
            if 'lithops_v' in runtime:
                runtime_name, runtime_memory = self._unformat_action_name(
                    runtime)
                self.delete_runtime(runtime_name, runtime_memory)

    def list_runtimes(self, docker_image_name='all'):
        default_location = self._full_default_location()
        response = self._get_funct_conn().projects().locations().functions().list(  # pylint: disable=no-member
            location=default_location,
            body={}
        ).execute(num_retries=self.num_retries)

        result = response['Functions'] if 'Functions' in response else []
        return result

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
            invokation_id = fut.result()
        except Exception as e:
            logger.debug(
                'ExecutorID {} - Function {} invocation failed: {}'.format(exec_id, call_id, str(e)))
            return None

        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        logger.debug('ExecutorID {} - Function {} invocation done! ({}s) - Activation ID: {}'.format(
            exec_id, call_id, resp_time, invokation_id))

        return(invokation_id)

    def invoke_with_result(self, runtime_name, runtime_memory, payload={}):
        action_name = self._format_action_name(runtime_name, runtime_memory)
        function_location = self._full_function_location(action_name)

        response = self._get_funct_conn().projects().locations().functions().call(  # pylint: disable=no-member
            name=function_location,
            body={'data': json.dumps({'data': self._encode_payload(payload)})}
        ).execute(num_retries=self.num_retries)

        return json.loads(response['result'])

    def get_runtime_key(self, runtime_name, runtime_memory):
        action_name = self._format_action_name(runtime_name, runtime_memory)
        runtime_key = os.path.join(self.name, self.region, action_name)

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
        action_location = os.path.join(
            tempfile.gettempdir(), 'extract_preinstalls_gcp.py')
        with open(action_location, 'w') as f:
            f.write(textwrap.dedent(action_code))

        modules_zip_action = os.path.join(
            tempfile.gettempdir(), 'extract_preinstalls_gcp.zip')
        with zipfile.ZipFile(modules_zip_action, 'w') as extract_modules_zip:
            extract_modules_zip.write(action_location, 'main.py')
            extract_modules_zip.close()
        with open(modules_zip_action, 'rb') as modules_zip:
            action_code = modules_zip.read()

        self._create_function(runtime_name, 128, action_code, trigger='HTTP')

        logger.debug(
            "Extracting Python modules list from: {}".format(runtime_name))
        try:
            runtime_meta = self.invoke_with_result(runtime_name, 128)
        except Exception:
            raise("Unable to invoke 'modules' action")
        try:
            self.delete_runtime(runtime_name, 128)
        except Exception:
            raise("Unable to delete 'modules' action")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta
