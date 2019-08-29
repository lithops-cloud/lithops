import os
import time
import pickle
import logging
import inspect
import pywren_ibm_cloud as pywren
from .serialize import SerializeIndependent, create_module_data
from .partitioner import create_partitions, partition_processor
from pywren_ibm_cloud import utils
from pywren_ibm_cloud.monitor import wait_storage
from pywren_ibm_cloud.runtime import select_runtime
from pywren_ibm_cloud.storage.utils import create_func_key, create_agg_data_key
from pywren_ibm_cloud.config import EXECUTION_TIMEOUT, MAX_AGG_DATA_SIZE

logger = logging.getLogger(__name__)


def create_call_async_job(config, internal_storage, executor_id, total_current_jobs, func,
                          data, extra_env=None, extra_meta=None, runtime_memory=None,
                          execution_timeout=EXECUTION_TIMEOUT, exclude_modules=[]):
    """
    Wrapper to create call_async job that contains only one function invocation.
    """
    job_id = str(total_current_jobs).zfill(3)
    async_job_id = f'A{job_id}'
    return _create_job(config, internal_storage, executor_id, async_job_id, func, [data],
                       extra_env=extra_env, extra_meta=extra_meta, runtime_memory=runtime_memory,
                       execution_timeout=execution_timeout, exclude_modules=exclude_modules)


def create_map_job(config, internal_storage, executor_id, total_current_jobs, map_function, iterdata,
                   obj_chunk_size=None, obj_chunk_number=None, extra_env=None, extra_meta=None,
                   runtime_memory=None, remote_invocation=False, remote_invocation_groups=None,
                   invoke_pool_threads=128, exclude_modules=[], is_cf_cluster=False,
                   execution_timeout=EXECUTION_TIMEOUT, overwrite_invoke_args=None):
    """
    Wrapper to create a map job.  It integrates COS logic to process objects.
    """
    job_id = str(total_current_jobs).zfill(3)
    map_job_id = f'M{job_id}'
    data = utils.iterdata_as_list(iterdata)
    map_func = map_function
    map_iterdata = data
    new_invoke_pool_threads = invoke_pool_threads
    new_runtime_memory = runtime_memory

    # Object processing functionality
    parts_per_object = None
    if utils.is_object_processing_function(map_function):
        '''
        If it is object processing function, create partitions according chunk_size or chunk_number
        '''
        logger.debug('ExecutorID {} | JobID {} - Calling map on partitions from object storage flow'.format(executor_id, job_id))
        arg_data = utils.verify_args(map_function, data, object_processing=True)
        map_iterdata, parts_per_object = create_partitions(config, arg_data, obj_chunk_size, obj_chunk_number)
        map_func = partition_processor(map_function)
    # ########

    # Remote invocation functionality
    original_total_tasks = len(map_iterdata)
    if original_total_tasks == 1 or is_cf_cluster:
        remote_invocation = False
    if remote_invocation:
        def remote_invoker(input_data):
            pw = pywren.ibm_cf_executor()
            return pw.map(map_function, input_data,
                          runtime_memory=runtime_memory,
                          invoke_pool_threads=invoke_pool_threads,
                          extra_env=extra_env,
                          extra_meta=extra_meta)

        map_func = remote_invoker
        if remote_invocation_groups:
            map_iterdata = [[iterdata[x:x+remote_invocation_groups]]
                            for x in range(0, original_total_tasks, remote_invocation_groups)]
        else:
            map_iterdata = [iterdata]
        new_invoke_pool_threads = 1
        new_runtime_memory = runtime_memory
    # ########

    job_description = _create_job(config, internal_storage, executor_id,
                                  map_job_id, map_func, map_iterdata,
                                  extra_env=extra_env,
                                  extra_meta=extra_meta,
                                  runtime_memory=new_runtime_memory,
                                  invoke_pool_threads=new_invoke_pool_threads,
                                  overwrite_invoke_args=overwrite_invoke_args,
                                  exclude_modules=exclude_modules,
                                  original_func_name=map_function.__name__,
                                  remote_invocation=remote_invocation,
                                  original_total_tasks=original_total_tasks,
                                  execution_timeout=execution_timeout)

    return job_description, parts_per_object


def create_reduce_job(config, internal_storage, executor_id, total_current_jobs,
                      reduce_function, reduce_runtime_memory, map_futures, parts_per_object,
                      reducer_one_per_object=False, extra_env=None, extra_meta=None, exclude_modules=[]):
    """
    Wrapper to create a reduce job. Apply a function across all map futures.
    """
    job_id = str(total_current_jobs).zfill(3)
    reduce_job_id = f'R{job_id}'
    map_iterdata = [[map_futures, ]]

    if parts_per_object and reducer_one_per_object:
        prev_total_partitons = 0
        map_iterdata = []
        for total_partitions in parts_per_object:
            map_iterdata.append([map_futures[prev_total_partitons:prev_total_partitons+total_partitions]])
            prev_total_partitons = prev_total_partitons + total_partitions

    def reduce_function_wrapper(fut_list, internal_storage, ibm_cos):
        logger.info('Waiting for results')
        if 'SHOW_MEMORY_USAGE' in os.environ:
            show_memory = eval(os.environ['SHOW_MEMORY_USAGE'])
        else:
            show_memory = False
        # Wait for all results
        wait_storage(fut_list, internal_storage, download_results=True)
        results = [f.result() for f in fut_list if f.done and not f.futures]
        fut_list.clear()
        reduce_func_args = {'results': results}

        if show_memory:
            logger.debug("Memory usage after getting the results: {}".format(utils.get_current_memory_usage()))

        # Run reduce function
        func_sig = inspect.signature(reduce_function)
        if 'ibm_cos' in func_sig.parameters:
            reduce_func_args['ibm_cos'] = ibm_cos
        if 'internal_storage' in func_sig.parameters:
            reduce_func_args['internal_storage'] = internal_storage

        return reduce_function(**reduce_func_args)

    return _create_job(config, internal_storage, executor_id, reduce_job_id, reduce_function_wrapper, map_iterdata,
                       runtime_memory=reduce_runtime_memory, extra_env=extra_env, extra_meta=extra_meta,
                       exclude_modules=exclude_modules, original_func_name=reduce_function.__name__)


