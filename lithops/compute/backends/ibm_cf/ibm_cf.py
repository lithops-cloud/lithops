#
# (C) Copyright IBM Corp. 2020
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
import sys
import base64
import logging
import textwrap
from . import config as ibmcf_config
from datetime import datetime, timezone
from ibm_botocore.credentials import DefaultTokenManager
from lithops.utils import version_str
from lithops.version import __version__
from lithops.utils import is_lithops_function
from lithops.config import CACHE_DIR, load_yaml_config, dump_yaml_config
from lithops.libs.openwhisk.client import OpenWhiskClient
from lithops.compute.utils import create_function_handler_zip

logger = logging.getLogger(__name__)


class IBMCloudFunctionsBackend:
    """
    A wrap-up around IBM Cloud Functions backend.
    """

    def __init__(self, ibm_cf_config, storage_config):
        logger.debug("Creating IBM Cloud Functions client")
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.name = 'ibm_cf'
        self.ibm_cf_config = ibm_cf_config
        self.is_lithops_function = is_lithops_function()

        self.user_agent = ibm_cf_config['user_agent']
        self.region = ibm_cf_config['region']
        self.endpoint = ibm_cf_config['regions'][self.region]['endpoint']
        self.namespace = ibm_cf_config['regions'][self.region]['namespace']
        self.namespace_id = ibm_cf_config['regions'][self.region].get('namespace_id', None)
        self.api_key = ibm_cf_config['regions'][self.region].get('api_key', None)
        self.iam_api_key = ibm_cf_config.get('iam_api_key', None)

        logger.info("Set IBM CF Namespace to {}".format(self.namespace))
        logger.info("Set IBM CF Endpoint to {}".format(self.endpoint))

        self.user_key = self.api_key[:5] if self.api_key else self.iam_api_key[:5]
        self.package = 'lithops_v{}_{}'.format(__version__, self.user_key)

        if self.api_key:
            enc_api_key = str.encode(self.api_key)
            auth_token = base64.encodebytes(enc_api_key).replace(b'\n', b'')
            auth = 'Basic %s' % auth_token.decode('UTF-8')

            self.cf_client = OpenWhiskClient(endpoint=self.endpoint,
                                             namespace=self.namespace,
                                             auth=auth,
                                             user_agent=self.user_agent)
        elif self.iam_api_key:
            token_manager = DefaultTokenManager(api_key_id=self.iam_api_key)
            token_filename = os.path.join(CACHE_DIR, 'ibm_cf', 'iam_token')

            if 'token' in self.ibm_cf_config:
                logger.debug("Using IBM IAM API Key - Reusing Token from config")
                token_manager._token = self.ibm_cf_config['token']
                token_manager._expiry_time = datetime.strptime(self.ibm_cf_config['token_expiry_time'],
                                                               '%Y-%m-%d %H:%M:%S.%f%z')
                token_minutes_diff = int((token_manager._expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0)
                logger.debug("Token expiry time: {} - Minutes left: {}".format(token_manager._expiry_time, token_minutes_diff))

            elif os.path.exists(token_filename):
                logger.debug("Using IBM IAM API Key - Reusing Token from local cache")
                token_data = load_yaml_config(token_filename)
                token_manager._token = token_data['token']
                token_manager._expiry_time = datetime.strptime(token_data['token_expiry_time'],
                                                               '%Y-%m-%d %H:%M:%S.%f%z')
                token_minutes_diff = int((token_manager._expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0)
                logger.debug("Token expiry time: {} - Minutes left: {}".format(token_manager._expiry_time, token_minutes_diff))

            if (token_manager._is_expired() or token_minutes_diff < 11) and not is_lithops_function():
                logger.debug("Using IBM IAM API Key - Token expired. Requesting new token")
                token_manager._token = None
                token_manager.get_token()
                token_data = {}
                token_data['token'] = token_manager._token
                token_data['token_expiry_time'] = token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')
                dump_yaml_config(token_filename, token_data)

            ibm_cf_config['token'] = token_manager._token
            ibm_cf_config['token_expiry_time'] = token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')

            auth_token = token_manager._token
            auth = 'Bearer ' + auth_token

            self.cf_client = OpenWhiskClient(endpoint=self.endpoint,
                                             namespace=self.namespace_id,
                                             auth=auth,
                                             user_agent=self.user_agent)

        log_msg = ('Lithops v{} init for IBM Cloud Functions - Namespace: {} - '
                   'Region: {}'.format(__version__, self.namespace, self.region))
        if not self.log_active:
            print(log_msg)
        logger.info("IBM CF client created successfully")

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '_').replace(':', '_')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _unformat_action_name(self, action_name):
        runtime_name, memory = action_name.rsplit('_', 1)
        image_name = runtime_name.replace('_', '/', 1)
        image_name = image_name.replace('_', ':', -1)
        return image_name, int(memory.replace('MB', ''))

    def _get_default_runtime_image_name(self):
        python_version = version_str(sys.version_info)
        return ibmcf_config.RUNTIME_DEFAULT[python_version]

    def _delete_function_handler_zip(self):
        os.remove(ibmcf_config.FH_ZIP_LOCATION)

    def build_runtime(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info('Building a new docker image from Dockerfile')
        logger.info('Docker image name: {}'.format(docker_image_name))

        if dockerfile:
            cmd = 'docker build -t {} -f {} .'.format(docker_image_name, dockerfile)
        else:
            cmd = 'docker build -t {} .'.format(docker_image_name)

        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        cmd = 'docker push {}'.format(docker_image_name)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')

    def create_runtime(self, docker_image_name, memory, timeout):
        """
        Creates a new runtime into IBM CF namespace from an already built Docker image
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()

        runtime_meta = self._generate_runtime_meta(docker_image_name)

        logger.info('Creating new Lithops runtime based on Docker image {}'.format(docker_image_name))

        self.cf_client.create_package(self.package)
        action_name = self._format_action_name(docker_image_name, memory)

        create_function_handler_zip(ibmcf_config.FH_ZIP_LOCATION, '__main__.py', __file__)

        with open(ibmcf_config.FH_ZIP_LOCATION, "rb") as action_zip:
            action_bin = action_zip.read()
        self.cf_client.create_action(self.package, action_name, docker_image_name, code=action_bin,
                                     memory=memory, is_binary=True, timeout=timeout*1000)
        self._delete_function_handler_zip()
        return runtime_meta

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()
        action_name = self._format_action_name(docker_image_name, memory)
        self.cf_client.delete_action(self.package, action_name)

    def delete_all_runtimes(self):
        """
        Deletes all runtimes from all packages
        """
        packages = self.cf_client.list_packages()
        for pkg in packages:
            if (pkg['name'].startswith('lithops') and pkg['name'].endswith(self.user_key)) or \
               (pkg['name'].startswith('lithops') and pkg['name'].count('_') == 1):
                actions = self.cf_client.list_actions(pkg['name'])
                while actions:
                    for action in actions:
                        self.cf_client.delete_action(pkg['name'], action['name'])
                    actions = self.cf_client.list_actions(pkg['name'])
                self.cf_client.delete_package(pkg['name'])

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed in the IBM CF service
        return: list of tuples (docker_image_name, memory)
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()
        runtimes = []
        actions = self.cf_client.list_actions(self.package)

        for action in actions:
            action_image_name, memory = self._unformat_action_name(action['name'])
            if docker_image_name == action_image_name or docker_image_name == 'all':
                runtimes.append((action_image_name, memory))
        return runtimes

    def invoke(self, docker_image_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        action_name = self._format_action_name(docker_image_name, runtime_memory)

        activation_id = self.cf_client.invoke(package=self.package,
                                              action_name=action_name,
                                              payload=payload,
                                              is_ow_action=self.is_lithops_function)

        return activation_id

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_action_name(docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.name, self.region, self.namespace, action_name)

        return runtime_key

    def _generate_runtime_meta(self, docker_image_name):
        """
        Extract installed Python modules from docker image
        """
        action_code = """
            import sys
            import pkgutil

            def main(args):
                print("Extracting preinstalled Python modules...")
                runtime_meta = dict()
                mods = list(pkgutil.iter_modules())
                runtime_meta["preinstalls"] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
                python_version = sys.version_info
                runtime_meta["python_ver"] = str(python_version[0])+"."+str(python_version[1])
                print("Done!")
                return runtime_meta
            """

        runtime_memory = 128
        # old_stdout = sys.stdout
        # sys.stdout = open(os.devnull, 'w')
        action_name = self._format_action_name(docker_image_name, runtime_memory)
        self.cf_client.create_package(self.package)
        self.cf_client.create_action(self.package, action_name, docker_image_name,
                                     is_binary=False, code=textwrap.dedent(action_code),
                                     memory=runtime_memory, timeout=30000)
        # sys.stdout = old_stdout
        logger.debug("Extracting Python modules list from: {}".format(docker_image_name))

        try:
            retry_invoke = True
            while retry_invoke:
                retry_invoke = False
                runtime_meta = self.cf_client.invoke_with_result(self.package, action_name)
                if 'activationId' in runtime_meta:
                    retry_invoke = True
        except Exception:
            raise("Unable to invoke 'modules' action")
        try:
            self.delete_runtime(docker_image_name, runtime_memory)
        except Exception:
            raise Exception("Unable to delete 'modules' action")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta
