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
from threading import Lock
from lithops.utils import version_str
from lithops.version import __version__
from lithops.utils import is_lithops_worker
from lithops.libs.openwhisk.client import OpenWhiskClient
from lithops.utils import create_handler_zip
from lithops.util.ibm_token_manager import IBMTokenManager
from lithops.constants import COMPUTE_CLI_MSG
from . import config as ibmcf_config

logger = logging.getLogger(__name__)
invoke_mutex = Lock()


class IBMCloudFunctionsBackend:
    """
    A wrap-up around IBM Cloud Functions backend.
    """

    def __init__(self, ibm_cf_config, internal_storage):
        logger.debug("Creating IBM Cloud Functions client")
        self.name = 'ibm_cf'
        self.type = 'faas'
        self.config = ibm_cf_config
        self.is_lithops_worker = is_lithops_worker()

        self.user_agent = ibm_cf_config['user_agent']
        self.endpoint = ibm_cf_config['endpoint']
        self.namespace = ibm_cf_config['namespace']
        self.namespace_id = ibm_cf_config.get('namespace_id', None)
        self.api_key = ibm_cf_config.get('api_key', None)
        self.iam_api_key = ibm_cf_config.get('iam_api_key', None)
        self.region = self.endpoint.split('//')[1].split('.')[0]

        self.invoke_error = None

        logger.debug("Set IBM CF Namespace to {}".format(self.namespace))
        logger.debug("Set IBM CF Endpoint to {}".format(self.endpoint))

        self.user_key = self.api_key.split(':')[1][:4] if self.api_key else self.iam_api_key[:4]
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
            api_key_type = 'IAM'
            token = self.config.get('token', None)
            token_expiry_time = self.config.get('token_expiry_time', None)
            self.ibm_token_manager = IBMTokenManager(self.iam_api_key,
                                                     api_key_type, token,
                                                     token_expiry_time)
            token, token_expiry_time = self.ibm_token_manager.get_token()

            self.config['token'] = token
            self.config['token_expiry_time'] = token_expiry_time

            auth = 'Bearer ' + token

            self.cf_client = OpenWhiskClient(endpoint=self.endpoint,
                                             namespace=self.namespace_id,
                                             auth=auth,
                                             user_agent=self.user_agent)

        msg = COMPUTE_CLI_MSG.format('IBM CF')
        logger.info("{} - Region: {} - Namespace: {}".format(msg, self.region,
                                                             self.namespace))

    def _format_function_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '_').replace(':', '_')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _unformat_function_name(self, action_name):
        runtime_name, memory = action_name.rsplit('_', 1)
        image_name = runtime_name.replace('_', '/', 1)
        image_name = image_name.replace('_', ':', -1)
        return image_name, int(memory.replace('MB', ''))

    def _get_default_runtime_image_name(self):
        python_version = version_str(sys.version_info)
        return ibmcf_config.RUNTIME_DEFAULT[python_version]

    def _delete_function_handler_zip(self):
        os.remove(ibmcf_config.FH_ZIP_LOCATION)

    def build_runtime(self, docker_image_name, dockerfile, extra_args=[]):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info('Building a new docker image from Dockerfile')
        logger.info('Docker image name: {}'.format(docker_image_name))

        if dockerfile:
            cmd = '{} build -t {} -f {} . '.format(ibmcf_config.DOCKER_PATH, docker_image_name, dockerfile)
        else:
            cmd = '{} build -t {} . '.format(ibmcf_config.DOCKER_PATH, docker_image_name)

        cmd = cmd+' '.join(extra_args)

        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        cmd = 'docker push {}'.format(docker_image_name)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')
        logger.info('Building done!')

    def deploy_runtime(self, docker_image_name, memory, timeout):
        """
        Creates a new runtime into IBM CF namespace from an already built Docker image
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()
        logger.debug(f"Deploying runtime: {docker_image_name} - Memory: {memory} Timeout: {timeout}")

        self.cf_client.create_package(self.package)
        action_name = self._format_function_name(docker_image_name, memory)

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        create_handler_zip(ibmcf_config.FH_ZIP_LOCATION, entry_point, '__main__.py')

        with open(ibmcf_config.FH_ZIP_LOCATION, "rb") as action_zip:
            action_bin = action_zip.read()
        self.cf_client.create_action(self.package, action_name, docker_image_name, code=action_bin,
                                     memory=memory, is_binary=True, timeout=timeout * 1000)

        self._delete_function_handler_zip()

        runtime_meta = self._generate_runtime_meta(docker_image_name, memory)

        return runtime_meta

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()
        action_name = self._format_function_name(docker_image_name, memory)
        self.cf_client.delete_action(self.package, action_name)

    def clean(self):
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
            action_image_name, memory = self._unformat_function_name(action['name'])
            if docker_image_name == action_image_name or docker_image_name == 'all':
                runtimes.append((action_image_name, memory))
        return runtimes

    def invoke(self, docker_image_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        action_name = self._format_function_name(docker_image_name, runtime_memory)

        activation_id = self.cf_client.invoke(package=self.package,
                                              action_name=action_name,
                                              payload=payload,
                                              is_ow_action=self.is_lithops_worker)

        if activation_id == 401:
            # unauthorized. Probably token expired if using IAM auth
            if self.iam_api_key and not self.is_lithops_worker:
                invoke_mutex.acquire()
                token, token_expiry_time = self.ibm_token_manager.get_token()
                if token != self.config['token']:
                    self.config['token'] = token
                    self.config['token_expiry_time'] = token_expiry_time
                    auth = 'Bearer ' + token
                    self.cf_client = OpenWhiskClient(endpoint=self.endpoint,
                                                     namespace=self.namespace_id,
                                                     auth=auth,
                                                     user_agent=self.user_agent)
                invoke_mutex.release()
                return self.invoke(docker_image_name, runtime_memory, payload)
            else:
                raise Exception('Unauthorized. Review your API key')

        elif activation_id == 404:
            # Runtime not deployed
            if self.invoke_error is None:
                self.invoke_error = 404

            invoke_mutex.acquire()
            if self.invoke_error == 404:
                logger.debug('Runtime not found')
                self.deploy_runtime(docker_image_name, runtime_memory,
                                    self.config['runtime_timeout'])
                self.invoke_error = None
            invoke_mutex.release()
            return self.invoke(docker_image_name, runtime_memory, payload)

        return activation_id

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_function_name(docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.name, self.region, self.namespace, action_name)

        return runtime_key

    def _generate_runtime_meta(self, docker_image_name, memory):
        """
        Extract installed Python modules from the docker image
        """
        logger.debug("Extracting Python modules list from: {}".format(docker_image_name))
        action_name = self._format_function_name(docker_image_name, memory)
        payload = {'log_level': logger.getEffectiveLevel(), 'get_preinstalls': True}
        try:
            retry_invoke = True
            while retry_invoke:
                retry_invoke = False
                runtime_meta = self.cf_client.invoke_with_result(self.package, action_name, payload)
                if 'activationId' in runtime_meta:
                    retry_invoke = True
        except Exception as e:
            raise ("Unable to extract runtime preinstalls: {}".format(e))

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta

    def calc_cost(self, runtimes, memory, *argv, **arg):
        """ returns total cost associated with executing the calling function-executor's job.
        :params *argv and **arg: made to support compatibility with similarly named functions in
        alternative computational backends.
        """
        return ibmcf_config.UNIT_PRICE * sum(runtimes[i] * memory[i] / 1024 for i in range(len(runtimes)))
