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

import logging
import time
from multiprocessing.pool import ThreadPool
from six.moves import cPickle as pickle
import os
import inspect
import requests
import pywren_ibm_cloud as pywren
import pywren_ibm_cloud.version as version
import pywren_ibm_cloud.wrenconfig as wrenconfig
import pywren_ibm_cloud.wrenutil as wrenutil
from pywren_ibm_cloud.future import ResponseFuture, JobState
from pywren_ibm_cloud.serialize import serialize, create_mod_data
from pywren_ibm_cloud.storage import storage_utils
from pywren_ibm_cloud.storage.storage_utils import create_func_key, create_agg_data_key
from pywren_ibm_cloud.wait import wait
from pywren_ibm_cloud.runtime import get_runtime_preinstalls


logger = logging.getLogger(__name__)


class Executor(object):

    def __init__(self, invoker, config, storage_handler, job_max_runtime):
        self.invoker = invoker
        self.job_max_runtime = job_max_runtime

        self.config = config
        self.storage_handler = storage_handler
        
        if 'PYWREN_EXECUTOR_ID' in os.environ:
            self.executor_id = os.environ['PYWREN_EXECUTOR_ID']
        else:
            self.executor_id = wrenutil.create_executor_id()

        runtime = self.config['ibm_cf']['action_name']
        runtime_preinstalls = get_runtime_preinstalls(self.storage_handler, runtime)
        
        self.serializer = serialize.SerializeIndependent(runtime_preinstalls)

        self.map_item_limit = None
        if 'scheduler' in self.config:
            if 'map_item_limit' in config['scheduler']:
                self.map_item_limit = config['scheduler']['map_item_limit']

    def put_data(self, data_key, data_str,
                 executor_id, call_id):

        self.storage_handler.put_data(data_key, data_str)
        logger.debug("call_async {} {} data upload complete {}".format(executor_id, call_id,
                                                                      data_key))

    def invoke_with_keys(self, func_key, data_key, output_key,
                         status_key, executor_id, callgroup_id,
                         call_id, extra_env,
                         extra_meta, data_byte_range,
                         host_job_meta, job_max_runtime,
                         overwrite_invoke_args=None):

        storage_config = self.storage_handler.get_storage_config()

        arg_dict = {
            'config' : self.config,
            'storage_config' : storage_config,
            'func_key' : func_key,
            'data_key' : data_key,
            'output_key' : output_key,
            'status_key' : status_key,
            'job_max_runtime' : job_max_runtime,
            'data_byte_range' : data_byte_range,   
            'executor_id': executor_id,
            'callgroup_id' : callgroup_id,
            'call_id' : call_id,
            'pywren_version' : version.__version__}

        if extra_env is not None:
            logger.debug("Extra environment vars {}".format(extra_env))
            arg_dict['extra_env'] = extra_env

        if extra_meta is not None:
            # sanity
            for k, v in extra_meta.iteritems():
                if k in arg_dict:
                    raise ValueError("Key {} already in dict".format(k))
                arg_dict[k] = v

        host_submit_time = time.time()
        arg_dict['host_submit_time'] = host_submit_time

        logger.debug("call_async {} {} cf invoke ".format(executor_id, call_id))

        # overwrite explicit args, mostly used for testing via injection
        if overwrite_invoke_args is not None:
            arg_dict.update(overwrite_invoke_args)
        
        lambda_invoke_time_start = time.time()
        # do the invocation
        activation_id = self.invoker.invoke(arg_dict)

        host_job_meta['cf_activation_id'] = activation_id
        host_job_meta['cf_invoke_timestamp'] = lambda_invoke_time_start
        host_job_meta['cf_invoke_time'] = time.time() - lambda_invoke_time_start


        host_job_meta.update(self.invoker.config())

        logger.debug("call_async {} {} cf invoke complete".format(executor_id, call_id))


        host_job_meta.update(arg_dict)
        fut = ResponseFuture(call_id, callgroup_id, executor_id, activation_id, host_job_meta, storage_config)
        fut._set_state(JobState.invoked)

        return fut

    def call_async(self, func, data, extra_env=None, extra_meta=None):
        return self.map(func, [data], extra_env, extra_meta)

    @staticmethod
    def agg_data(data_strs):
        ranges = []
        pos = 0
        for datum in data_strs:
            l = len(datum)
            ranges.append((pos, pos + l -1))
            pos += l
        return b"".join(data_strs), ranges

    def map(self, func, iterdata, extra_env=None, extra_meta=None, invoke_pool_threads=128, 
            data_all_as_one=True, overwrite_invoke_args=None, exclude_modules=None,
            original_func_name=None):
        """
        :param func: the function to map over the data
        :param iterdata: An iterable of input data
        :param extra_env: Additional environment variables for lambda environment. Default None.
        :param extra_meta: Additional metadata to pass to lambda. Default None.
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

        if type(iterdata) != list:
            data = list(iterdata)
        else:
            data = iterdata

        if not data:
            return []

        if self.map_item_limit is not None and len(data) > self.map_item_limit:
            raise ValueError("len(data) ={}, exceeding map item limit of {}"\
                             "consider mapping over a smaller"\
                             "number of items".format(len(data),
                                                      self.map_item_limit))
        
        # This allows multiple parameters in functions
        data = wrenutil.verify_args(func, data)
        
        callgroup_id = wrenutil.create_callgroup_id()
        
        host_job_meta = {}

        pool = ThreadPool(invoke_pool_threads)      

        ### pickle func and all data (to capture module dependencies)
        func_and_data_ser, mod_paths = self.serializer([func] + data)

        func_str = func_and_data_ser[0]
        data_strs = func_and_data_ser[1:]
        data_size_bytes = sum(len(x) for x in data_strs)

        agg_data_key = None
        host_job_meta['agg_data'] = False
        host_job_meta['data_size_bytes'] = data_size_bytes
        
        log_msg='Executor ID {} Uploading function and data'.format(self.executor_id)
        logger.info(log_msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(log_msg)

        if data_size_bytes < wrenconfig.MAX_AGG_DATA_SIZE and data_all_as_one:
            agg_data_key = create_agg_data_key(self.storage_handler.prefix, self.executor_id, callgroup_id)
            agg_data_bytes, agg_data_ranges = self.agg_data(data_strs)
            agg_upload_time = time.time()
            self.storage_handler.put_data(agg_data_key, agg_data_bytes)
            host_job_meta['agg_data'] = True
            host_job_meta['data_upload_time'] = time.time() - agg_upload_time
            host_job_meta['data_upload_timestamp'] = time.time()
        else:
            # FIXME add warning that you wanted data all as one but
            # it exceeded max data size
            pass

        if exclude_modules:
            for module in exclude_modules:
                for mod_path in list(mod_paths):
                    if module in mod_path and mod_path in mod_paths:
                        mod_paths.remove(mod_path)

        module_data = create_mod_data(mod_paths)
        ### Create func and upload
        func_module_str = pickle.dumps({'func' : func_str,
                                        'module_data' : module_data}, -1)
        host_job_meta['func_module_str_len'] = len(func_module_str)

        func_upload_time = time.time()
        func_key = create_func_key(self.storage_handler.prefix, self.executor_id, callgroup_id)
        self.storage_handler.put_func(func_key, func_module_str)
        host_job_meta['func_upload_time'] = time.time() - func_upload_time
        host_job_meta['func_upload_timestamp'] = time.time()
        
        def invoke(data_str, executor_id, callgroup_id, call_id, func_key,
                   host_job_meta,
                   agg_data_key=None, data_byte_range=None):
            data_key, output_key, status_key \
                = storage_utils.create_keys(self.storage_handler.prefix, executor_id, callgroup_id, call_id)

            host_job_meta['job_invoke_timestamp'] = time.time()

            if agg_data_key is None:
                data_upload_time = time.time()
                self.put_data(data_key, data_str,
                              executor_id, call_id)
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
        log_msg='Executor ID {} Starting function invocation: {}()'.format(self.executor_id, func_name)
        logger.info(log_msg)
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

            logger.debug("map {} {} apply async".format(self.executor_id, call_id))

            call_result_objs.append(cb)

        res = [c.get() for c in call_result_objs]
        pool.close()
        pool.join()

        log_msg='Executor ID {} Invocation done: {} seconds'.format(self.executor_id,
                                                                    round(time.time()-start_inv, 3))
        logger.info(log_msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(log_msg)

        return res

    def reduce(self, function, list_of_futures, throw_except=True,
               wait_local=True, extra_env=None, extra_meta=None):
        """
        Apply a function across all futures.
        """
        executor_id = self.executor_id
        
        if wait_local:
            wait(list_of_futures, executor_id, self.storage_handler, throw_except)
        
        def reduce_func(fut_list, storage_handler):
            logger.info('Starting reduce_func() function')
            logger.info('Waiting for results')
            # Wait for all results
            wait(fut_list, executor_id, storage_handler, throw_except)
            accum_list = []

            # Get all results
            for f in fut_list:
                accum_list.append(f.result(throw_except=throw_except, storage_handler=storage_handler))

            # Run reduce function
            func_sig = inspect.signature(function)
            if 'futures' in func_sig.parameters and 'storage_handler' in func_sig.parameters:
                return function(accum_list, futures=fut_list, storage_handler=storage_handler)
            if 'storage_handler' in func_sig.parameters:
                return function(accum_list, storage_handler=storage_handler)
            if 'futures' in func_sig.parameters:
                return function(accum_list, futures=fut_list)
            
            return function(accum_list)

        return self.call_async(reduce_func, [list_of_futures,],
                               extra_env=extra_env, extra_meta=extra_meta)[0]
                           
    def map_reduce(self, map_function, iterdata, reduce_function, obj_chunk_size=64*1024**2,
                   reducer_one_per_object=False, reducer_wait_local=True, throw_except=True,
                   extra_env=None, extra_meta=None):
        """
        Designed to run all-in-cloud map-reduce like functions.
        The method includes a partitioner function which splits the dataset
        into obj_chunk_size chunks.
        """

        if type(iterdata) != list:
            data = [iterdata]
        else:
            data = iterdata
            
        chunk_threshold = 4*1024  # 4KB
        
        def map_func(map_func_args, data_byte_range, storage_handler):
            extra_get_args = {}
            if data_byte_range is not None:
                range_str = 'bytes={}-{}'.format(*data_byte_range)
                extra_get_args['Range'] = range_str
                print(extra_get_args)
            
            print('Getting dataset')
            if 'url' in map_func_args:
                #it is a public url
                resp = requests.get(map_func_args['url'], headers=extra_get_args, stream=True)
                fileobj = resp.raw
            elif 'key' in map_func_args:
                # it is a COS key
                bucket, object_name = map_func_args['key'].split('/', 1)   
                fileobj = storage_handler.get_object(bucket, object_name, stream=True,
                                                     extra_get_args=extra_get_args)   
                # fileobj = wrenutil.WrappedStreamingBody(stream, obj_chunk_size, chunk_threshold)
    
            func_sig = inspect.signature(map_function)
            if 'storage_handler' in func_sig.parameters:
                return map_function(**map_func_args, data_stream=fileobj, storage_handler=storage_handler)
            return map_function(**map_func_args, data_stream=fileobj)

        def get_object_list(bucket_name, storage_handler):
            """
            This function returns the objects inside a given bucket
            """
            if not storage_handler.bucket_exists(bucket_name):
                raise ValueError('Bucket you provided does not exists: \
                                 {}'.format(bucket_name))

            return storage_handler.list_objects(bucket_name)
        
        def split_objects_from_bucket(map_func_args_list, chunk_size, storage_handler):
            """
            Create partitions from bucket/s      
            """
            logger.info('Creating dataset chunks from bucket/s ...')
            partitions = list()
            
            for entry in map_func_args_list:
                # Each entry is a bucket
                bucket_name =  entry['bucket']
                dataset_objects = get_object_list(bucket_name, storage_handler)
                
                logger.info('Creating dataset chunks from objects within "{}" '
                            'bucket ...'.format(bucket_name))
    
                for obj in dataset_objects:
                    try:
                        # S3 API
                        key = obj['Key']
                        obj_size = obj['Size']
                    except:
                        # Swift API
                        key = obj['name']
                        obj_size = obj['bytes']
                    
                    full_key = '{}/{}'.format(bucket_name, key)

                    size = 0
                    if obj_size > chunk_size:
                        size = 0
                        while size < obj_size:
                            brange = (size, size+chunk_size+chunk_threshold)
                            size += chunk_size
                            partition = {}
                            partition['map_func_args'] = entry.copy()
                            partition['map_func_args']['key'] = full_key
                            partition['data_byte_range'] = brange
                            partitions.append(partition)
                    else:
                        partition = {}
                        partition['map_func_args'] = entry.copy()
                        partition['map_func_args']['key'] = full_key
                        partition['data_byte_range'] = (0, obj_size)
                        partitions.append(partition)

            return partitions
        
        def split_object_from_key(map_func_args_list, chunk_size, storage_handler):
            """
            Create partitions from a list of COS objects keys      
            """      
            logger.info('Creating dataset chunks from object keys ...')
            partitions = list()

            for entry in map_func_args_list:                
                object_key = entry['key']
                logger.info(object_key)
                bucket, object_name = object_key.split('/', 1)
                metadata = storage_handler.get_metadata(bucket, object_name)
                obj_size = int(metadata['content-length'])
    
                if obj_size > chunk_size:
                    size = 0
                    while size < obj_size:
                        brange = (size, size+chunk_size+chunk_threshold)
                        size += chunk_size
                        partition = {}
                        partition['map_func_args'] = entry
                        partition['data_byte_range'] = brange
                        partitions.append(partition)
                else:
                    partition = {}
                    partition['map_func_args'] = entry
                    partition['data_byte_range'] = (0, obj_size)
                    partitions.append(partition)
            
            return partitions
        
        def split_object_from_url(map_func_args_list, object_url, chunk_size):     
            """
            Create partitions from a list of objects urls      
            """
            logger.info('Creating dataset chunks from urls ...')
            partitions = list()

            for entry in map_func_args_list:                
                object_key = entry['key']
                logger.info(object_key)
                metadata = requests.head(object_url)
                obj_size = int(metadata.headers['content-length'])
    
                if 'accept-ranges' in metadata.headers and obj_size > chunk_size:
                    size = 0
                    while size < obj_size:
                        brange = (size, size+chunk_size+chunk_threshold)
                        size += chunk_size
                        partition = {}
                        partition['map_func_args'] = entry
                        partition['data_byte_range'] = brange
                        partitions.append(partition)
                else:
                    partition = {}
                    partition['map_func_args'] = entry
                    partition['data_byte_range'] = (0, obj_size)
                    partitions.append(partition)
            
            return partitions

        def partitioner(map_func_args, chunk_size, storage_handler):
            logger.info('Starting partitioner() function')
            map_func_keys = map_func_args[0].keys()
    
            if 'bucket' in map_func_keys and not 'key' in map_func_keys:
                partitions = split_objects_from_bucket(map_func_args,
                                                       chunk_size,
                                                       storage_handler)
            elif 'key' in map_func_keys:
                partitions = split_object_from_key(map_func_args,
                                                   chunk_size,
                                                   storage_handler)
            elif 'url' in map_func_keys:
                partitions = split_object_from_url(map_func_args,
                                                   chunk_size)
            else:
                raise ValueError('You did not provide any bucket or object key/url')
            
            # logger.info(partitions)

            pw = pywren.ibm_cf_executor()
            reduce_future = pw.map_reduce(map_func, partitions, reduce_function,
                                          reducer_wait_local=False, throw_except=throw_except)
                    
            return reduce_future

        # Check function signature to see if the user wants to process
        # objects in Object Storage.
        func_sig = inspect.signature(map_function)

        if 'bucket' in func_sig.parameters or 'key' in func_sig.parameters or \
           'url' in func_sig.parameters:
            # map-reduce over objects in COS or public URL
            # it will launch a partitioner
            arg_data = wrenutil.verify_args(map_function, data,
                                            object_processing=True)

            if reducer_one_per_object:  
                if 'bucket' in func_sig.parameters:
                    part_func_args = []
                    for entry in arg_data:
                        # Each entry is a bucket
                        bucket_name =  entry['bucket']
                        objects = get_object_list(bucket_name,
                                                  self.storage_handler)
                        for obj in objects:
                            try: # S3 API
                                full_key = '{}/{}'.format(bucket_name, obj['Key'])
                            except:  # Swift API
                                full_key = '{}/{}'.format(bucket_name, obj['name'])
                            
                            new_entry = entry.copy()
                            new_entry['key'] = full_key

                            part_args = {'map_func_args': [new_entry],
                                         'chunk_size' : obj_chunk_size}
                            part_func_args.append(part_args)
                else:
                    part_func_args = []
                    for entry in arg_data:
                        part_args = {'map_func_args': [entry],
                                     'chunk_size' : obj_chunk_size}
                        part_func_args.append(part_args)
            else:
                part_func_args = [{'map_func_args': arg_data,
                                   'chunk_size' : obj_chunk_size}]

            return self.map(partitioner, part_func_args,
                            extra_env=extra_env,
                            extra_meta=extra_meta, 
                            original_func_name=map_function.__name__)
        else:
            # map-reduce over anything else
            map_futures = self.map(map_function, iterdata,
                                   extra_env=extra_env,
                                   extra_meta=extra_meta)
            
            return self.reduce(reduce_function, map_futures,
                               throw_except=throw_except,
                               wait_local=reducer_wait_local,
                               extra_env=extra_env, 
                               extra_meta=extra_meta)
