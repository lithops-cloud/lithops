#
# Copyright Cloudlab URV 2021
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

import signal
import logging
import time
from functools import partial
from lithops.utils import is_unix_system, timeout_handler, is_notebook, is_lithops_worker
from lithops.storage import InternalStorage

ALL_COMPLETED = 1
ANY_COMPLETED = 2

logger = logging.getLogger(__name__)


def wait(fs, internal_storage=None, throw_except=True, timeout=None,
         return_when=ALL_COMPLETED, download_results=False,
         THREADPOOL_SIZE=128, WAIT_DUR_SEC=2, job_monitor=None):
    """
    Wait for the Future instances (possibly created by different Executor instances)
    given by fs to complete. Returns a named 2-tuple of sets. The first set, named done,
    contains the futures that completed (finished or cancelled futures) before the wait
    completed. The second set, named not_done, contains the futures that did not complete
    (pending or running futures). timeout can be used to control the maximum number of
    seconds to wait before returning.

    :param fs: Futures list. Default None
    :param throw_except: Re-raise exception if call raised. Default True.
    :param return_when: One of `ALL_COMPLETED`, `ANY_COMPLETED`, `ALWAYS`
    :param download_results: Download results. Default false (Only get statuses)
    :param timeout: Timeout of waiting for results.
    :param THREADPOOL_SIZE: Number of threads to use. Default 64
    :param WAIT_DUR_SEC: Time interval between each check.

    :return: `(fs_done, fs_notdone)`
        where `fs_done` is a list of futures that have completed
        and `fs_notdone` is a list of futures that have not completed.
    :rtype: 2-tuple of list
    """
    if not fs:
        return

    if type(fs) != list:
        fs = [fs]

    if not internal_storage:
        internal_storage = InternalStorage(fs[0].storage_config)

    if download_results:
        msg = 'ExecutorID {} - Getting results from functions'.format(fs[0].executor_id)
        fs_done = [f for f in fs if f.done]
        fs_not_done = [f for f in fs if not f.done]
        # fs_not_ready = [f for f in futures if not f.ready and not f.done]

    else:
        msg = 'ExecutorID {} - Waiting for functions to complete'.format(fs[0].executor_id)
        fs_done = [f for f in fs if f.ready or f.done]
        fs_not_done = [f for f in fs if not (f.ready or f.done)]
        # fs_not_ready = [f for f in futures if not f.ready and not f.done]

    logger.info(msg)

    if not fs_not_done:
        return fs_done, fs_not_done

    if is_unix_system() and timeout is not None:
        logger.debug('Setting waiting timeout to {} seconds'.format(timeout))
        error_msg = 'Timeout of {} seconds exceeded waiting for function activations to finish'.format(timeout)
        signal.signal(signal.SIGALRM, partial(timeout_handler, error_msg))
        signal.alarm(timeout)

    # Setup progress bar
    pbar = None
    if not is_lithops_worker() and logger.getEffectiveLevel() == logging.INFO:
        from tqdm.auto import tqdm
        if not is_notebook():
            print()
        pbar = tqdm(bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ',
                    total=len(fs), disable=None)
        pbar.update(len(fs_done))

    try:
        present_jobs = {f.job_key for f in fs_not_done}

        for job_key in present_jobs:
            monitor = job_monitor.monitors[job_key]
            monitor.update_params(pbar, throw_except, download_results,
                                  WAIT_DUR_SEC, THREADPOOL_SIZE)

            if return_when == ALL_COMPLETED:
                while not job_monitor.monitors[job_key].all_done():
                    time.sleep(1)
            elif return_when == ANY_COMPLETED:
                while not job_monitor.monitors[job_key].any_done():
                    time.sleep(1)

    except KeyboardInterrupt as e:
        if download_results:
            not_dones_call_ids = [(f.job_id, f.call_id) for f in fs if not f.done]
        else:
            not_dones_call_ids = [(f.job_id, f.call_id) for f in fs if not f.ready and not f.done]
        msg = ('Cancelled - Total Activations not done: {}'.format(len(not_dones_call_ids)))
        if pbar:
            pbar.close()
            print()
        logger.info(msg)
        raise e

    except Exception as e:
        raise e

    finally:
        if is_unix_system():
            signal.alarm(0)
        if pbar and not pbar.disable:
            pbar.close()
            if not is_notebook():
                print()

    if download_results:
        fs_done = [f for f in fs if f.done]
        fs_notdone = [f for f in fs if not f.done]
    else:
        fs_done = [f for f in fs if f.ready or f.done]
        fs_notdone = [f for f in fs if not f.ready and not f.done]

    return fs_done, fs_notdone


def get_result(fs, throw_except=True, timeout=None,
               THREADPOOL_SIZE=128, WAIT_DUR_SEC=1,
               internal_storage=None):
    """
    For getting the results from all function activations

    :param fs: Futures list. Default None
    :param throw_except: Reraise exception if call raised. Default True.
    :param verbose: Shows some information prints. Default False
    :param timeout: Timeout for waiting for results.
    :param THREADPOOL_SIZE: Number of threads to use. Default 128
    :param WAIT_DUR_SEC: Time interval between each check.
    :return: The result of the future/s
    """
    if type(fs) != list:
        fs = [fs]

    if not internal_storage:
        internal_storage = InternalStorage(fs[0]._storage_config)

    fs_done, _ = wait(fs=fs, throw_except=throw_except,
                      timeout=timeout, download_results=True,
                      internal_storage=internal_storage,
                      THREADPOOL_SIZE=THREADPOOL_SIZE,
                      WAIT_DUR_SEC=WAIT_DUR_SEC)
    result = []
    fs_done = [f for f in fs_done if not f.futures and f._produce_output]
    for f in fs_done:
        result.append(f.result(throw_except=throw_except,
                               internal_storage=internal_storage))

    logger.debug("ExecutorID {} - Finished getting results".format(fs[0].executor_id))

    return result
