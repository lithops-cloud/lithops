#
# Copyright 2018 PyWren Team
# (C) Copyright IBM Corp. 2020
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

import os
import time
import hashlib
import inspect
import pickle
import logging
import weakref
from collections.abc import Callable, Iterable, Mapping
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

from lithops import utils
from lithops.job.partitioner import create_partitions
from lithops.storage.utils import create_func_key, create_data_key, \
    create_job_key, func_key_suffix
from lithops.job.serialize import (
    SerializeIndependent, create_module_data, write_module_data
)
from lithops.constants import (
    MAX_AGG_DATA_SIZE, SERVERLESS, STANDALONE, CUSTOM_RUNTIME_DIR, JOBS_PREFIX
)


logger = logging.getLogger(__name__)

FUNCTION_CACHE = set()
_FUNC_SERIALIZE_CACHE = weakref.WeakKeyDictionary()
MAX_DATA_IN_PAYLOAD = 8 * 1024  # Per invocation. 8KB


def invalidate_function_cache(executor_id: str) -> None:
    """
    Drops the cached func keys of an executor, after they were deleted from
    the storage backend and have to be uploaded again
    """
    prefix = f'{JOBS_PREFIX}/{executor_id}/'
    FUNCTION_CACHE.difference_update(
        key for key in tuple(FUNCTION_CACHE) if key.startswith(prefix)
    )


def _freeze_module_set(mods: Optional[Set[str]]) -> Optional[Tuple[str, ...]]:
    if mods is None:
        return None
    return tuple(sorted(mods))


def _cached_func_serialize(
    serializer: Any,
    func: Callable,
    inc_modules: Optional[Set[str]],
    exc_modules: Set[str]
) -> Tuple[bytes, Set[str]]:
    """
    Serializes a function and resolves its modules, reusing the result of a
    previous job that ran the same function with the same module filters
    """
    subkey = (
        _freeze_module_set(inc_modules),
        _freeze_module_set(exc_modules),
    )
    try:
        per_func = _FUNC_SERIALIZE_CACHE[func]
    except TypeError:
        # Not every callable can be weak referenced, so caching is best effort
        per_func = None
    except KeyError:
        per_func = {}
        try:
            _FUNC_SERIALIZE_CACHE[func] = per_func
        except TypeError:
            per_func = None

    if per_func is not None:
        cached = per_func.get(subkey)
        if cached is not None:
            return cached

    func_str = serializer.dumps([func])[0]
    func_paths = serializer.module_paths([func], inc_modules, exc_modules)
    cached = (func_str, func_paths)
    if per_func is not None:
        per_func[subkey] = cached
    return cached


def _serialize_func_and_data(
    serializer: Any,
    func: Callable,
    iterdata: List,
    inc_modules: Optional[Set[str]],
    exc_modules: Set[str]
) -> Tuple[bytes, List[bytes], Set[str]]:
    """
    Serializes the function apart from its data, so that the function can be
    cached across jobs. Falls back to serializing everything in one go for
    serializers that only expose a call interface
    """
    dumps = getattr(serializer, 'dumps', None)
    module_paths = getattr(serializer, 'module_paths', None)
    if dumps is None or module_paths is None:
        ser, paths = serializer(
            [func] + list(iterdata), inc_modules, exc_modules
        )
        return ser[0], ser[1:], paths

    func_str, func_paths = _cached_func_serialize(
        serializer, func, inc_modules, exc_modules
    )
    data_strs = dumps(iterdata)
    # The data is only inspected for modules when the module manager is on
    # and no explicit include list was given
    if inc_modules is not None and not inc_modules:
        data_paths = module_paths(iterdata, inc_modules, exc_modules)
    else:
        data_paths = set()
    return func_str, data_strs, func_paths | data_paths


