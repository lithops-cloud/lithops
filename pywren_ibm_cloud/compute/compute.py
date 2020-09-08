#
# (C) Copyright IBM Corp. 2018
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

import logging
import importlib

logger = logging.getLogger(__name__)


class Compute:
    """
    A Compute object is used by invokers and other components to access
    underlying compute backend without exposing the implementation details.
    """

    def __init__(self, compute_config):
        self.config = compute_config
        self.backend = self.config['backend']
        self.compute_handler = None

        try:
            module_location = 'pywren_ibm_cloud.compute.backends.{}'.format(self.backend)
            cb_module = importlib.import_module(module_location)
            ComputeBackend = getattr(cb_module, 'ComputeBackend')
            self.compute_handler = ComputeBackend(self.config[self.backend])
            self.remote_client = self._get_remote_client(self.config[self.backend])

            # if backend supports, check if ready. run client to setup in case not ready
            if self.remote_client and \
               hasattr(self.compute_handler, 'ready') and \
               not self.compute_handler.ready():
                self._setup_compute()
                self.remote_client.create_instance_action('start')

        except Exception as e:
            logger.error("There was en error trying to create the '{}' compute backend".format(e))
            raise e

    def _setup_compute(self):
        logger.info("Starting setup of compute backend")
        self.remote_client.create_instance_action('start')
        logger.info("Waiting for compute to become ready")
        if not self.compute_handler.ready(retries=10, timeout=20):
            raise Exception("The remote compute is not ready")

    def _get_remote_client(self, backend_config):
        if 'remote_client' in backend_config:
            remote_client_backend = backend_config['remote_client']
            client_location = 'pywren_ibm_cloud.libs.clients.{}'.format(remote_client_backend)
            client = importlib.import_module(client_location)
            RemoteInstanceClient = getattr(client, 'RemoteInstanceClient')
            return RemoteInstanceClient(backend_config[remote_client_backend],
                                                       user_agent=backend_config['user_agent'])
        return None

    def invoke(self, runtime_name, memory, payload):
        """
        Invoke -- return information about this invocation
        """
        return self.compute_handler.invoke(runtime_name, memory, payload)

    def build_runtime(self, runtime_name, file):
        """
        Wrapper method to build a new runtime for the compute backend.
        return: the name of the runtime
        """
        self.compute_handler.build_runtime(runtime_name, file)

    def create_runtime(self, runtime_name, memory, timeout):
        """
        Wrapper method to create a runtime in the compute backend.
        return: the name of the runtime
        """
        return self.compute_handler.create_runtime(runtime_name, memory, timeout=timeout)

    def delete_runtime(self, runtime_name, memory):
        """
        Wrapper method to create a runtime in the compute backend
        """
        self.compute_handler.delete_runtime(runtime_name, memory)

    def delete_all_runtimes(self):
        """
        Wrapper method to create a runtime in the compute backend
        """
        self.compute_handler.delete_all_runtimes()

    def list_runtimes(self, runtime_name='all'):
        """
        Wrapper method to list deployed runtime in the compute backend
        """
        return self.compute_handler.list_runtimes(runtime_name)

    def get_runtime_key(self, runtime_name, memory):
        """
        Wrapper method that returns a formated string that represents the runtime key.
        Each backend has its own runtime key format. Used to store modules preinstalls
        into the storage
        """
        return self.compute_handler.get_runtime_key(runtime_name, memory)

    def dismantle(self):
        if self.remote_client:
            logger.debug("Dismantling setup")
            self.remote_client.create_instance_action('stop')

    def __del__(self):
        if self.compute_handler and hasattr(self.compute_handler, '__del__'):
            self.compute_handler.__del__()
