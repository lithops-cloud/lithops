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
import diskcache
from numpy import ndarray
from multiprocessing.pool import ThreadPool
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from joblib import Parallel
from joblib._parallel_backends import MultiprocessingBackend
from joblib.pool import PicklingPool
from joblib.parallel import register_parallel_backend

from lithops.multiprocessing import Pool, cpu_count
from lithops.constants import LITHOPS_TEMP_DIR
from lithops.storage import Storage

logger = logging.getLogger(__name__)


def register_lithops():
    """ Register Lithops Backend to be called with parallel_backend("lithops"). """
    register_parallel_backend("lithops", LithopsBackend)


class LithopsBackend(MultiprocessingBackend):
    """A ParallelBackend which will use a multiprocessing.Pool.
    Will introduce some communication and memory overhead when exchanging
    input and output data with the with the worker Python processes.
    However, does not suffer from the Python Global Interpreter Lock.
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
        """Make Lithops Pool the father class of PicklingPool. PicklingPool is a
        father class that inherits Pool from multiprocessing.pool. The next
        line is a patch, which changes the inheritance of Pool to be from
        lithops.multiprocessing.pool
        """
        self.prefer = prefer
        PicklingPool.__bases__ = (Pool,)

        if n_jobs == -1:
            n_jobs = self.effective_n_jobs(n_jobs)

        eff_n_jobs = super(LithopsBackend, self).configure(
            n_jobs,
            parallel,
            prefer,
            require,
            **memmappingpool_args
        )
        return eff_n_jobs

    def effective_n_jobs(self, n_jobs):
        eff_n_jobs = super(LithopsBackend, self).effective_n_jobs(n_jobs)
        if n_jobs == -1:
            self.eff_n_jobs = self.eff_n_jobs or cpu_count()
            eff_n_jobs = self.eff_n_jobs
        return eff_n_jobs

    def start_call(self):
        """This is a workaround to make "batch size" working properly
        and invoke all the tasks using a single map() instead of
        individual apply_async()"""
        self.parallel._cached_effective_n_jobs = 1
        self.parallel.pre_dispatch = 'all'

    def compute_batch_size(self):
        return int(1e6)

    def apply_async(self, func, callback=None):
        """Schedule a func to be run"""
        mem_opt_calls = find_shared_objects(func.items)
        if self.prefer == "threads":
            return self._get_pool().apply_async(handle_call_threads, (mem_opt_calls, ), callback=callback)
        else:
            return self._get_pool().starmap_async(handle_call_process, mem_opt_calls, callback=callback)


def find_shared_objects(calls):
    # find and annotate repeated arguments
    logger.info('Optimizing shared data between tasks')

    record = {}
    for i, call in enumerate(calls):
        for j, arg in enumerate(call[1]):
            if id(arg) in record:
                record[id(arg)].append((i, j))
            else:
                record[id(arg)] = [arg, (i, j)]

        for k, v in call[2].items():
            if id(v) in record:
                record[id(v)].append((i, k))
            else:
                record[id(v)] = [v, (i, k)]

    # If we found multiple occurrences of one object, then
    # store it in shared memory, pass a proxy as a value
    calls = [list(item) for item in calls]

    storage = Storage()
    thread_pool = ThreadPoolExecutor(max_workers=len(record))

    def put_arg_obj(positions):
        obj = positions.pop(0)
        if len(positions) > 1 and consider_sharing(obj):
            logger.debug('Proxying {}'.format(type(obj)))
            obj_bin = pickle.dumps(obj)
            cloud_object = storage.put_cloudobject(obj_bin)

            for pos in positions:
                call_n, idx_or_key = pos
                call = calls[call_n]

                if isinstance(idx_or_key, str):
                    call[2][idx_or_key] = cloud_object
                else:
                    args_as_list = list(call[1])
                    args_as_list[idx_or_key] = cloud_object
                    call[1] = tuple(args_as_list)

                try:
                    call[3].append(idx_or_key)
                except IndexError:
                    call.append([idx_or_key])

    fut = []
    for positions in record.values():
        f = thread_pool.submit(put_arg_obj, positions)
        fut.append(f)
    [f.result() for f in fut]

    return [tuple(item) for item in calls]


def handle_call_threads(mem_opt_calls):
    with ThreadPool(processes=len(mem_opt_calls)) as pool:
        results = pool.starmap(handle_call_process, mem_opt_calls)

    return list(results)


def handle_call_process(func, args, kwargs, proxy_positions=[]):
    if len(proxy_positions) > 0:
        args, kwargs = replace_with_values(args, kwargs, proxy_positions)

    return func(*args, **kwargs)


def replace_with_values(args, kwargs, proxy_positions):
    args_as_list = list(args)
    thread_pool = ThreadPoolExecutor(max_workers=len(proxy_positions))
    cache = diskcache.Cache(os.path.join(LITHOPS_TEMP_DIR, 'cache'))

    def get_arg_obj(idx_or_key):
        if isinstance(idx_or_key, str):
            obj_id = kwargs[idx_or_key]
        else:
            obj_id = args_as_list[idx_or_key]

        if obj_id in cache:
            logger.debug('Get {} (arg {}) from cache'.format(obj_id, idx_or_key))
            obj = cache[obj_id]
        else:
            logger.debug('Get {} (arg {}) from storage'.format(obj_id, idx_or_key))
            storage = Storage()
            obj_bin = storage.get_cloudobject(obj_id)
            obj = pickle.loads(obj_bin)
            cache[obj_id] = obj

        if isinstance(idx_or_key, str):
            kwargs[idx_or_key] = obj
        else:
            args_as_list[idx_or_key] = obj

    fut = []
    for idx_or_key in proxy_positions:
        f = thread_pool.submit(get_arg_obj, idx_or_key)
        fut.append(f)
    [f.result() for f in fut]
    return args_as_list, kwargs


def consider_sharing(obj):
    if isinstance(obj, (ndarray, list)):  # TODO: some heuristic
        return True
    return False
