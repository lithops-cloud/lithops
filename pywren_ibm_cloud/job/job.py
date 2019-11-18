import os
import time
import pickle
import logging
import inspect
import pywren_ibm_cloud as pywren
from .serialize import SerializeIndependent, create_module_data
from .partitioner import create_partitions
from pywren_ibm_cloud import utils
from pywren_ibm_cloud.wait import wait_storage
from pywren_ibm_cloud.storage.utils import create_func_key, create_agg_data_key
from pywren_ibm_cloud.config import EXECUTION_TIMEOUT, MAX_AGG_DATA_SIZE

logger = logging.getLogger(__name__)


class JobState:
    Running = 'Running'
    Ready = 'Ready'
    Done = 'Done'
    Finished = 'Finished'


def create_map_job(config, internal_storage, executor_id, map_job_id, map_function, iterdata, runtime_meta,
                   runtime_memory=None, extra_params=None, extra_env=None, obj_chunk_size=None,
                   obj_chunk_number=None, remote_invocation=False, remote_invocation_groups=None,
                   invoke_pool_threads=128, include_modules=[], exclude_modules=[], is_remote_cluster=False,
                   execution_timeout=EXECUTION_TIMEOUT):
    """
    Wrapper to create a map job.  It integrates COS logic to process objects.
    """
    map_func = map_function
    map_iterdata = utils.verify_args(map_function, iterdata, extra_params)
    new_invoke_pool_threads = invoke_pool_threads
    new_runtime_memory = runtime_memory

    # Object processing functionality
    parts_per_object = None
    if utils.is_object_processing_function(map_function):
        # If it is object processing function, create partitions according chunk_size or chunk_number
        logger.debug('ExecutorID {} | JobID {} - Calling map on partitions from object storage flow'.format(executor_id, map_job_id))
        map_iterdata, parts_per_object = create_partitions(config, map_iterdata, obj_chunk_size, obj_chunk_number)
    # ########

    # Remote invocation functionality
    original_total_tasks = len(map_iterdata)
    if original_total_tasks == 1 or is_remote_cluster:
        remote_invocation = False
    if remote_invocation:
        def remote_invoker(input_data):
            pw = pywren.ibm_cf_executor()
            return pw.map(map_function, input_data,
                          runtime_memory=runtime_memory,
                          invoke_pool_threads=invoke_pool_threads,
                          extra_env=extra_env)

        map_func = remote_invoker
        if remote_invocation_groups:
            map_iterdata = [[iterdata[x:x+remote_invocation_groups]]
                            for x in range(0, original_total_tasks, remote_invocation_groups)]
        else:
            map_iterdata = [iterdata]
        map_iterdata = utils.verify_args(remote_invoker, map_iterdata, extra_params)
        new_invoke_pool_threads = 1
        new_runtime_memory = runtime_memory
    # ########

    job_description = _create_job(config, internal_storage, executor_id,
                                  map_job_id, map_func, map_iterdata,
                                  runtime_meta=runtime_meta,
                                  runtime_memory=new_runtime_memory,
                                  extra_env=extra_env,
                                  invoke_pool_threads=new_invoke_pool_threads,
                                  include_modules=include_modules,
                                  exclude_modules=exclude_modules,
                                  remote_invocation=remote_invocation,
                                  original_total_tasks=original_total_tasks,
                                  execution_timeout=execution_timeout)

    job_description['parts_per_object'] = parts_per_object

    return job_description


def create_reduce_job(config, internal_storage, executor_id, reduce_job_id, reduce_function,
                      map_job, map_futures, runtime_meta, reducer_one_per_object=False,
                      runtime_memory=None, extra_env=None, include_modules=[], exclude_modules=[]):
    """
    Wrapper to create a reduce job. Apply a function across all map futures.
    """
    iterdata = [[map_futures, ]]

    if map_job['parts_per_object'] and reducer_one_per_object:
        prev_total_partitons = 0
        iterdata = []
        for total_partitions in map_job['parts_per_object']:
            iterdata.append([map_futures[prev_total_partitons:prev_total_partitons+total_partitions]])
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

    iterdata = utils.verify_args(reduce_function_wrapper, iterdata, None)

    return _create_job(config, internal_storage, executor_id,
                       reduce_job_id, reduce_function_wrapper,
                       iterdata, runtime_meta=runtime_meta,
                       runtime_memory=runtime_memory,
                       extra_env=extra_env,
                       include_modules=include_modules,
                       exclude_modules=exclude_modules,
                       original_func_name=reduce_function.__name__)


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


def _create_job(config, internal_storage, executor_id, job_id, func, data, runtime_meta,
                runtime_memory=None, extra_env=None, invoke_pool_threads=128, include_modules=[],
                exclude_modules=[], original_func_name=None, remote_invocation=False,
                original_total_tasks=None, execution_timeout=EXECUTION_TIMEOUT):
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
    log_level = os.getenv('PYWREN_LOGLEVEL')

    runtime_name = config['pywren']['runtime']
    if runtime_memory is None:
        runtime_memory = config['pywren']['runtime_memory']

    if original_func_name:
        func_name = original_func_name
    else:
        func_name = func.__name__

    extra_env = {} if extra_env is None else extra_env
    if extra_env:
        extra_env = utils.convert_bools_to_string(extra_env)
        logger.debug("Extra environment vars {}".format(extra_env))

    if not data:
        return []

    host_job_meta = {}
    job_description = {}

    job_description['runtime_name'] = runtime_name
    job_description['runtime_memory'] = int(runtime_memory)
    job_description['execution_timeout'] = execution_timeout
    job_description['func_name'] = func_name
    job_description['extra_env'] = extra_env
    job_description['total_calls'] = len(data)
    job_description['invoke_pool_threads'] = invoke_pool_threads
    job_description['job_id'] = job_id
    job_description['remote_invocation'] = remote_invocation
    job_description['original_total_calls'] = original_total_tasks

    log_msg = 'ExecutorID {} | JobID {} - Serializing function and data'.format(executor_id, job_id)
    logger.debug(log_msg)

    # pickle func and all data (to capture module dependencies)
    exclude_modules.extend(config['pywren'].get('exclude_modules', []))
    include_modules_cfg = config['pywren'].get('include_modules', [])
    if include_modules is not None and include_modules_cfg is not None:
        include_modules.extend(include_modules_cfg)
    serializer = SerializeIndependent(runtime_meta['preinstalls'])
    func_and_data_ser, mod_paths = serializer([func] + data, include_modules, exclude_modules)

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

    job_description['metadata'] = host_job_meta

    return job_description
