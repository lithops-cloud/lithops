#
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
import gc
import logging
from numpy import ndarray

from joblib._parallel_backends import ParallelBackendBase, PoolManagerMixin

from lithops.multiprocessing import Pool, Manager
from lithops.multiprocessing.managers import _builtin_types
from lithops.storage.cloud_proxy import os as cloudfs
from lithops.multiprocessing.managers import SyncManager, BaseProxy

logger = logging.getLogger(__name__)


class CloudValueProxy(BaseProxy):
    def __init__(self, typecode='Any', value=None, lock=True):
        super().__init__('CloudValue({})'.format(typecode))
        if value is not None:
            self.set(value)

        cloudfs.delete = lambda *x: [cloudfs.remove(path=xi) for xi in x]
        # Override redis client with a storage client
        self._client = self._ref._client = cloudfs
        self._ref.managed = True

    def get(self):
        with self._client.open(self._oid, 'rb') as obj:
            serialized = obj.read()
            return self._pickler.loads(serialized)

    def set(self, value):
        with self._client.open(self._oid, 'wb') as obj:
            serialized = self._pickler.dumps(value)
            obj.write(serialized)

    value = property(get, set)


_builtin_types.add('CloudValue')
SyncManager.register('CloudValue', CloudValueProxy)


class LithopsBackend(ParallelBackendBase, PoolManagerMixin):
    """A ParallelBackend which will use a multiprocessing.Pool.
    Will introduce some communication and memory overhead when exchanging
    input and output data with the with the worker Python processes.
    However, does not suffer from the Python Global Interpreter Lock.
    """

    # Environment variables to protect against bad situations when nesting
    JOBLIB_SPAWNED_PROCESS = "__JOBLIB_SPAWNED_PARALLEL__"

    supports_timeout = True
    supports_sharedmem = False

    def effective_n_jobs(self, n_jobs):
        """Determine the number of jobs which are going to run in parallel.
        This also checks if we are attempting to create a nested parallel
        loop.
        """
        # this must be 1 as we only want to create 1 LithopsExecutor()
        return 1

    def configure(self, n_jobs=1, parallel=None, prefer=None, require=None,
                  **memmappingpool_args):
        """Build a process or thread pool and return the number of workers"""

        n_jobs = self.effective_n_jobs(n_jobs)

        already_forked = int(os.environ.get(self.JOBLIB_SPAWNED_PROCESS, 0))
        if already_forked:
            raise ImportError(
                '[joblib] Attempting to do parallel computing '
                'without protecting your import on a system that does '
                'not support forking. To use parallel-computing in a '
                'script, you must protect your main loop using "if '
                "__name__ == '__main__'"
                '". Please see the joblib documentation on Parallel '
                'for more information')
        # Set an environment variable to avoid infinite loops
        os.environ[self.JOBLIB_SPAWNED_PROCESS] = '1'

        # Make sure to free as much memory as possible before forking
        gc.collect()
        self._pool = Pool()
        self.parallel = parallel

        return n_jobs

    def terminate(self):
        """Shutdown the process or thread pool"""
        super().terminate()
        if self.JOBLIB_SPAWNED_PROCESS in os.environ:
            del os.environ[self.JOBLIB_SPAWNED_PROCESS]

    def compute_batch_size(self):
        return int(1e6)

    def apply_async(self, func, callback=None):
        """Schedule a func to be run"""
        #return self._get_pool().map_async(handle_call, func.items, callback=callback) # bypass

        manager = Manager()
        manager.start()
        mem_opt_calls = find_shared_objects(func.items, manager)

        return self._get_pool().map_async(
            handle_call,
            mem_opt_calls,
            callback=Then(callback, manager.shutdown))


def find_shared_objects(calls, manager):
    # find and annotate repeated arguments
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

    for positions in record.values():
        obj = positions.pop(0)
        if len(positions) > 1 and consider_sharing(obj):
            #shared_object = manager.Value(obj.__class__.__name__) # redis
            shared_object = manager.CloudValue(obj.__class__.__name__)
            logger.debug('proxying: ' + repr(shared_object))
            shared_object.value = obj

            for pos in positions:
                call_n, idx_or_key = pos
                call = calls[call_n]

                if isinstance(idx_or_key, str):
                    call[2][idx_or_key] = shared_object
                else:
                    args_as_list = list(call[1])
                    args_as_list[idx_or_key] = shared_object
                    call[1] = tuple(args_as_list)

                try:
                    call[3].append(idx_or_key)
                except IndexError:
                    call.append([idx_or_key])

    return [tuple(item) for item in calls]


def handle_call(func, args, kwargs, proxy_positions=[]):
    if len(proxy_positions) > 0:
        args, kwargs = replace_with_values(args, kwargs, proxy_positions)

    return func(*args, **kwargs)


def replace_with_values(args, kwargs, proxy_positions):
    args_as_list = list(args)
    for idx_or_key in proxy_positions:
        if isinstance(idx_or_key, str):
            kwargs[idx_or_key] = kwargs[idx_or_key].value
        else:
            args_as_list[idx_or_key] = args_as_list[idx_or_key].value
    return args_as_list, kwargs


def consider_sharing(obj):
    if isinstance(obj, (ndarray, list)):    #TODO: some heuristic
        return True
    return False


class Then:
    def __init__(self, func, then):
        self.func = func
        self.then = then

    def __call__(self, *args, **kwargs):
        self.func(*args, **kwargs)
        self.then()
