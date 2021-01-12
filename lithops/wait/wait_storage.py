#
# Copyright 2018 PyWren Team
# Copyright IBM Corp. 2020
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

import sys
import json
import time
import pickle
import random
import logging
import concurrent.futures
from threading import Thread
from tblib import pickling_support

from lithops.storage.utils import create_status_key
from lithops.constants import JOBS_PREFIX


pickling_support.install()
logger = logging.getLogger(__name__)

ALL_COMPLETED = 1
ANY_COMPLETED = 2
ALWAYS = 3


def wait_storage(fs, internal_storage, download_results=False,
                 throw_except=True, pbar=None, return_when=ALL_COMPLETED,
                 THREADPOOL_SIZE=128, WAIT_DUR_SEC=1):
    """
    Wait for the Future instances `fs` to complete. Returns a 2-tuple of
    lists. The first list contains the futures that completed
    (finished or cancelled) before the wait completed. The second
    contains uncompleted futures.

    :param futures: A list of futures.
    :param executor_id: executor's ID.
    :param internal_storage: Storage handler to poll cloud storage.
    :param download_results: Download the results: Ture, False.
    :param pbar: Progress bar.
    :param return_when: One of `ALL_COMPLETED`, `ANY_COMPLETED`, `ALWAYS`
    :param THREADPOOL_SIZE: Number of threads to use. Default 128
    :param WAIT_DUR_SEC: Time interval between each check.

    :return: `(fs_dones, fs_notdones)`
        where `fs_dones` is a list of futures that have completed
        and `fs_notdones` is a list of futures that have not completed.
    :rtype: 2-tuple of lists
    """
    N = len(fs)

    # These are performance-related settings that we may eventually
    # want to expose to end users:
    MAX_DIRECT_QUERY_N = 64
    RETURN_EARLY_N = 32
    RANDOM_QUERY = False

    running_futures = set()
    ftc = Thread(target=_future_timeout_checker,
                 args=(fs, running_futures, internal_storage, throw_except))
    ftc.daemon = True
    ftc.start()

    if return_when == ALL_COMPLETED:

        result_count = 0

        while result_count < N:
            fs_dones, fs_notdones = _wait_storage(fs,
                                                  running_futures,
                                                  internal_storage,
                                                  download_results,
                                                  throw_except,
                                                  RETURN_EARLY_N,
                                                  MAX_DIRECT_QUERY_N,
                                                  pbar=pbar,
                                                  random_query=RANDOM_QUERY,
                                                  THREADPOOL_SIZE=THREADPOOL_SIZE)
            N = len(fs)
            result_count = len(fs_dones)
            if result_count == N:
                return fs_dones, fs_notdones
            else:
                sleep = WAIT_DUR_SEC
                if fs_dones:
                    sleep = max(float(round(WAIT_DUR_SEC-((len(fs_dones)/N)*WAIT_DUR_SEC), 3)), 0)
                #print("Sleep:", sleep)
                time.sleep(sleep)
                #print('---')

    elif return_when == ANY_COMPLETED:
        while True:
            fs_dones, fs_notdones = _wait_storage(fs,
                                                  running_futures,
                                                  internal_storage,
                                                  download_results,
                                                  throw_except,
                                                  RETURN_EARLY_N,
                                                  MAX_DIRECT_QUERY_N,
                                                  random_query=RANDOM_QUERY,
                                                  THREADPOOL_SIZE=THREADPOOL_SIZE)

            if len(fs_dones) != 0:
                return fs_dones, fs_notdones
            else:
                time.sleep(WAIT_DUR_SEC)

    elif return_when == ALWAYS:
        return _wait_storage(fs,
                             running_futures,
                             internal_storage,
                             download_results,
                             throw_except,
                             RETURN_EARLY_N,
                             MAX_DIRECT_QUERY_N,
                             random_query=RANDOM_QUERY,
                             THREADPOOL_SIZE=THREADPOOL_SIZE)
    else:
        raise ValueError()