def create_map_job(
    config: Dict[str, Any],
    internal_storage: Any,
    executor_id: str,
    job_id: str,
    map_function: Callable,
    iterdata: Iterable,
    runtime_meta: Mapping[str, Any],
    runtime_memory: Optional[int],
    extra_env: Optional[Mapping[str, Any]],
    include_modules: Optional[Iterable[str]],
    exclude_modules: Optional[Iterable[str]],
    execution_timeout: Optional[int],
    chunksize: Optional[int] = None,
    extra_args: Any = None,
    obj_chunk_size: Optional[int] = None,
    obj_newline: Optional[str] = '\n',
    obj_chunk_number: Optional[int] = None
) -> SimpleNamespace:
    """
    Creates a map job, splitting the referenced objects into partitions first
    when the function processes data from object storage
    """
    host_job_meta = {'host_job_create_tstamp': time.time()}
    map_iterdata = utils.verify_args(map_function, iterdata, extra_args)

    parts_per_object = None
    if utils.is_object_processing_function(map_function):
        create_partitions_start = time.time()
        logger.debug(
            f'{utils.log_prefix(executor_id, job_id)} - Calling map on partitions '
            'from object storage flow'
        )
        map_iterdata, parts_per_object = create_partitions(
            config, internal_storage, map_iterdata,
            obj_chunk_size, obj_chunk_number, obj_newline
        )
        host_job_meta['host_job_create_partitions_time'] = round(
            time.time() - create_partitions_start, 6
        )

    job = _create_job(
        config=config,
        internal_storage=internal_storage,
        executor_id=executor_id,
        job_id=job_id,
        func=map_function,
        iterdata=map_iterdata,
        chunksize=chunksize,
        runtime_meta=runtime_meta,
        runtime_memory=runtime_memory,
        extra_env=extra_env,
        include_modules=include_modules,
        exclude_modules=exclude_modules,
        execution_timeout=execution_timeout,
        host_job_meta=host_job_meta
    )

    if parts_per_object:
        job.parts_per_object = parts_per_object

    return job


def create_reduce_job(
    config: Dict[str, Any],
    internal_storage: Any,
    executor_id: str,
    reduce_job_id: str,
    reduce_function: Callable,
    map_job: Any,
    map_futures: List,
    runtime_meta: Mapping[str, Any],
    runtime_memory: Optional[int],
    obj_reduce_by_key: Any,
    extra_env: Optional[Mapping[str, Any]],
    include_modules: Optional[Iterable[str]],
    exclude_modules: Optional[Iterable[str]],
    execution_timeout: Optional[int] = None,
    extra_args: Any = None
) -> SimpleNamespace:
    """
    Creates a reduce job that applies a function over the futures of a map
    job, either over all of them at once or over one group per source object
    """
    host_job_meta = {'host_job_create_tstamp': time.time()}

    iterdata = [(map_futures, )]

    if hasattr(map_job, 'parts_per_object') and obj_reduce_by_key:
        offset = 0
        iterdata = []
        for total_partitions in map_job.parts_per_object:
            end = offset + total_partitions
            iterdata.append((map_futures[offset:end],))
            offset = end

    ext_env = {} if extra_env is None else extra_env.copy()
    ext_env['__LITHOPS_REDUCE_JOB'] = True

    iterdata = utils.verify_args(reduce_function, iterdata, extra_args)

    return _create_job(
        config=config,
        internal_storage=internal_storage,
        executor_id=executor_id,
        job_id=reduce_job_id,
        func=reduce_function,
        iterdata=iterdata,
        runtime_meta=runtime_meta,
        runtime_memory=runtime_memory,
        extra_env=ext_env,
        include_modules=include_modules,
        exclude_modules=exclude_modules,
        execution_timeout=execution_timeout,
        host_job_meta=host_job_meta
    )


def _function_name(func: Callable) -> str:
    if inspect.isfunction(func) or inspect.ismethod(func):
        return func.__name__
    return type(func).__name__


def _include_exclude_modules(
    config: Mapping[str, Any],
    include_modules: Optional[Iterable[str]],
    exclude_modules: Optional[Iterable[str]],
) -> Tuple[Optional[Set[str]], Set[str]]:
    """
    Merges the module filters given to the job with the ones in the config.
    An include set of None means that no module analysis is done at all
    """
    exclude_modules_cfg = config['lithops'].get('exclude_modules', [])
    include_modules_cfg = config['lithops'].get('include_modules', [])

    if isinstance(include_modules_cfg, str):
        if include_modules_cfg.lower() == 'none':
            include_modules_cfg = None
        else:
            raise ValueError(
                "'include_modules' parameter in config must be a list"
            )

    exc_modules = set()
    inc_modules = set()

    if exclude_modules_cfg:
        exc_modules.update(exclude_modules_cfg)
    if exclude_modules:
        exc_modules.update(exclude_modules)
    if include_modules_cfg is not None:
        inc_modules.update(include_modules_cfg)
    if include_modules_cfg is None and not include_modules:
        inc_modules = None
    if include_modules is not None and include_modules:
        inc_modules.update(include_modules)
    if include_modules is None:
        inc_modules = None

    return inc_modules, exc_modules


