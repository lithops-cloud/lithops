#
# Copyright 2018 PyWren Team
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
import time
import logging
import random
from types import SimpleNamespace
from pywren_ibm_cloud.compute import Compute
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.version import __version__
from concurrent.futures import ThreadPoolExecutor
from pywren_ibm_cloud.config import extract_storage_config, extract_compute_config
from pywren_ibm_cloud.future import ResponseFuture
from pywren_ibm_cloud.storage.utils import create_output_key, create_status_key

logger = logging.getLogger(__name__)


class FunctionInvoker:
    """
    Module responsible to perform the invocations against the compute backend
    """

    def __init__(self, pywren_config, executor_id, internal_storage):
        self.log_level = os.getenv('PYWREN_LOGLEVEL')
        self.pywren_config = pywren_config
        self.executor_id = executor_id
        self.storage_config = extract_storage_config(self.pywren_config)
        self.internal_storage = internal_storage
        self.compute_config = extract_compute_config(self.pywren_config)

        self.compute_handlers = []
        cb = self.compute_config['backend']
        regions = self.compute_config[cb].get('region')
        if regions and type(regions) == list:
            for region in regions:
                compute_config = self.compute_config.copy()
                compute_config[cb]['region'] = region
                self.compute_handlers.append(Compute(compute_config))
        else:
            self.compute_handlers.append(Compute(self.compute_config))

    def select_runtime(self, job_id, runtime_memory):
        """
        Auxiliary method that selects the runtime to use. To do so it gets the
        runtime metadata from the storage. This metadata contains the preinstalled
        python modules needed to serialize the local function. If the .metadata
        file does not exists in the storage, this means that the runtime is not
        installed, so this method will proceed to install it.
        """
        log_level = os.getenv('PYWREN_LOGLEVEL')
        runtime_name = self.pywren_config['pywren']['runtime']
        if runtime_memory is None:
            runtime_memory = self.pywren_config['pywren']['runtime_memory']
        runtime_memory = int(runtime_memory)

        log_msg = ('ExecutorID {} | JobID {} - Selected Runtime: {} - {}MB'
                   .format(self.executor_id, job_id, runtime_name, runtime_memory))
        logger.info(log_msg)
        if not log_level:
            print(log_msg, end=' ')
        installing = False

        for compute_handler in self.compute_handlers:
            runtime_key = compute_handler.get_runtime_key(runtime_name, runtime_memory)
            runtime_deployed = True
            try:
                runtime_meta = self.internal_storage.get_runtime_meta(runtime_key)
            except Exception:
                runtime_deployed = False

            if not runtime_deployed:
                logger.debug('ExecutorID {} | JobID {} - Runtime {} with {}MB is not yet '
                             'installed'.format(self.executor_id, job_id, runtime_name, runtime_memory))
                if not log_level and not installing:
                    installing = True
                    print('(Installing...)')

                timeout = self.pywren_config['pywren']['runtime_timeout']
                logger.debug('Creating runtime: {}, memory: {}MB'.format(runtime_name, runtime_memory))
                runtime_meta = compute_handler.create_runtime(runtime_name, runtime_memory, timeout=timeout)
                self.internal_storage.put_runtime_meta(runtime_key, runtime_meta)

            py_local_version = version_str(sys.version_info)
            py_remote_version = runtime_meta['python_ver']

            if py_local_version != py_remote_version:
                raise Exception(("The indicated runtime '{}' is running Python {} and it "
                                 "is not compatible with the local Python version {}")
                                .format(runtime_name, py_remote_version, py_local_version))

        if not log_level and runtime_deployed:
            print()

        return runtime_meta

    def run(self, job_description):
        """
        Run a job described in job_description
        """
        job = SimpleNamespace(**job_description)

        if job.remote_invocation:
            log_msg = ('ExecutorID {} | JobID {} - Starting {} remote invocation function: Spawning {}() '
                       '- Total: {} activations'.format(self.executor_id, job.job_id, job.total_calls,
                                                        job.func_name, job.original_total_calls))
        else:
            log_msg = ('ExecutorID {} | JobID {} - Starting function invocation: {}()  - Total: {} '
                       'activations'.format(self.executor_id, job.job_id, job.func_name, job.total_calls))
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

        ########################

        def invoke(executor_id, job_id, call_id, func_key, job_metadata, data_key, data_byte_range):

            output_key = create_output_key(self.storage_config['prefix'], executor_id, job_id, call_id)
            status_key = create_status_key(self.storage_config['prefix'], executor_id, job_id, call_id)

            payload = {'config': self.pywren_config,
                       'log_level': self.log_level,
                       'func_key': func_key,
                       'data_key': data_key,
                       'output_key': output_key,
                       'status_key': status_key,
                       'extra_env': job.extra_env,
                       'execution_timeout': job.execution_timeout,
                       'data_byte_range': data_byte_range,
                       'executor_id': executor_id,
                       'job_id': job_id,
                       'call_id': call_id,
                       'host_submit_time': time.time(),
                       'pywren_version': __version__}

            # do the invocation
            compute_handler = random.choice(self.compute_handlers)
            activation_id = compute_handler.invoke(job.runtime_name, job.runtime_memory, payload)

            if not activation_id:
                raise Exception("ExecutorID {} | JobID {} - Retrying mechanism finished with no success. "
                                "Failed to invoke the job".format(executor_id, job_id))

            job_metadata['activation_id'] = activation_id
            fut = ResponseFuture(executor_id, job_id, call_id, self.storage_config, job_metadata)
            fut._set_state(ResponseFuture.State.Invoked)

            return fut

        ########################

        call_futures = []
        with ThreadPoolExecutor(max_workers=job.invoke_pool_threads) as executor:
            for i in range(job.total_calls):
                call_id = "{:05d}".format(i)
                data_byte_range = job.data_ranges[i]
                future = executor.submit(invoke, self.executor_id,
                                         job.job_id, call_id, job.func_key,
                                         job.metadata.copy(),
                                         job.data_key, data_byte_range)
                call_futures.append(future)

        res = [ft.result() for ft in call_futures]

        return res
