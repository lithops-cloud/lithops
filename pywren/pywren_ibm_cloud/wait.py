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

import random
import time
from multiprocessing.pool import ThreadPool


ALL_COMPLETED = 1
ANY_COMPLETED = 2
ALWAYS = 3


def wait(fs, executor_id, storage_handler, throw_except=True, verbose=False,
         return_when=ALL_COMPLETED, THREADPOOL_SIZE=64, WAIT_DUR_SEC=4):
    """
    Wait for the Future instances `fs` to complete. Returns a 2-tuple of
    lists. The first list contains the futures that completed
    (finished or cancelled) before the wait completed. The second
    contains uncompleted futures.

    :param fs: A list of futures.
    :param executor_id: executor's ID.
    :param storage_handler: Storage handler to poll cloud storage.
    :param return_when: One of `ALL_COMPLETED`, `ANY_COMPLETED`, `ALWAYS`
    :param THREADPOOL_SIZE: Number of threads to use. Default 64
    :param WAIT_DUR_SEC: Time interval between each check.
    :return: `(fs_dones, fs_notdones)`
        where `fs_dones` is a list of futures that have completed
        and `fs_notdones` is a list of futures that have not completed.
    :rtype: 2-tuple of lists

    Usage
      >>> futures = pwex.map(foo, data)
      >>> dones, not_dones = wait(futures, ALL_COMPLETED)
      >>> # not_dones should be an empty list.
      >>> results = [f.result() for f in dones]

    """
    N = len(fs)
    # These are performance-related settings that we may eventually
    # want to expose to end users:
    MAX_DIRECT_QUERY_N = 16
    RETURN_EARLY_N = 16

    if return_when == ALL_COMPLETED:
        result_count = 0
        while result_count < N:

            fs_dones, fs_notdones = _wait(fs, executor_id,
                                          storage_handler,
                                          throw_except,
                                          verbose,
                                          RETURN_EARLY_N,
                                          MAX_DIRECT_QUERY_N,
                                          THREADPOOL_SIZE)
            result_count = len(fs_dones)

            if result_count == N:
                return fs_dones, fs_notdones
            else:
                time.sleep(WAIT_DUR_SEC)

    elif return_when == ANY_COMPLETED:
        while True:
            fs_dones, fs_notdones = _wait(fs, executor_id,
                                          storage_handler,
                                          throw_except,
                                          verbose,
                                          RETURN_EARLY_N,
                                          MAX_DIRECT_QUERY_N,
                                          THREADPOOL_SIZE)

            if len(fs_dones) != 0:
                return fs_dones, fs_notdones
            else:
                time.sleep(WAIT_DUR_SEC)

    elif return_when == ALWAYS:
        return _wait(fs, executor_id,
                     storage_handler,
                     RETURN_EARLY_N,
                     MAX_DIRECT_QUERY_N,
                     THREADPOOL_SIZE)
    else:
        raise ValueError()


def _wait(fs, executor_id, storage_handler, throw_except, verbose, return_early_n,
          max_direct_query_n, random_query=False, THREADPOOL_SIZE=16):
    """
    internal function that performs the majority of the WAIT task
    work.

    For the list of futures fn, we will check at a minimum `max_direct_query_n`
    futures at least once. Internally we :
    1. use list() to quickly get a list of which ones are done (but
    list can be behind due to eventual consistency issues)
    2. then individually call get_status on at most `max_direct_query_n` returning
       early if we have found at least `return_early_n`

    This can mitigate the stragglers.

    random_query decides whether we get the fs in the order they are presented
    or in a random order.
    """
    # get all the futures that are not yet done
    not_done_futures = [f for f in fs if not f.done]
    if len(not_done_futures) == 0:
        return fs, []

    # note this returns everything done, so we have to figure out
    # the intersection of those that are done
    callids_done_in_callset = set(storage_handler.get_callset_status(executor_id))
    not_done_call_ids = set([(f.callgroup_id, f.call_id) for f in not_done_futures])
    done_call_ids = not_done_call_ids.intersection(callids_done_in_callset)

    not_done_call_ids = not_done_call_ids - done_call_ids

    still_not_done_futures = [f for f in not_done_futures if ((f.callgroup_id, f.call_id) in not_done_call_ids)]

    #def fetch_future_status(f):
    #    status_key = storage_utils.create_status_key(storage_handler.prefix, f.executor_id, f.callgroup_id, f.call_id)
    #    return storage_handler.object_exists(status_key)

    def fetch_future_status(f):
        return storage_handler.get_call_status(f.executor_id, f.callgroup_id, f.call_id)

    pool = ThreadPool(THREADPOOL_SIZE)

    # now try up to max_direct_query_n direct status queries, quitting once
    # we have return_n done.
    query_count = 0
    max_queries = min(max_direct_query_n, len(still_not_done_futures))

    if random_query:
        random.shuffle(still_not_done_futures)

    while query_count < max_queries:

        if len(done_call_ids) >= return_early_n:
            break
        num_to_query_at_once = THREADPOOL_SIZE
        fs_to_query = still_not_done_futures[query_count:query_count + num_to_query_at_once]

        fs_statuses = pool.map(fetch_future_status, fs_to_query)

        callids_found = [(fs_to_query[i].callgroup_id, fs_to_query[i].call_id) for i in range(len(fs_to_query))
                         if fs_statuses[i] is not None]

        done_call_ids = done_call_ids.union(set(callids_found))

        query_count += len(fs_to_query)

    # now we walk through all the original queries and get
    # the ones that are actually done.
    fs_dones = []
    fs_notdones = []
    f_to_wait_on = []
    for f in fs:
        if f.done:
            # done, don't need to do anything
            fs_dones.append(f)
        else:
            if (f.callgroup_id, f.call_id) in done_call_ids:
                f_to_wait_on.append(f)
                fs_dones.append(f)
            else:
                fs_notdones.append(f)

    def get_result(f):
        f.result(throw_except=throw_except, verbose=verbose, storage_handler=storage_handler)
    pool.map(get_result, f_to_wait_on)

    pool.close()
    pool.join()

    # Check for redirections
    fs_dones_redirected = [f for f in fs_dones if not f.done]
    fs_dones = [f for f in fs_dones if f.done]
    fs_notdones.extend(fs_dones_redirected)

    return fs_dones, fs_notdones
