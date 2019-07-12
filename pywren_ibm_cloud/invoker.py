import os
import logging
import time
from types import SimpleNamespace
from pywren_ibm_cloud import wrenconfig
from pywren_ibm_cloud.version import __version__
from concurrent.futures import ThreadPoolExecutor
from pywren_ibm_cloud.compute import Compute
from pywren_ibm_cloud.future import ResponseFuture, JobState
from pywren_ibm_cloud.wrenconfig import extract_storage_config
from pywren_ibm_cloud.storage.storage_utils import create_output_key, create_status_key

logger = logging.getLogger(__name__)


class Invoker:

    def __init__(self, config, executor_id):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.config = config
        self.executor_id = executor_id

        compute_config = wrenconfig.extract_compute_config(self.config)
        self.internal_compute = Compute(compute_config)

    def run(self, job_description):
        job = SimpleNamespace(**job_description)
        storage_config = extract_storage_config(self.config)

        if job.remote_invocation:
            log_msg = ('ExecutorID {} - Starting {} remote invocation function: Spawning {}() '
                       '- Total: {} activations'.format(self.executor_id, job.total_data_items,
                                                        job.func_name, job.original_iterdata_len))
        else:
            log_msg = ('ExecutorID {} - Starting function invocation: {}() - Total: {} '
                       'activations'.format(self.executor_id, job.func_name, job.total_data_items))
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

        ########################

        def invoke(executor_id, callgroup_id, call_id, func_key, invoke_metadata, data_key, data_byte_range):

            output_key = create_output_key(storage_config['storage_prefix'], executor_id, callgroup_id, call_id)
            status_key = create_status_key(storage_config['storage_prefix'], executor_id, callgroup_id, call_id)

            payload = {
                'config': self.config,
                'log_level': self.log_level,
                'func_key': func_key,
                'data_key': data_key,
                'output_key': output_key,
                'status_key': status_key,
                'job_max_runtime': job.runtime_timeout,
                'data_byte_range': data_byte_range,
                'executor_id': executor_id,
                'callgroup_id': callgroup_id,
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
                raise Exception("ExecutorID {} - Activation {} failed, therefore job is failed".format(executor_id, call_id))

            invoke_metadata['activation_id'] = activation_id
            invoke_metadata['invoke_time'] = time.time() - host_submit_time

            invoke_metadata.update(payload)
            del invoke_metadata['config']

            fut = ResponseFuture(call_id, callgroup_id, executor_id, activation_id, storage_config, invoke_metadata)
            fut._set_state(JobState.invoked)

            return fut

        ########################

        call_futures = []
        with ThreadPoolExecutor(max_workers=job.invoke_pool_threads) as executor:
            for i in range(job.total_data_items):
                call_id = "{:05d}".format(i)
                data_byte_range = job.data_ranges[i]
                future = executor.submit(invoke, self.executor_id,
                                         job.callgroup_id, call_id, job.func_key,
                                         job.host_job_meta.copy(),
                                         job.data_key, data_byte_range)
                call_futures.append(future)

        res = [ft.result() for ft in call_futures]

        return res