def _wait_storage(fs, running_futures, internal_storage, download_results, throw_except,
                  return_early_n, max_direct_query_n, pbar=None,
                  random_query=False, THREADPOOL_SIZE=128):
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
    if download_results:
        not_done_futures = [f for f in fs if not f.done]
    else:
        not_done_futures = [f for f in fs if not (f.ready or f.done)]

    if len(not_done_futures) == 0:
        return fs, []

    present_jobs = {(f.executor_id, f.job_id) for f in not_done_futures}

    still_not_done_futures = []
    while present_jobs:
        executor_id, job_id = present_jobs.pop()
        # note this returns everything done, so we have to figure out
        # the intersection of those that are done
        current_time = time.time()
        callids_running_in_job, callids_done_in_job = internal_storage.get_job_status(executor_id, job_id)
        for f in not_done_futures:
            for call in callids_running_in_job:
                if (f.executor_id, f.job_id, f.call_id) == call[0]:
                    if f.invoked and f not in running_futures:
                        f.activation_id = call[1]
                        f._call_status = {'type': '__init__',
                                          'activation_id': call[1],
                                          'start_time': current_time}
                        f.status(throw_except=throw_except, internal_storage=internal_storage)
                        running_futures.add(f)

        # print('Time getting job status: {} - Running: {} - Done: {}'
        #       .format(round(time.time()-current_time, 3),  len(callids_running_in_job), len(callids_done_in_job)))

        not_done_call_ids = set([(f.executor_id, f.job_id, f.call_id) for f in not_done_futures])
        done_call_ids = not_done_call_ids.intersection(callids_done_in_job)
        not_done_call_ids = not_done_call_ids - done_call_ids
        still_not_done_futures += [f for f in not_done_futures if ((f.executor_id, f.job_id, f.call_id) in not_done_call_ids)]

    def fetch_future_status(f):
        return internal_storage.get_call_status(f.executor_id, f.job_id, f.call_id)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=THREADPOOL_SIZE)

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

        fs_statuses = list(pool.map(fetch_future_status, fs_to_query))

        callids_found = [(fs_to_query[i].executor_id, fs_to_query[i].job_id, fs_to_query[i].call_id)
                         for i in range(len(fs_to_query)) if fs_statuses[i] is not None]

        # print('FOUND:', callids_found, len(callids_found))

        done_call_ids = done_call_ids.union(set(callids_found))
        query_count += len(fs_to_query)

    # now we walk through all the original queries and get
    # the ones that are actually done.
    fs_dones = []
    fs_notdones = []
    fs_to_wait_on = []
    for f in fs:
        if (download_results and f.done) or (not download_results and (f.ready or f.done)):
            # done, don't need to do anything
            fs_dones.append(f)
        else:
            if (f.executor_id, f.job_id, f.call_id) in done_call_ids:
                fs_to_wait_on.append(f)
                fs_dones.append(f)
            else:
                fs_notdones.append(f)

    def get_result(f):
        if f.running:
            f._call_status = None
        f.result(throw_except=throw_except, internal_storage=internal_storage)

    def get_status(f):
        if f.running:
            f._call_status = None
        f.status(throw_except=throw_except, internal_storage=internal_storage)

    if download_results:
        list(pool.map(get_result, fs_to_wait_on))
    else:
        list(pool.map(get_status, fs_to_wait_on))

    pool.shutdown()

    if pbar:
        for f in fs_to_wait_on:
            if (download_results and f.done) or (not download_results and (f.ready or f.done)):
                pbar.update(1)
        pbar.refresh()

    # Check for new futures
    new_futures = [f.result() for f in fs_to_wait_on if f.futures]
    for futures in new_futures:
        fs.extend(futures)
        if pbar:
            pbar.total = pbar.total + len(futures)
            pbar.refresh()

    return fs_dones, fs_notdones


def _future_timeout_checker(futures,
                            running_futures,
                            internal_storage,
                            throw_except):
    should_run = True
    while should_run:
        try:
            while True:
                current_time = time.time()
                for fut in running_futures:
                    if fut.running and fut._call_status:
                        fut_timeout = fut._call_status['start_time'] + fut.execution_timeout + 5
                        if current_time > fut_timeout:
                            msg = 'The function did not run as expected.'
                            raise TimeoutError('HANDLER', msg)

                if all([not f.running for f in running_futures])\
                   and len(futures) == len(running_futures):
                    should_run = False
                    break
                time.sleep(5)
        except TimeoutError:
            # generate fake TimeoutError call status
            pickled_exception = str(pickle.dumps(sys.exc_info()))
            call_status = {'type': '__end__',
                           'exception': True,
                           'exc_info': pickled_exception,
                           'executor_id': fut.executor_id,
                           'job_id': fut.job_id,
                           'call_id': fut.call_id,
                           'activation_id': fut.activation_id}
            status_key = create_status_key(JOBS_PREFIX, fut.executor_id, fut.job_id, fut.call_id)
            dmpd_response_status = json.dumps(call_status)
            internal_storage.put_data(status_key, dmpd_response_status)
            if throw_except:
                should_run = False
        except Exception:
            time.sleep(5)