def _apply_mode_limits(
    job: SimpleNamespace,
    config: Mapping[str, Any],
    runtime_meta: Mapping[str, Any],
    runtime_memory: Optional[int]
) -> None:
    """
    Sets the memory and the timeout the job is allowed, clamping the execution
    timeout so that the job ends before the runtime is torn down under it
    """
    mode = config['lithops']['mode']
    backend = config['lithops']['backend']

    if mode == SERVERLESS:
        job.runtime_memory = (
            config[backend]['runtime_memory']
            if runtime_memory is None
            else runtime_memory
        )
        job.runtime_timeout = runtime_meta['runtime_timeout']
        if job.execution_timeout >= job.runtime_timeout:
            job.execution_timeout = job.runtime_timeout - 5
        return

    job.runtime_memory = None
    if mode == STANDALONE:
        runtime_timeout = config[STANDALONE]['hard_dismantle_timeout']
        if job.execution_timeout >= runtime_timeout:
            job.execution_timeout = runtime_timeout - 10
        return

    job.runtime_timeout = None


def _serialize_job(
    runtime_meta: Mapping[str, Any],
    func: Callable,
    iterdata: List,
    inc_modules: Optional[Set[str]],
    exc_modules: Set[str],
    host_job_meta: Dict[str, Any]
) -> SimpleNamespace:
    """
    Serializes the function, its module dependencies and the data, and records
    how long it took and how big the result is
    """
    serialize_start = time.time()
    serializer = SerializeIndependent(runtime_meta['preinstalls'])
    func_str, data_strs, mod_paths = _serialize_func_and_data(
        serializer, func, iterdata, inc_modules, exc_modules
    )
    module_data = create_module_data(mod_paths)
    func_module_str = pickle.dumps(
        {'func': func_str, 'module_data': module_data}, -1
    )
    data_size_bytes = sum(len(data_str) for data_str in data_strs)

    host_job_meta['host_job_serialize_time'] = round(
        time.time() - serialize_start, 6
    )
    host_job_meta['func_data_size_bytes'] = data_size_bytes
    host_job_meta['func_module_size_bytes'] = len(func_module_str)

    return SimpleNamespace(
        func_str=func_str,
        data_strs=data_strs,
        data_size_bytes=data_size_bytes,
        mod_paths=mod_paths,
        module_data=module_data,
        func_module_str=func_module_str
    )


def _upload_function(
    internal_storage: Any,
    job: SimpleNamespace,
    serialized: SimpleNamespace,
    host_job_meta: Dict[str, Any],
    prefix: str
) -> None:
    """
    Uploads the serialized function and its modules to the storage backend,
    unless this executor already uploaded an identical one
    """
    function_hash = hashlib.md5(serialized.func_module_str).hexdigest()
    job.func_key = create_func_key(job.executor_id, function_hash)

    if job.func_key in FUNCTION_CACHE:
        logger.debug(f'{prefix} - Function and modules found in local cache')
        host_job_meta['host_func_upload_time'] = 0
        return

    logger.debug(
        f'{prefix} - Uploading function and modules to the storage backend'
    )
    upload_start = time.time()
    internal_storage.put_func(job.func_key, serialized.func_module_str)
    host_job_meta['host_func_upload_time'] = round(
        time.time() - upload_start, 6
    )
    FUNCTION_CACHE.add(job.func_key)


def _bundle_function_in_runtime(
    job: SimpleNamespace,
    func: Callable,
    serialized: SimpleNamespace,
    host_job_meta: Dict[str, Any]
) -> None:
    """
    Writes the function and its modules to a local directory, for backends
    that build them into the runtime image instead of uploading them
    """
    with open(func.__code__.co_filename, 'rb') as fid:
        function_hash = hashlib.md5(fid.read()).hexdigest()[:16]
    mod_hash = hashlib.md5(
        repr(sorted(serialized.mod_paths)).encode('utf-8')
    ).hexdigest()[:16]

    job.func_key = func_key_suffix
    # The uuid identifies the runtime image that carries this exact function
    job.ext_runtime_uuid = f'{function_hash}{mod_hash}'
    job.local_tmp_dir = os.path.join(CUSTOM_RUNTIME_DIR, job.ext_runtime_uuid)
    _store_func_and_modules(
        job.local_tmp_dir, job.func_key, serialized.func_str,
        serialized.module_data
    )
    host_job_meta['host_func_upload_time'] = 0


