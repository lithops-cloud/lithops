#
# (C) Copyright IBM Corp. 2018
# (C) Copyright Cloudlab URV 2020
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
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ServerlessHandler:
    """
    A ServerlessHandler object is used by invokers and other components to
    access the underlying serverless backend without exposing implementation
    details.
    """

    def __init__(self, serverless_config: Dict[str, Any], internal_storage):
        self.config = serverless_config
        self.backend_name = self.config['backend']
        self.backend = self._load_backend(internal_storage)

    def _load_backend(self, internal_storage):
        """Builds the backend the configuration asks for"""
        try:
            module_location = f'lithops.serverless.backends.{self.backend_name}'
            sb_module = importlib.import_module(module_location)
            serverless_backend_cls = getattr(sb_module, 'ServerlessBackend')
            return serverless_backend_cls(
                self.config[self.backend_name], internal_storage
            )
        except Exception:
            logger.error(
                f"There was an error trying to create the {self.backend_name} "
                "serverless backend",
                exc_info=True,
            )
            raise

    def _call_backend(self, method: str, *args):
        """
        Calls an optional backend method, so that a backend only implements
        the hooks it needs
        """
        fn = getattr(self.backend, method, None)
        if fn is not None:
            return fn(*args)
        return None

    def init(self):
        """Nothing to initialize: serverless backends are ready to invoke"""

    def pre_invoke(self, job):
        """Runs the pre-invoke hook of the backend, if it has one"""
        self._call_backend('pre_invoke', job.runtime_name, job.runtime_memory)

    def invoke(self, job_payload: Dict[str, Any]):
        """Invokes a job, and returns the activation id of the invocation"""
        return self.backend.invoke(
            job_payload['runtime_name'],
            job_payload['runtime_memory'],
            job_payload,
        )

    def build_runtime(self, runtime_name: str, file: str, extra_args=None):
        """Builds the runtime image the jobs will run in"""
        self.backend.build_runtime(runtime_name, file, extra_args or [])

    def deploy_runtime(self, runtime_name: str, memory: int, timeout: int):
        """Deploys a runtime and returns its metadata"""
        return self.backend.deploy_runtime(
            runtime_name, memory, timeout=timeout
        )

    def delete_runtime(self, runtime_name: str, memory: int, version: str):
        """Deletes a deployed runtime"""
        self.backend.delete_runtime(runtime_name, memory, version)

    def clean(self, **kwargs):
        """Deletes every runtime and every resource the backend created"""
        self.backend.clean(**kwargs)

    def clear(self, job_keys=None, exception=None):
        """
        Releases the backend resources of the given jobs, for the backends
        that hold any
        """
        self._call_backend('clear', job_keys)

    def list_runtimes(self, runtime_name: str = 'all'):
        """Lists the runtimes deployed in the backend"""
        return self.backend.list_runtimes(runtime_name)

    def get_runtime_key(self, runtime_name: str, memory: int, version: str):
        """
        Returns a formatted string that represents the runtime key.
        Each backend has its own runtime key format. Used to store
        runtime metadata in storage.
        """
        return self.backend.get_runtime_key(runtime_name, memory, version)

    def get_runtime_info(self):
        """Returns the runtime limits the executor reports to the user"""
        return self.backend.get_runtime_info()

    def get_backend_type(self):
        """Returns whether the backend is invoked per call or with a job"""
        return self.backend.type
