import os
import logging
import time
from pywren_ibm_cloud.compute import InternalCompute
from pywren_ibm_cloud import wrenconfig
from concurrent.futures import ThreadPoolExecutor
from pywren_ibm_cloud.future import ResponseFuture, JobState
from pywren_ibm_cloud.storage.storage_utils import create_keys
from pywren_ibm_cloud.version import __version__

logger = logging.getLogger(__name__)


class Invoker:

    def __init__(self, config, internal_storage, executor_id):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.config = config
        self.internal_storage = internal_storage
        self.executor_id = executor_id

        compute_config = wrenconfig.extract_compute_config(self.config)
        self.internal_compute = InternalCompute(compute_config, internal_storage)

    def run(self, job_description):

        runtime_name = job_description['runtime_name']
        runtime_memory = job_description['runtime_memory']
        runtime_timeout = job_description['runtime_timeout']
        func_name = job_description['func_name']
        func_key = job_description['func_key']
        extra_env = job_description['extra_env']
        extra_meta = job_description['extra_meta']
        total_data_items = job_description['total_data_items']
        invoke_pool_threads = job_description['invoke_pool_threads']
        overwrite_invoke_args = job_description['overwrite_invoke_args']
        data_key = job_description['data_key']
        data_ranges = job_description['data_ranges']
        host_job_meta = job_description['host_job_meta']
        callgroup_id = job_description['callgroup_id']
        remote_invocation = job_description['remote_invocation']
        original_iterdata_len = job_description['original_iterdata_len']

        if remote_invocation and original_iterdata_len > 1:
            log_msg = 'ExecutorID {} - Starting {} remote invocation function: Spawning {}() - Total: {} activations'.format(self.executor_id, total_data_items, func_name,
                                                                                                                             original_iterdata_len)
        else:
            log_msg = 'ExecutorID {} - Starting function invocation: {}() - Total: {} activations'.format(self.executor_id, func_name, total_data_items)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

        ########################

        def invoke(executor_id, callgroup_id, call_id, func_key, host_job_meta, data_key, data_byte_range):

            output_key, status_key = create_keys(self.internal_storage.prefix, executor_id, callgroup_id, call_id)
            payload = {
                'config': self.config,
                'log_level': self.log_level,
                'func_key': func_key,
                'data_key': data_key,
                'output_key': output_key,
                'status_key': status_key,
                'job_max_runtime': runtime_timeout,
                'data_byte_range': data_byte_range,
                'executor_id': executor_id,
                'callgroup_id': callgroup_id,
                'call_id': call_id,
                'pywren_version': __version__}

            if extra_env is not None:
                logger.debug("Extra environment vars {}".format(extra_env))
                payload['extra_env'] = extra_env

            if extra_meta is not None:
                # sanity
                for k, v in extra_meta.items():
                    if k in payload:
                        raise ValueError("Key {} already in dict".format(k))
                    payload[k] = v

            # overwrite explicit args, mostly used for testing via injection
            if overwrite_invoke_args is not None:
                payload.update(overwrite_invoke_args)

            host_submit_time = time.time()
            payload['host_submit_time'] = host_submit_time
            # do the invocation
            activation_id = self.internal_compute.invoke(runtime_name, runtime_memory, payload)

            if not activation_id:
                raise Exception("ExecutorID {} - Activation {} failed, therefore job is failed".format(executor_id, call_id))

            host_job_meta['activation_id'] = activation_id
            host_job_meta['invoke_time'] = time.time() - host_submit_time

            host_job_meta.update(payload)
            del host_job_meta['config']

            storage_config = self.internal_storage.get_storage_config()
            fut = ResponseFuture(call_id, callgroup_id, executor_id, activation_id, host_job_meta, storage_config)
            fut._set_state(JobState.invoked)

            return fut

        ########################

        call_futures = []
        with ThreadPoolExecutor(max_workers=invoke_pool_threads) as executor:
            for i in range(total_data_items):
                call_id = "{:05d}".format(i)
                data_byte_range = data_ranges[i]
                future = executor.submit(invoke, self.executor_id,
                                         callgroup_id, call_id, func_key,
                                         host_job_meta.copy(),
                                         data_key, data_byte_range)
                call_futures.append(future)

        res = [ft.result() for ft in call_futures]

        return res