def _agg_data(data_strs):
    """
    Auxiliary function that aggregates data of a job to a single byte string
    """
    ranges = []
    pos = 0
    for datum in data_strs:
        datum_len = len(datum)
        ranges.append((pos, pos+datum_len-1))
        pos += datum_len
    return b"".join(data_strs), ranges


def _create_job(config, internal_storage, executor_id, job_id, func, iterdata, extra_env=None, extra_meta=None,
                runtime_memory=None, invoke_pool_threads=128, overwrite_invoke_args=None,
                exclude_modules=[], original_func_name=None, remote_invocation=False, original_total_tasks=None,
                execution_timeout=EXECUTION_TIMEOUT):
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
    log_level = os.getenv('CB_LOG_LEVEL')

    runtime_name = config['pywren']['runtime']
    if runtime_memory is None:
        runtime_memory = config['pywren']['runtime_memory']
    runtime_memory = int(runtime_memory)
    runtime_preinstalls = select_runtime(config, internal_storage, executor_id,
                                         job_id, runtime_name, runtime_memory)
    serializer = SerializeIndependent(runtime_preinstalls)

    if original_func_name:
        func_name = original_func_name
    else:
        func_name = func.__name__

    data = utils.iterdata_as_list(iterdata)

    if extra_env is not None:
        extra_env = utils.convert_bools_to_string(extra_env)

    if not data:
        return []

    # This allows multiple parameters in functions
    data = utils.verify_args(func, data)

    host_job_meta = {}
    job_description = {}

    job_description['runtime_name'] = runtime_name
    job_description['runtime_memory'] = runtime_memory
    job_description['execution_timeout'] = execution_timeout
    job_description['func_name'] = func_name
    job_description['extra_env'] = extra_env
    job_description['extra_meta'] = extra_meta
    job_description['total_calls'] = len(data)
    job_description['invoke_pool_threads'] = invoke_pool_threads
    job_description['overwrite_invoke_args'] = overwrite_invoke_args
    job_description['job_id'] = job_id
    job_description['remote_invocation'] = remote_invocation
    job_description['original_total_calls'] = original_total_tasks

    log_msg = 'ExecutorID {} | JobID {} - Serializing function and data'.format(executor_id, job_id)
    logger.debug(log_msg)
    # pickle func and all data (to capture module dependencies)
    func_and_data_ser, mod_paths = serializer([func] + data, exclude_modules)

    func_str = func_and_data_ser[0]
    data_strs = func_and_data_ser[1:]
    data_size_bytes = sum(len(x) for x in data_strs)

    host_job_meta['agg_data'] = False
    host_job_meta['data_size_bytes'] = data_size_bytes

    log_msg = 'ExecutorID {} | JobID {} - Uploading function and data'.format(executor_id, job_id)
    logger.info(log_msg)
    if not log_level:
        print(log_msg, end=' ')

    if data_size_bytes < MAX_AGG_DATA_SIZE:
        agg_data_key = create_agg_data_key(internal_storage.prefix, executor_id, job_id)
        job_description['data_key'] = agg_data_key
        agg_data_bytes, agg_data_ranges = _agg_data(data_strs)
        job_description['data_ranges'] = agg_data_ranges
        agg_upload_time = time.time()
        internal_storage.put_data(agg_data_key, agg_data_bytes)
        host_job_meta['agg_data'] = True
        host_job_meta['data_upload_time'] = time.time() - agg_upload_time
        host_job_meta['data_upload_timestamp'] = time.time()
    else:
        log_msg = ('ExecutorID {} | JobID {} - Total data exceeded '
                   'maximum size of {} bytes'.format(executor_id, job_id, MAX_AGG_DATA_SIZE))
        raise Exception(log_msg)

    module_data = create_module_data(mod_paths)
    # Create func and upload
    host_job_meta['func_name'] = func_name
    func_module_str = pickle.dumps({'func': func_str, 'module_data': module_data}, -1)
    host_job_meta['func_module_bytes'] = len(func_module_str)

    func_upload_time = time.time()
    func_key = create_func_key(internal_storage.prefix, executor_id, job_id)
    job_description['func_key'] = func_key
    internal_storage.put_func(func_key, func_module_str)
    host_job_meta['func_upload_time'] = time.time() - func_upload_time
    host_job_meta['func_upload_timestamp'] = time.time()

    if not log_level:
        func_and_data_size = utils.sizeof_fmt(host_job_meta['func_module_bytes']+host_job_meta['data_size_bytes'])
        log_msg = '- Total: {}'.format(func_and_data_size)
        print(log_msg)

    job_description['host_job_meta'] = host_job_meta

    return job_description
