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
import requests
import pywren_ibm_cloud as pywren
import pywren_ibm_cloud.version as version
import pywren_ibm_cloud.wrenutil as wrenutil
from pywren_ibm_cloud.wait import wait
from multiprocessing.pool import ThreadPool
from pywren_ibm_cloud.wrenconfig import MAX_AGG_DATA_SIZE
from pywren_ibm_cloud.partitioner import object_partitioner
from pywren_ibm_cloud.future import ResponseFuture, JobState
from pywren_ibm_cloud.runtime import get_runtime_preinstalls
from pywren_ibm_cloud.serialize import serialize, create_mod_data
from pywren_ibm_cloud.storage.storage_utils import create_keys, create_func_key, create_agg_data_key
from pywren_ibm_cloud.storage.backends.cos import COSBackend


logger = logging.getLogger(__name__)


class Executor(object):

    def __init__(self, invoker, config, internal_storage, timeout):
        self.invoker = invoker
        self.job_max_runtime = timeout

        self.config = config
        self.internal_storage = internal_storage

        if 'PYWREN_EXECUTOR_ID' in os.environ:
            self.executor_id = os.environ['PYWREN_EXECUTOR_ID']
        else:
            self.executor_id = wrenutil.create_executor_id()

        runtime = self.config['ibm_cf']['action_name']
        runtime_preinstalls = get_runtime_preinstalls(self.internal_storage, runtime)

        self.serializer = serialize.SerializeIndependent(runtime_preinstalls)

        self.map_item_limit = None
        if 'scheduler' in self.config:
            if 'map_item_limit' in config['scheduler']:
                self.map_item_limit = config['scheduler']['map_item_limit']

        log_msg = 'IBM Cloud Functions executor created with ID {}'.format(self.executor_id)
        logger.info(log_msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(log_msg)

    def invoke_with_keys(self, func_key, data_key, output_key,
                         status_key, executor_id, callgroup_id,
                         call_id, extra_env,
                         extra_meta, data_byte_range,
                         host_job_meta, job_max_runtime,
                         overwrite_invoke_args=None):

        arg_dict = {
            'config': self.config,
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

        logger.debug("Executor ID {} Activation {} invoke".format(executor_id, call_id))

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

        logger.debug("Executor ID {} Activation {} complete".format(executor_id, call_id))

        host_job_meta.update(self.invoker.config())
        host_job_meta.update(arg_dict)
        storage_config = self.internal_storage.get_storage_config()
        fut = ResponseFuture(call_id, callgroup_id, executor_id, activation_id, host_job_meta, storage_config)
        fut._set_state(JobState.invoked)

        return fut

    @staticmethod
    def agg_data(data_strs):
        ranges = []
        pos = 0
        for datum in data_strs:
            l = len(datum)
            ranges.append((pos, pos+l-1))
            pos += l
        return b"".join(data_strs), ranges

    def object_processing(self, map_function):
        """
        Method that returns the function to process objects in the Cloud.
        It creates a ready-to-use data_stream parameter
        """
        def object_processing_function(map_func_args, data_byte_range, storage, ibm_cos):
            extra_get_args = {}
            if data_byte_range is not None:
                range_str = 'bytes={}-{}'.format(*data_byte_range)
                extra_get_args['Range'] = range_str
                print(extra_get_args)

            logger.info('Getting dataset')
            if 'url' in map_func_args:
                # it is a public url
                resp = requests.get(map_func_args['url'], headers=extra_get_args, stream=True)
                map_func_args['data_stream'] = resp.raw

            elif 'key' in map_func_args:
                # it is a COS key
                if 'bucket' not in map_func_args or ('bucket' in map_func_args and not map_func_args['bucket']):
                    bucket, object_name = map_func_args['key'].split('/', 1)
                else:
                    bucket = map_func_args['bucket']
                    object_name = map_func_args['key']
                fileobj = storage.get_object(bucket, object_name, stream=True,
                                             extra_get_args=extra_get_args)
                map_func_args['data_stream'] = fileobj
                # fileobj = wrenutil.WrappedStreamingBody(stream, obj_chunk_size, chunk_threshold)

            func_sig = inspect.signature(map_function)
            if 'storage' in func_sig.parameters:
                map_func_args['storage'] = storage

            if 'ibm_cos' in func_sig.parameters:
                map_func_args['ibm_cos'] = ibm_cos

            return map_function(**map_func_args)

        return object_processing_function

    def single_call(self, func, data, extra_env=None, extra_meta=None):
        """
        Wrapper to launch one function invocation.
        """

        return self.map(func, [data], extra_env=extra_env, extra_meta=extra_meta)

    def multiple_call(self, map_function, iterdata, reduce_function=None,
                      obj_chunk_size=None, extra_env=None, extra_meta=None,
                      remote_invocation=False, invoke_pool_threads=128,
                      data_all_as_one=True, overwrite_invoke_args=None,
                      exclude_modules=None, reducer_one_per_object=False,
                      reducer_wait_local=True):
        """
        Wrapper to launch both map() and map_reduce() methods.
        It integrates COS logic to process objects.
        """
        data = wrenutil.iterdata_as_list(iterdata)
        # Check function signature to see if the user wants to process
        # objects in Object Storage, from a public URL, or none.
        func_sig = inspect.signature(map_function)
        if {'bucket', 'key', 'url'} & set(func_sig.parameters):
            # map-reduce over objects in COS/Swift or public URL. It will launch a partitioner
            # Wrap original map function. This will produce the ready-to-use data_stream parameter
            object_processing_function = self.object_processing(map_function)
            # Get the object partitioner function
            object_partitioner_function = object_partitioner(object_processing_function,
                                                             reduce_function,
                                                             extra_env, extra_meta)
            arg_data = wrenutil.verify_args(map_function, data, object_processing=True)
            if reducer_one_per_object:
                part_func_args = []
                if 'bucket' in func_sig.parameters:
                    # need to discover data objects
                    for entry in arg_data:
                        # Each entry is a bucket
                        bucket_name, prefix = wrenutil.split_path(entry['bucket'])
                        storage = COSBackend(self.config['ibm_cos'])
                        obj_keys = storage.list_keys_with_prefix(bucket_name, prefix)
                        for key in obj_keys:
                            new_entry = entry.copy()
                            new_entry['bucket'] = None
                            new_entry['key'] = '{}/{}'.format(bucket_name, key)
                            part_args = {'map_func_args': [new_entry],
                                         'chunk_size': obj_chunk_size}
                            part_func_args.append(part_args)
                else:
                    # Object keys
                    for entry in arg_data:
                        part_args = {'map_func_args': [entry],
                                     'chunk_size': obj_chunk_size}
                        part_func_args.append(part_args)
            else:
                part_func_args = [{'map_func_args': arg_data,
                                   'chunk_size': obj_chunk_size}]

            logger.debug("Calling map on partitions from object storage flow")
            return self.map(object_partitioner_function, part_func_args,
                            extra_env=extra_env,
                            extra_meta=extra_meta,
                            original_func_name=map_function.__name__,
                            invoke_pool_threads=invoke_pool_threads,
                            data_all_as_one=data_all_as_one,
                            overwrite_invoke_args=overwrite_invoke_args,
                            exclude_modules=exclude_modules)
        else:
            def remote_invoker(input_data):
                pw = pywren.ibm_cf_executor()
                return pw.map(map_function, input_data,
                              extra_env=extra_env,
                              extra_meta=extra_meta)

            if len(iterdata) > 1 and remote_invocation:
                map_func = remote_invoker
                map_iterdata = [[iterdata[x:x+100]] for x in range(0, len(iterdata), 100)]
                invoke_pool_threads = 1
            else:
                remote_invocation = False
                map_func = map_function
                map_iterdata = iterdata

            map_futures = self.map(map_func, map_iterdata,
                                   extra_env=extra_env,
                                   extra_meta=extra_meta,
                                   invoke_pool_threads=invoke_pool_threads,
                                   data_all_as_one=data_all_as_one,
                                   overwrite_invoke_args=overwrite_invoke_args,
                                   exclude_modules=exclude_modules,
                                   original_func_name=map_function.__name__)

            if not reduce_function:
                return map_futures

            logger.debug("Calling reduce")
            return self.reduce(reduce_function, map_futures,
                               wait_local=reducer_wait_local,
                               extra_env=extra_env,
                               extra_meta=extra_meta)

    def map(self, func, iterdata, extra_env=None, extra_meta=None, invoke_pool_threads=128,
            data_all_as_one=True, overwrite_invoke_args=None, exclude_modules=None,
            original_func_name=None):
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

        pool = ThreadPool(invoke_pool_threads)

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
        logger.debug(log_msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(log_msg)

        if data_size_bytes < MAX_AGG_DATA_SIZE and data_all_as_one:
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
                                                         MAX_AGG_DATA_SIZE))
            logger.warning(log_msg)

        if exclude_modules:
            for module in exclude_modules:
                for mod_path in list(mod_paths):
                    if module in mod_path and mod_path in mod_paths:
                        mod_paths.remove(mod_path)

        module_data = create_mod_data(mod_paths)
        # Create func and upload
        func_module_str = pickle.dumps({'func': func_str, 'module_data': module_data}, -1)
        host_job_meta['func_module_str_len'] = len(func_module_str)

        func_upload_time = time.time()
        func_key = create_func_key(self.internal_storage.prefix, self.executor_id, callgroup_id)
        self.internal_storage.put_func(func_key, func_module_str)
        host_job_meta['func_upload_time'] = time.time() - func_upload_time
        host_job_meta['func_upload_timestamp'] = time.time()

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
                                         self.job_max_runtime,
                                         overwrite_invoke_args=overwrite_invoke_args)

        N = len(data)
        call_result_objs = []

        start_inv = time.time()
        log_msg = 'Executor ID {} Starting function invocation: {}()'.format(self.executor_id, func_name)
        logger.debug(log_msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(log_msg)

        for i in range(N):
            call_id = "{:05d}".format(i)

            data_byte_range = None
            if agg_data_key is not None:
                data_byte_range = agg_data_ranges[i]

            cb = pool.apply_async(invoke, (data_strs[i], self.executor_id,
                                           callgroup_id, call_id, func_key,
                                           host_job_meta.copy(),
                                           agg_data_key,
                                           data_byte_range))

            call_result_objs.append(cb)

        res = [c.get() for c in call_result_objs]
        pool.close()
        pool.join()

        log_msg = 'Executor ID {} Invocation done: {} seconds'.format(self.executor_id,
                                                                      round(time.time()-start_inv, 3))
        logger.debug(log_msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(log_msg)

        return res

    def reduce(self, reduce_function, list_of_futures, throw_except=True,
               wait_local=True, extra_env=None, extra_meta=None):
        """
        Apply a function across all futures.
        """
        executor_id = self.executor_id

        if wait_local:
            logger.info('Waiting locally for results')
            wait(list_of_futures, executor_id, self.internal_storage, throw_except=throw_except)

        def reduce_function_wrapper(fut_list, internal_storage, storage, ibm_cos):
            logger.info('Waiting for results')
            if 'SHOW_MEMORY_USAGE' in os.environ:
                show_memory = eval(os.environ['SHOW_MEMORY_USAGE'])
            else:
                show_memory = False
            # Wait for all results
            wait(fut_list, executor_id, internal_storage, throw_except=throw_except)
            results = [f.result() for f in fut_list if f.done and not f.futures]
            reduce_func_args = {'results': results}

            if show_memory:
                logger.debug("Memory usage after getting the results: {}".format(wrenutil.get_current_memory_usage()))

            # Run reduce function
            func_sig = inspect.signature(reduce_function)
            if 'futures' in func_sig.parameters:
                reduce_func_args['futures'] = fut_list
            if 'storage' in func_sig.parameters:
                reduce_func_args['storage'] = storage
            if 'ibm_cos' in func_sig.parameters:
                reduce_func_args['ibm_cos'] = ibm_cos

            return reduce_function(**reduce_func_args)

        return self.map(reduce_function_wrapper, [[list_of_futures, ]], extra_env=extra_env,
                        extra_meta=extra_meta, original_func_name=reduce_function.__name__)
