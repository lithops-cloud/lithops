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
import time
import pickle
import logging
import inspect
import pywren_ibm_cloud as pywren
import pywren_ibm_cloud.version as version
import pywren_ibm_cloud.utils as wrenutil
import pywren_ibm_cloud.wrenconfig as wrenconfig
from pywren_ibm_cloud.wait import wait
from concurrent.futures import ThreadPoolExecutor
from pywren_ibm_cloud.future import ResponseFuture, JobState
from pywren_ibm_cloud.runtime import get_runtime_preinstalls
from pywren_ibm_cloud.storage.backends.cos import COSBackend
from pywren_ibm_cloud.serialize import serialize, create_mod_data
from pywren_ibm_cloud.storage.storage_utils import create_keys, create_func_key, create_agg_data_key
from pywren_ibm_cloud.partitioner import create_partitions, partition_processor


logger = logging.getLogger(__name__)


class Executor(object):

    def __init__(self, invoker, config, internal_storage):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.invoker = invoker
        self.config = config
        self.internal_storage = internal_storage

        self.runtime_name = self.config['pywren']['runtime']
        self.runtime_memory = self.config['pywren']['runtime_memory']
        runtime_preinstalls = get_runtime_preinstalls(self.internal_storage,
                                                      self.runtime_name,
                                                      self.runtime_memory,
                                                      self.config)
        self.serializer = serialize.SerializeIndependent(runtime_preinstalls)

        self.map_item_limit = None
        if 'scheduler' in self.config:
            if 'map_item_limit' in config['scheduler']:
                self.map_item_limit = config['scheduler']['map_item_limit']

        if 'PYWREN_EXECUTOR_ID' in os.environ:
            self.executor_id = os.environ['PYWREN_EXECUTOR_ID']
        else:
            self.executor_id = wrenutil.create_executor_id()

        log_msg = 'IBM Cloud Functions executor created with ID {}'.format(self.executor_id)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

    def invoke_with_keys(self, func_key, data_key, output_key,
                         status_key, executor_id, callgroup_id,
                         call_id, extra_env,
                         extra_meta, data_byte_range,
                         host_job_meta, job_max_runtime,
                         overwrite_invoke_args=None):

        log_level = 'INFO' if not self.log_level else self.log_level

        arg_dict = {
            'config': self.config,
            'log_level': log_level,
            'func_key': func_key,
            'data_key': data_key,
            'output_key': output_key,
            'status_key': status_key,
            'job_max_runtime': job_max_runtime,
            'data_byte_range': data_byte_range,
            'executor_id': executor_id,
            'callgroup_id': callgroup_id,
            'call_id': call_id,
            'pywren_version': version.__version__}

        if extra_env is not None:
            logger.debug("Extra environment vars {}".format(extra_env))
            arg_dict['extra_env'] = extra_env

        if extra_meta is not None:
            # sanity
            for k, v in extra_meta.items():
                if k in arg_dict:
                    raise ValueError("Key {} already in dict".format(k))
                arg_dict[k] = v

        host_submit_time = time.time()
        arg_dict['host_submit_time'] = host_submit_time

        # logger.debug("Executor ID {} Activation {} invoke".format(executor_id, call_id))

        # overwrite explicit args, mostly used for testing via injection
        if overwrite_invoke_args is not None:
            arg_dict.update(overwrite_invoke_args)

        cf_invoke_time_start = time.time()
        # do the invocation
        activation_id = self.invoker.invoke(arg_dict)

        if not activation_id:
            raise ValueError("Executor ID {} Activation {} failed, therefore job is failed".format(executor_id, call_id))

        host_job_meta['cf_activation_id'] = activation_id
        host_job_meta['cf_invoke_timestamp'] = cf_invoke_time_start
        host_job_meta['cf_invoke_time'] = time.time() - cf_invoke_time_start

        # logger.debug("Executor ID {} Activation {} complete".format(executor_id, call_id))

        host_job_meta.update(self.invoker.config())
        host_job_meta.update(arg_dict)
        del host_job_meta['config']
        storage_config = self.internal_storage.get_storage_config()
        fut = ResponseFuture(call_id, callgroup_id, executor_id, activation_id, host_job_meta, storage_config)
        fut._set_state(JobState.invoked)

        return fut

    @staticmethod
    def agg_data(data_strs):
        ranges = []
        pos = 0
        for datum in data_strs:
            datum_len = len(datum)
            ranges.append((pos, pos+datum_len-1))
            pos += datum_len
        return b"".join(data_strs), ranges

    def call_async(self, func, data, extra_env=None, extra_meta=None, runtime_timeout=wrenconfig.RUNTIME_TIMEOUT):
        """
        Wrapper to launch one function invocation.
        """

        return self._map(func, [data], extra_env=extra_env, extra_meta=extra_meta, job_max_runtime=runtime_timeout)

    def map(self, map_function, iterdata, obj_chunk_size=None, extra_env=None, extra_meta=None,
            remote_invocation=False, remote_invocation_groups=None, invoke_pool_threads=128,
            data_all_as_one=True, job_max_runtime=wrenconfig.RUNTIME_TIMEOUT,
            overwrite_invoke_args=None, exclude_modules=None):
        """
        Wrapper to launch map() method.  It integrates COS logic to process objects.
        """
        data = wrenutil.iterdata_as_list(iterdata)
        map_func = map_function
        map_iterdata = data
        new_invoke_pool_threads = invoke_pool_threads
        parts_per_object = None

        if wrenutil.is_object_processing(map_function):
            '''
            If it is object processing function, create partitions according chunk_size
            '''
            logger.debug("Calling map on partitions from object storage flow")
            arg_data = wrenutil.verify_args(map_function, data, object_processing=True)
            storage = COSBackend(self.config['ibm_cos'])
            map_iterdata, parts_per_object = create_partitions(arg_data, obj_chunk_size, storage)
            map_func = partition_processor(map_function)

        # Remote invocation functionality
        original_iterdata_len = len(iterdata)
        if original_iterdata_len > 1 and remote_invocation:
            runtime_name = self.runtime_name
            runtime_memory = self.runtime_memory
            rabbitmq_monitor = "PYWREN_RABBITMQ_MONITOR" in os.environ

            def remote_invoker(input_data):
                pw = pywren.ibm_cf_executor(runtime=runtime_name,
                                            runtime_memory=runtime_memory,
                                            rabbitmq_monitor=rabbitmq_monitor)
                return pw.map(map_function, input_data,
                              invoke_pool_threads=invoke_pool_threads,
                              extra_env=extra_env,
                              extra_meta=extra_meta)

            map_func = remote_invoker
            if remote_invocation_groups:
                map_iterdata = [[iterdata[x:x+remote_invocation_groups]]
                                for x in range(0, original_iterdata_len, remote_invocation_groups)]
            else:
                map_iterdata = [iterdata]
            new_invoke_pool_threads = 1

        map_futures = self._map(map_func, map_iterdata,
                                extra_env=extra_env,
                                extra_meta=extra_meta,
                                invoke_pool_threads=new_invoke_pool_threads,
                                data_all_as_one=data_all_as_one,
                                overwrite_invoke_args=overwrite_invoke_args,
                                exclude_modules=exclude_modules,
                                original_func_name=map_function.__name__,
                                remote_invocation=remote_invocation,
                                original_iterdata_len=original_iterdata_len,
                                job_max_runtime=job_max_runtime)

        return map_futures, parts_per_object

    def _map(self, func, iterdata, extra_env=None, extra_meta=None, invoke_pool_threads=128,
             data_all_as_one=True, overwrite_invoke_args=None, exclude_modules=None,
             original_func_name=None, remote_invocation=False, original_iterdata_len=None,
             job_max_runtime=wrenconfig.RUNTIME_TIMEOUT):
        """
        :param func: the function to map over the data
        :param iterdata: An iterable of input data
        :param extra_env: Additional environment variables for CF environment. Default None.
        :param extra_meta: Additional metadata to pass to CF. Default None.
        :param remote_invocation: Enable remote invocation. Default False.
        :param invoke_pool_threads: Number of threads to use to invoke.
        :param data_all_as_one: upload the data as a single object. Default True
        :param overwrite_invoke_args: Overwrite other args. Mainly used for testing.
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.
        :param original_func_name: Name of the function to invoke.
        :return: A list with size `len(iterdata)` of futures for each job
        :rtype:  list of futures.
        """
        if original_func_name:
            func_name = original_func_name
        else:
            func_name = func.__name__

        data = wrenutil.iterdata_as_list(iterdata)

        if extra_env is not None:
            extra_env = wrenutil.convert_bools_to_string(extra_env)

        if not data:
            return []

        if self.map_item_limit is not None and len(data) > self.map_item_limit:
            raise ValueError("len(data) ={}, exceeding map item limit of {}"
                             "consider mapping over a smaller"
                             "number of items".format(len(data),
                                                      self.map_item_limit))

        # This allows multiple parameters in functions
        data = wrenutil.verify_args(func, data)

        callgroup_id = wrenutil.create_callgroup_id()

        host_job_meta = {}

        log_msg = 'Executor ID {} Serializing function and data'.format(self.executor_id)
        logger.debug(log_msg)
        # pickle func and all data (to capture module dependencies)
        func_and_data_ser, mod_paths = self.serializer([func] + data)

        func_str = func_and_data_ser[0]
        data_strs = func_and_data_ser[1:]
        data_size_bytes = sum(len(x) for x in data_strs)

        agg_data_key = None
        host_job_meta['agg_data'] = False
        host_job_meta['data_size_bytes'] = data_size_bytes

        log_msg = 'Executor ID {} Uploading function and data'.format(self.executor_id)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg, end=' ')

        if data_size_bytes < wrenconfig.MAX_AGG_DATA_SIZE and data_all_as_one:
            agg_data_key = create_agg_data_key(self.internal_storage.prefix, self.executor_id, callgroup_id)
            agg_data_bytes, agg_data_ranges = self.agg_data(data_strs)
            agg_upload_time = time.time()
            self.internal_storage.put_data(agg_data_key, agg_data_bytes)
            host_job_meta['agg_data'] = True
            host_job_meta['data_upload_time'] = time.time() - agg_upload_time
            host_job_meta['data_upload_timestamp'] = time.time()
        else:
            log_msg = ('Executor ID {} Total data exceeded '
                       'maximum size of {} bytes'.format(self.executor_id,
                                                         wrenconfig.MAX_AGG_DATA_SIZE))
            logger.warning(log_msg)

        if exclude_modules:
            for module in exclude_modules:
                for mod_path in list(mod_paths):
                    if module in mod_path and mod_path in mod_paths:
                        mod_paths.remove(mod_path)

        module_data = create_mod_data(mod_paths)
        # Create func and upload
        func_module_str = pickle.dumps({'func': func_str, 'module_data': module_data}, -1)
        host_job_meta['func_module_bytes'] = len(func_module_str)

        func_upload_time = time.time()
        func_key = create_func_key(self.internal_storage.prefix, self.executor_id, callgroup_id)
        self.internal_storage.put_func(func_key, func_module_str)
        host_job_meta['func_upload_time'] = time.time() - func_upload_time
        host_job_meta['func_upload_timestamp'] = time.time()

        if not self.log_level:
            func_and_data_size = wrenutil.sizeof_fmt(host_job_meta['func_module_bytes']+host_job_meta['data_size_bytes'])
            log_msg = '- Total: {}'.format(func_and_data_size)
            print(log_msg)

        def invoke(data_str, executor_id, callgroup_id, call_id, func_key,
                   host_job_meta, agg_data_key=None, data_byte_range=None):
            data_key, output_key, status_key = create_keys(self.internal_storage.prefix,
                                                           executor_id, callgroup_id, call_id)
            host_job_meta['job_invoke_timestamp'] = time.time()

            if agg_data_key is None:
                data_upload_time = time.time()
                self.internal_storage.put_data(data_key, data_str)
                data_upload_time = time.time() - data_upload_time
                host_job_meta['data_upload_time'] = data_upload_time
                host_job_meta['data_upload_timestamp'] = time.time()

                data_key = data_key
            else:
                data_key = agg_data_key

            return self.invoke_with_keys(func_key, data_key,
                                         output_key, status_key,
                                         executor_id, callgroup_id,
                                         call_id, extra_env,
                                         extra_meta, data_byte_range,
                                         host_job_meta.copy(),
                                         job_max_runtime,
                                         overwrite_invoke_args=overwrite_invoke_args)

        N = len(data)
        call_futures = []
        if remote_invocation and original_iterdata_len > 1:
            log_msg = 'Executor ID {} Starting {} remote invocation function: Spawning {}() - Total: {} activations'.format(self.executor_id, N, func_name,
                                                                                                                            original_iterdata_len)
        else:
            log_msg = 'Executor ID {} Starting function invocation: {}() - Total: {} activations'.format(self.executor_id, func_name, N)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

        with ThreadPoolExecutor(max_workers=invoke_pool_threads) as executor:
            for i in range(N):
                call_id = "{:05d}".format(i)

                data_byte_range = None
                if agg_data_key is not None:
                    data_byte_range = agg_data_ranges[i]

                future = executor.submit(invoke, data_strs[i], self.executor_id,
                                         callgroup_id, call_id, func_key,
                                         host_job_meta.copy(),
                                         agg_data_key,
                                         data_byte_range)

                call_futures.append(future)

        res = [ft.result() for ft in call_futures]

        return res

    def reduce(self, reduce_function, list_of_futures, parts_per_object,
               reducer_one_per_object, extra_env, extra_meta):
        """
        Apply a function across all futures.
        """
        executor_id = self.executor_id
        map_iterdata = [[list_of_futures, ]]

        if parts_per_object and reducer_one_per_object:
            prev_total_partitons = 0
            map_iterdata = []
            for total_partitions in parts_per_object:
                map_iterdata.append([list_of_futures[prev_total_partitons:prev_total_partitons+total_partitions]])
                prev_total_partitons = prev_total_partitons + total_partitions

        def reduce_function_wrapper(fut_list, internal_storage, storage, ibm_cos):
            logger.info('Waiting for results')
            if 'SHOW_MEMORY_USAGE' in os.environ:
                show_memory = eval(os.environ['SHOW_MEMORY_USAGE'])
            else:
                show_memory = False
            # Wait for all results
            wait(fut_list, executor_id, internal_storage, download_results=True)
            results = [f.result() for f in fut_list if f.done and not f.futures]
            reduce_func_args = {'results': results}

            if show_memory:
                logger.debug("Memory usage after getting the results: {}".format(wrenutil.get_current_memory_usage()))

            # Run reduce function
            func_sig = inspect.signature(reduce_function)
            if 'storage' in func_sig.parameters:
                reduce_func_args['storage'] = storage
            if 'ibm_cos' in func_sig.parameters:
                reduce_func_args['ibm_cos'] = ibm_cos

            return reduce_function(**reduce_func_args)
            #result = reduce_function(**reduce_func_args)
            #run_statuses = [f.run_status for f in fut_list]
            #invoke_statuses = [f.invoke_status for f in fut_list]

            #return {'fn_result': result, 'run_statuses': run_statuses, 'invoke_statuses': invoke_statuses}

        return self._map(reduce_function_wrapper, map_iterdata, extra_env=extra_env,
                         extra_meta=extra_meta, original_func_name=reduce_function.__name__)
