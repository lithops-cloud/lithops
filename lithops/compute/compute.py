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
from lithops.compute.utils import get_remote_client

logger = logging.getLogger(__name__)


class Compute:
    """
    A Compute object is used by invokers and other components to access
    underlying compute backend without exposing the implementation details.
    """

    def __init__(self, compute_config, storage_config):
        self.config = compute_config
        self.backend = self.config['backend']
        self.compute_handler = None

        try:
            module_location = 'lithops.compute.backends.{}'.format(self.backend)
            cb_module = importlib.import_module(module_location)
            ComputeBackend = getattr(cb_module, 'ComputeBackend')
            self.compute_handler = ComputeBackend(self.config[self.backend], storage_config)
            self.remote_client = get_remote_client(self.config)

            # if backend supports, check if ready. run client to setup in case not ready
            self._setup_compute()

        except Exception as e:
            logger.error("There was en error trying to create the '{}' compute backend".format(e))
            raise e

    def _setup_compute(self):
        logger.info("Starting setup of compute backend")
        readiness_probe = None
        if hasattr(self.compute_handler, 'ready'):
            readiness_probe = self.compute_handler.ready

        if self.remote_client:
            self.remote_client.setup(readiness_probe=readiness_probe)

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

        """
        Compute engine may need to perform cleanup for completed invocations
        """
    def cleanup(self, activation_id):
        return self.compute_handler.cleanup(activation_id)

    def dismantle(self):
        if self.remote_client:
            logger.info("Dismantling setup")
            self.remote_client.dismantle()

    def __del__(self):
        if self.compute_handler and hasattr(self.compute_handler, '__del__'):
            self.compute_handler.__del__()