def _attach_data(
    config: Mapping[str, Any],
    internal_storage: Any,
    job: SimpleNamespace,
    serialized: SimpleNamespace,
    host_job_meta: Dict[str, Any],
    prefix: str
) -> None:
    """
    Uploads the data of the job to the storage backend, or leaves it in the
    job so that it travels inside the invocation payload when it is small
    """
    fits_in_payload = all(
        (len(data_str) * job.chunksize) <= MAX_DATA_IN_PAYLOAD
        for data_str in serialized.data_strs
    )
    is_batch = (
        config['lithops']['backend_type'] == utils.BackendType.BATCH.value
    )

    if fits_in_payload and not is_batch:
        logger.debug(
            f'{prefix} - Data per activation is < '
            f'{utils.sizeof_fmt(MAX_DATA_IN_PAYLOAD)}. '
            'Passing data through invocation payload'
        )
        job.data_key = None
        job.data_byte_ranges = None
        job.data_byte_strs = serialized.data_strs
        host_job_meta['host_data_upload_time'] = 0
        return

    logger.debug(f'{prefix} - Uploading data to the storage backend')
    job.data_key = create_data_key(job.executor_id, job.job_id)
    data_bytes, job.data_byte_ranges = utils.agg_data(serialized.data_strs)
    upload_start = time.time()
    internal_storage.put_data(job.data_key, data_bytes)
    host_job_meta['host_data_upload_time'] = round(
        time.time() - upload_start, 6
    )


def _create_job(
    config: Dict[str, Any],
    internal_storage: Any,
    executor_id: str,
    job_id: str,
    func: Callable,
    iterdata: List,
    runtime_meta: Mapping[str, Any],
    runtime_memory: Optional[int],
    extra_env: Optional[Mapping[str, Any]],
    include_modules: Optional[Iterable[str]],
    exclude_modules: Optional[Iterable[str]],
    execution_timeout: Optional[int],
    host_job_meta: Dict[str, Any],
    chunksize: Optional[int] = None
) -> SimpleNamespace:
    """
    Creates a new job, uploading its function and its data so that the
    invoker only has to hand the workers a reference to them
    """
    ext_env = {} if extra_env is None else extra_env.copy()
    if ext_env:
        ext_env = utils.convert_bools_to_string(ext_env)
        logger.debug(f'Extra environment vars {ext_env}')

    backend = config['lithops']['backend']
    prefix = utils.log_prefix(executor_id, job_id)

    job = SimpleNamespace()
    job.chunksize = (
        config['lithops']['chunksize'] if chunksize is None else chunksize
    )
    job.worker_processes = config[backend]['worker_processes']
    job.execution_timeout = (
        config['lithops']['execution_timeout']
        if execution_timeout is None
        else execution_timeout
    )
    job.executor_id = executor_id
    job.job_id = job_id
    job.job_key = create_job_key(job.executor_id, job.job_id)
    job.extra_env = ext_env
    job.function_name = _function_name(func)
    job.total_calls = len(iterdata)

    _apply_mode_limits(job, config, runtime_meta, runtime_memory)

    inc_modules, exc_modules = _include_exclude_modules(
        config, include_modules, exclude_modules
    )

    logger.debug(f'{prefix} - Serializing function and data')
    serialized = _serialize_job(
        runtime_meta, func, iterdata, inc_modules, exc_modules, host_job_meta
    )

    data_limit = config['lithops'].get('data_limit', MAX_AGG_DATA_SIZE)
    if data_limit and serialized.data_size_bytes > data_limit * 1024**2:
        raise Exception(
            f'{prefix} - Total data exceeded maximum size '
            f'of {utils.sizeof_fmt(data_limit * 1024**2)}'
        )

    if config[backend].get('runtime_include_function', False):
        _bundle_function_in_runtime(job, func, serialized, host_job_meta)
    else:
        _upload_function(
            internal_storage, job, serialized, host_job_meta, prefix
        )

    _attach_data(
        config, internal_storage, job, serialized, host_job_meta, prefix
    )

    host_job_meta['host_job_created_time'] = round(
        time.time() - host_job_meta['host_job_create_tstamp'], 6
    )
    job.metadata = host_job_meta

    return job


def _store_func_and_modules(
    job_tmp_dir: str,
    func_key: str,
    func_str: bytes,
    module_data: Optional[Dict[str, str]]
) -> None:
    """
    Stores a function and its modules in a local directory, for the custom
    runtime build to pick them up
    """
    os.makedirs(job_tmp_dir, exist_ok=True)

    with open(os.path.join(job_tmp_dir, func_key), 'wb') as fid:
        pickle.dump({'func': func_str}, fid, -1)

    if module_data:
        logger.debug('Writing Function dependencies to local disk')
        write_module_data(os.path.join(job_tmp_dir, 'modules'), module_data)

    logger.debug('Finished storing function and modules')
