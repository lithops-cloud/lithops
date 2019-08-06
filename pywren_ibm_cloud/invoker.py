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
import logging
import time
from types import SimpleNamespace
from pywren_ibm_cloud.version import __version__
from concurrent.futures import ThreadPoolExecutor
from pywren_ibm_cloud.compute import Compute
from pywren_ibm_cloud.future import ResponseFuture, CallState
from pywren_ibm_cloud.config import extract_storage_config, extract_compute_config
from pywren_ibm_cloud.storage.utils import create_output_key, create_status_key

logger = logging.getLogger(__name__)


class Invoker:

    def __init__(self, config, executor_id):
        self.log_level = os.getenv('CB_LOG_LEVEL')
        self.config = config
        self.executor_id = executor_id
        self.storage_config = extract_storage_config(self.config)
        compute_config = extract_compute_config(config)
        self.internal_compute = Compute(compute_config)

    def run(self, job_description):
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

        def invoke(executor_id, job_id, call_id, func_key, invoke_metadata, data_key, data_byte_range):

            output_key = create_output_key(self.storage_config['prefix'], executor_id, job_id, call_id)
            status_key = create_status_key(self.storage_config['prefix'], executor_id, job_id, call_id)

            payload = {
                'config': self.config,
                'log_level': self.log_level,
                'func_key': func_key,
                'data_key': data_key,
                'output_key': output_key,
                'status_key': status_key,
                'execution_timeout': job.execution_timeout,
                'data_byte_range': data_byte_range,
                'executor_id': executor_id,
                'job_id': job_id,
                'call_id': call_id,
                'pywren_version': __version__}

            if job.extra_env is not None:
                logger.debug("Extra environment vars {}".format(job.extra_env))
                payload['extra_env'] = job.extra_env

            if job.extra_meta is not None:
                # sanity
                for k, v in job.extra_meta.items():
                    if k in payload:
                        raise ValueError("Key {} already in dict".format(k))
                    payload[k] = v

            # overwrite explicit args, mostly used for testing via injection
            if job.overwrite_invoke_args is not None:
                payload.update(job.overwrite_invoke_args)

            host_submit_time = time.time()
            payload['host_submit_time'] = host_submit_time
            # do the invocation
            activation_id = self.internal_compute.invoke(job.runtime_name, job.runtime_memory, payload)

            if not activation_id:
                raise Exception("ExecutorID {} | JobID {} - Retrying mechanism finished with no success. "
                                "Failed to invoke the job".format(executor_id, job_id))

            invoke_metadata['activation_id'] = activation_id
            invoke_metadata['invoke_time'] = time.time() - host_submit_time

            invoke_metadata.update(payload)
            del invoke_metadata['config']

            fut = ResponseFuture(call_id, job_id, executor_id, activation_id, self.storage_config, invoke_metadata)
            fut._set_state(CallState.invoked)

            return fut

        ########################

        call_futures = []
        with ThreadPoolExecutor(max_workers=job.invoke_pool_threads) as executor:
            for i in range(job.total_calls):
                call_id = "{:05d}".format(i)
                data_byte_range = job.data_ranges[i]
                future = executor.submit(invoke, self.executor_id,
                                         job.job_id, call_id, job.func_key,
                                         job.host_job_meta.copy(),
                                         job.data_key, data_byte_range)
                call_futures.append(future)

        res = [ft.result() for ft in call_futures]

        return res
