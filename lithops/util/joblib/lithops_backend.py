#
# (C) Copyright Cloudlab URV 2021
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
import os
import pickle
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from multiprocessing.pool import ThreadPool
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import diskcache
from numpy import ndarray

from joblib import Parallel
from joblib._parallel_backends import MultiprocessingBackend
from joblib.pool import PicklingPool

from lithops.multiprocessing import Pool, cpu_count
from lithops.multiprocessing import config as mp_config
from lithops.constants import LITHOPS_TEMP_DIR
from lithops.storage import Storage

logger = logging.getLogger(__name__)

# A call, as joblib hands it over: (function, args, kwargs), optionally
# followed by the positions of the arguments replaced by a cloud object
Call = Tuple

# Upper bound for the threads that upload and download the shared arguments:
# there is one argument per thread, and a batch can hold a great many
MAX_UPLOAD_THREADS = 32

# Tells a cached None apart from a key that is not cached
_CACHE_MISS = object()


class LithopsBackend(MultiprocessingBackend):
    """
    joblib backend that runs the tasks of a batch through Lithops instead of
    a local process pool, uploading the arguments they share only once
    """

    supports_timeout = True
    supports_sharedmem = False
    supports_retrieve_callback = False

    def __init__(
        self,
        nesting_level: Optional[int] = None,
        inner_max_num_threads: Optional[int] = None,
        lithops_args: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        self.lithops_args = lithops_args
        self.eff_n_jobs = None
        self.prefer = None

        if lithops_args:
            # The batches run on lithops.multiprocessing, which takes its
            # executor arguments from this process-wide parameter
            mp_config.set_parameter(mp_config.LITHOPS_CONFIG, lithops_args)
        super().__init__(
            nesting_level=nesting_level,
            inner_max_num_threads=inner_max_num_threads,
            **kwargs
        )

    def configure(
        self,
        n_jobs: int = 1,
        parallel: Optional[Parallel] = None,
        prefer: Optional[str] = None,
        require: Optional[str] = None,
        **memmappingpool_args
    ):
        """
        Configures the backend, making the Lithops Pool the one that joblib
        instantiates to run the tasks
        """
        self.prefer = prefer
        # PicklingPool inherits Pool from multiprocessing.pool. This patch
        # changes that inheritance to lithops.multiprocessing.Pool
        PicklingPool.__bases__ = (Pool,)

        if n_jobs == -1:
            n_jobs = self.effective_n_jobs(n_jobs)

        return super().configure(
            n_jobs,
            parallel,
            prefer,
            require,
            **memmappingpool_args
        )

    def effective_n_jobs(self, n_jobs: int) -> int:
        """
        Resolves how many jobs to run in parallel, asking the Lithops backend
        only once for the CPUs that -1 stands for
        """
        eff_n_jobs = super().effective_n_jobs(n_jobs)
        if n_jobs == -1:
            self.eff_n_jobs = self.eff_n_jobs or cpu_count()
            eff_n_jobs = self.eff_n_jobs
        return eff_n_jobs

    def start_call(self):
        """Forces a single map() instead of one apply_async() per task"""
        self.parallel._cached_effective_n_jobs = 1
        self.parallel.pre_dispatch = 'all'

    def compute_batch_size(self) -> int:
        """Keeps every task in one batch, so that a call is a single map"""
        return int(1e6)

    def submit(self, func, callback=None):
        """
        Schedules a batch of calls, uploading the arguments they have in
        common only once.

        joblib renamed this hook from apply_async to submit, and the
        multiprocessing backend this one extends carries its own submit, so
        without this override joblib would hand the batch straight to the pool
        wrapped in a class the pool does not know what to do with
        """
        mem_opt_calls = find_shared_objects(func.items)
        pool = self._get_pool()
        if self.prefer == "threads":
            return pool.apply_async(
                handle_call_threads, (mem_opt_calls,), callback=callback
            )
        return pool.starmap_async(
            handle_call_process, mem_opt_calls, callback=callback
        )

    # The name joblib used before 1.4
    apply_async = submit


def _wait_all(futures: Iterable[Future]) -> None:
    """Waits for every future, re-raising whatever they raised"""
    for fut in futures:
        fut.result()


def _storage_for_the_pool() -> Storage:
    """
    Builds a storage client from the parameters the pool runs with, so that a
    shared argument lands where the workers of that pool will look for it and
    not in whatever storage this machine has configured by default
    """
    lithops_conf = mp_config.get_parameter(mp_config.LITHOPS_CONFIG) or {}
    return Storage(
        config=lithops_conf.get('config'),
        backend=lithops_conf.get('storage'),
    )


def _index_arguments_by_identity(calls: Sequence[Call]) -> Dict[int, List]:
    """
    Groups every argument of every call by object identity. Each entry holds
    the object itself followed by the (call, position) pairs it appears in,
    where a position is an index for an arg and a name for a kwarg
    """
    record = {}
    for i, call in enumerate(calls):
        arguments = list(enumerate(call[1])) + list(call[2].items())
        for idx_or_key, arg in arguments:
            record.setdefault(id(arg), [arg]).append((i, idx_or_key))
    return record


def _proxy_argument(call: List, idx_or_key, cloud_object) -> None:
    """
    Replaces one argument of a call with a cloud object, and records its
    position so that the worker knows which arguments to fetch back
    """
    if isinstance(idx_or_key, str):
        call[2][idx_or_key] = cloud_object
    else:
        args_as_list = list(call[1])
        args_as_list[idx_or_key] = cloud_object
        call[1] = tuple(args_as_list)

    # The 4th element only exists once a first argument has been proxied
    try:
        call[3].append(idx_or_key)
    except IndexError:
        call.append([idx_or_key])


def find_shared_objects(calls: Sequence[Call]) -> List[Call]:
    """
    Replaces the arguments that several calls share with a proxy to a single
    cloud object, so that they travel to the workers only once
    """
    logger.info('Optimizing shared data between tasks')

    record = _index_arguments_by_identity(calls)
    calls = [list(item) for item in calls]
    if not record:
        return [tuple(item) for item in calls]

    storage = None
    storage_lock = threading.Lock()
    # Two shared arguments of the same call are proxied by two threads, and
    # each one rewrites the args tuple of every call it appears in
    calls_lock = threading.Lock()

    def get_storage():
        # Created on first use and shared, so that the uploading threads do
        # not build one client each
        nonlocal storage
        with storage_lock:
            if storage is None:
                storage = _storage_for_the_pool()
            return storage

    def put_arg_obj(positions):
        obj = positions.pop(0)
        if len(positions) <= 1 or not consider_sharing(obj):
            return

        logger.debug(f'Proxying {type(obj)}')
        obj_bin = pickle.dumps(obj)
        cloud_object = get_storage().put_cloudobject(obj_bin)

        with calls_lock:
            for call_n, idx_or_key in positions:
                _proxy_argument(calls[call_n], idx_or_key, cloud_object)

    workers = min(len(record), MAX_UPLOAD_THREADS)
    with ThreadPoolExecutor(max_workers=workers) as thread_pool:
        _wait_all([
            thread_pool.submit(put_arg_obj, positions)
            for positions in record.values()
        ])

    return [tuple(item) for item in calls]


def handle_call_threads(mem_opt_calls: Sequence[Call]) -> List[Any]:
    """Runs a whole batch of calls in this worker, one thread each"""
    with ThreadPool(processes=max(1, len(mem_opt_calls))) as pool:
        return list(pool.starmap(handle_call_process, mem_opt_calls))


def handle_call_process(
    func: Callable,
    args: Tuple,
    kwargs: Dict[str, Any],
    proxy_positions: Optional[List] = None
) -> Any:
    """Runs a single call, fetching the arguments that were proxied"""
    if proxy_positions:
        args, kwargs = replace_with_values(args, kwargs, proxy_positions)
    return func(*args, **kwargs)


def replace_with_values(
    args: Tuple,
    kwargs: Dict[str, Any],
    proxy_positions: List
) -> Tuple[List, Dict[str, Any]]:
    """
    Downloads the cloud objects standing in for the proxied arguments, using
    a local disk cache shared by every task that runs in the same worker
    """
    args_as_list = list(args)
    cache_dir = os.path.join(LITHOPS_TEMP_DIR, 'cache')

    def get_arg_obj(idx_or_key, cache):
        if isinstance(idx_or_key, str):
            obj_id = kwargs[idx_or_key]
        else:
            obj_id = args_as_list[idx_or_key]

        # Read in one call: asking whether the key is there and then reading
        # it is a race. Every task of this runtime shares the cache directory,
        # and a value too big to sit inline is a file of its own, so the row
        # can be there while the file is not readable yet
        obj = cache.get(obj_id, default=_CACHE_MISS)
        if obj is _CACHE_MISS:
            logger.debug(f'Get {obj_id} (arg {idx_or_key}) from storage')
            storage = Storage()
            obj_bin = storage.get_cloudobject(obj_id)
            obj = pickle.loads(obj_bin)
            cache[obj_id] = obj
        else:
            logger.debug(f'Get {obj_id} (arg {idx_or_key}) from cache')

        if isinstance(idx_or_key, str):
            kwargs[idx_or_key] = obj
        else:
            args_as_list[idx_or_key] = obj

    with diskcache.Cache(cache_dir) as cache:
        workers = min(max(1, len(proxy_positions)), MAX_UPLOAD_THREADS)
        with ThreadPoolExecutor(max_workers=workers) as thread_pool:
            _wait_all([
                thread_pool.submit(get_arg_obj, idx_or_key, cache)
                for idx_or_key in proxy_positions
            ])
    return args_as_list, kwargs


def consider_sharing(obj: Any) -> bool:
    """Tells whether an object is worth uploading as a shared cloud object"""
    return isinstance(obj, (ndarray, list))
