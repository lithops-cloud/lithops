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
import math
import time
import concurrent.futures as cf
from functools import partial
from types import SimpleNamespace
from itertools import chain
from typing import Optional, List, Union, Tuple, Any

from lithops.utils import (
    is_unix_system,
    timeout_handler,
    is_notebook,
    is_lithops_worker,
    FuturesList,
    _as_future_list,
    log_prefix,
)
from lithops.storage import InternalStorage
from lithops.future import ResponseFuture
from lithops.monitoring import JobMonitor


ALWAYS = 0
ANY_COMPLETED = -1
ALL_COMPLETED = 100

THREADPOOL_SIZE = 64
WAIT_DUR_SEC = 1

logger = logging.getLogger(__name__)


def _future_is_complete(fut, download_results):
    return fut.done if download_results else (fut.success or fut.done)


def _partition_futures(fs, download_results):
    """Split futures into (done, not_done)."""
    done, not_done = [], []
    for fut in fs:
        if _future_is_complete(fut, download_results):
            done.append(fut)
        else:
            not_done.append(fut)
    return done, not_done


def _poll_sleep_sec(job_monitor, wait_dur_sec):
    """
    Returns the interval between two polls. Only a remote storage backend is
    worth throttling, every other source of statuses is local and cheap
    """
    remote_storage = (
        job_monitor.type == 'storage'
        and job_monitor.storage_backend != 'localhost'
    )
    if remote_storage:
        return wait_dur_sec or WAIT_DUR_SEC
    return 0.1


def _log_wait_start(prefix: str, return_when: Any, pending: int) -> None:
    """
    Logs how many function activations the wait is going to block on
    """
    if return_when == ALL_COMPLETED:
        target = ''
    elif return_when == ANY_COMPLETED:
        target = 'any of '
    else:
        target = f'{return_when}% of '

    logger.info(
        f'{prefix} - Waiting for {target}{pending} '
        'function activations to complete'
    )


def _set_wait_alarm(timeout: int) -> None:
    """
    Arms a SIGALRM that aborts the wait once the timeout is exceeded
    """
    logger.debug(f'Setting waiting timeout to {timeout} seconds')
    error_msg = (
        f'Timeout of {timeout} seconds exceeded waiting for '
        'function activations to finish'
    )
    signal.signal(signal.SIGALRM, partial(timeout_handler, error_msg))
    signal.alarm(timeout)


def _create_progressbar(total: int, initial: int):
    """
    Builds the bar that tracks the wait, or nothing where a bar would only
    get in the way: inside a worker, or when debug logs are already printed
    """
    if is_lithops_worker() or logger.getEffectiveLevel() == logging.DEBUG:
        return None

    from tqdm.auto import tqdm
    if not is_notebook():
        print()
    pbar = tqdm(
        bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ',
        total=total,
        disable=None,
    )
    pbar.update(min(initial, total))
    return pbar


def _start_job_monitors(executors_data) -> List[JobMonitor]:
    """
    Starts one monitor per executor the futures belong to
    """
    monitors = []
    for executor_data in executors_data:
        monitor = JobMonitor(
            executor_id=executor_data.executor_id,
            internal_storage=executor_data.internal_storage,
        )
        monitor.start(fs=executor_data.futures)
        monitors.append(monitor)
    return monitors


def _poll_until_done(
    fs,
    executors_data,
    job_monitor,
    return_when,
    download_results,
    sleep_sec,
    poll_kwargs,
):
    """
    Polls every executor until return_when% of the futures are done. A round
    that fetched something is followed immediately by another one, as more
    statuses are likely to be waiting already
    """
    while not _check_done(fs, return_when, download_results):
        # The monitor is a daemon thread that exits on its own once every
        # future it knows about is done, so it may need waking up for the
        # futures that showed up afterwards
        if not job_monitor.is_alive():
            job_monitor.start(fs=fs)

        new_data = False
        for executor_data in executors_data:
            if _get_executor_data(fs, executor_data, **poll_kwargs):
                new_data = True

        time.sleep(0 if new_data else sleep_sec)


def wait(
    fs: Union[ResponseFuture, FuturesList, List[ResponseFuture]],
    internal_storage: Optional[InternalStorage] = None,
    job_monitor: Optional[JobMonitor] = None,
    throw_except: Optional[bool] = True,
    return_when: Optional[Any] = ALL_COMPLETED,
    download_results: Optional[bool] = False,
    timeout: Optional[int] = None,
    threadpool_size: Optional[int] = THREADPOOL_SIZE,
    wait_dur_sec: Optional[int] = None,
    show_progressbar: Optional[bool] = True,
    futures_from_executor_wait: Optional[bool] = False,
) -> Tuple[FuturesList, FuturesList]:
    """
    Wait for the Future instances (possibly created by different
    Executor instances) given by fs to complete. Returns a 2-tuple.
    The first item, done, contains the futures that completed
    before the wait completed. The second item, not_done, contains
    the futures that did not complete. timeout can be used to
    control the maximum number of seconds to wait before returning.

    :param fs: Futures list. Default None
    :param internal_storage: InternalStorage instance. Default None.
    :param job_monitor: JobMonitor instance. Default None.
    :param throw_except: Re-raise exception if call raised.
        Default True.
    :param return_when: Percentage of done futures
    :param download_results: Download results. Default false
        (Only get statuses)
    :param timeout: Timeout of waiting for results.
    :param threadpool_size: Number of threads to use. Default 64
    :param wait_dur_sec: Time interval between each check.
        Default 1 second
    :param show_progressbar: whether or not to show the progress bar.
    :param futures_from_executor_wait: Measure progress against the
        futures that are still pending instead of against all of them.

    :return: `(fs_done, fs_notdone)`
        where `fs_done` is a list of futures that have completed
        and `fs_notdone` is a list of futures that have not completed.
    :rtype: 2-tuple of list
    """
    if not fs:
        return [], []

    fs = _as_future_list(fs)
    prefix = log_prefix(fs[0].executor_id)
    fs_done, fs_not_done = _partition_futures(fs, download_results)

    if not fs_not_done:
        logger.debug(f'{prefix} - All function activations are done')
        return fs_done, fs_not_done

    not_done_futures = fs_not_done if futures_from_executor_wait else fs
    fs_to_wait = math.ceil(return_when * len(not_done_futures) / 100)
    _log_wait_start(prefix, return_when, len(not_done_futures))

    if is_unix_system() and timeout is not None:
        _set_wait_alarm(timeout)

    pbar = (
        _create_progressbar(fs_to_wait, len(fs_done))
        if show_progressbar else None
    )

    started_monitors = []
    pool = None
    try:
        executors_data = _create_executors_data_from_futures(
            fs, internal_storage
        )

        if not job_monitor:
            started_monitors = _start_job_monitors(executors_data)
            # All of them run, but a single one drives the loop below and
            # sets its poll interval. There is only one wait to pace
            job_monitor = started_monitors[-1]

        sleep_sec = _poll_sleep_sec(job_monitor, wait_dur_sec)
        pool = cf.ThreadPoolExecutor(max_workers=threadpool_size)
        poll_kwargs = dict(
            pbar=pbar,
            throw_except=throw_except,
            download_results=download_results,
            threadpool_size=threadpool_size,
            pool=pool,
        )

        if return_when == ALWAYS:
            for executor_data in executors_data:
                _get_executor_data(fs, executor_data, **poll_kwargs)
        else:
            _poll_until_done(
                fs, executors_data, job_monitor, return_when,
                download_results, sleep_sec, poll_kwargs
            )

    except KeyboardInterrupt:
        _, not_done = _partition_futures(fs, download_results)
        if pbar:
            pbar.close()
            print()
        logger.info(f'Cancelled - Total Activations not done: {len(not_done)}')
        raise

    finally:
        if pool is not None:
            pool.shutdown(wait=True)
        for monitor in started_monitors:
            monitor.stop()
        if is_unix_system():
            signal.alarm(0)
        if pbar and not pbar.disable:
            pbar.close()
            if not is_notebook():
                print()

    return _partition_futures(fs, download_results)


def get_result(
    fs: Optional[
        Union[ResponseFuture, FuturesList, List[ResponseFuture]]
    ] = None,
    internal_storage: Optional[InternalStorage] = None,
    throw_except: Optional[bool] = True,
    timeout: Optional[int] = None,
    threadpool_size: Optional[int] = THREADPOOL_SIZE,
    wait_dur_sec: Optional[int] = None,
    show_progressbar: Optional[bool] = True,
):
    """
    For getting the results from all function activations

    :param fs: Futures list. Default None
    :param internal_storage: InternalStorage instance. Default None.
    :param throw_except: Reraise exception if call raised.
        Default True.
    :param timeout: Timeout for waiting for results.
    :param threadpool_size: Number of threads to use. Default 64
    :param wait_dur_sec: Time interval between each check.
        Default 1 second
    :param show_progressbar: whether or not to show the progress bar.

    :return: The result of the future/s
    """
    fs = _as_future_list(fs)
    prefix = log_prefix(fs[0].executor_id)

    logger.info(
        f'{prefix} - Getting results from {len(fs)} function activations'
    )

    fs_done, _ = wait(
        fs=fs,
        throw_except=throw_except,
        timeout=timeout,
        download_results=True,
        internal_storage=internal_storage,
        threadpool_size=threadpool_size,
        wait_dur_sec=wait_dur_sec,
        show_progressbar=show_progressbar,
    )
    result = [
        f.result(throw_except=throw_except)
        for f in fs_done
        if not f.futures and f._produce_output
    ]

    logger.debug(f'{prefix} - Finished getting results')

    return result


def _create_executors_data_from_futures(fs, internal_storage):
    """
    Groups the futures by the executor that created them, and pairs every
    group with the storage its statuses have to be read from
    """
    grouped = {}
    for fut in fs:
        grouped.setdefault(fut.executor_id, []).append(fut)

    executor_jobs = []
    for executor_id, futures in grouped.items():
        executor_data = SimpleNamespace(
            executor_id=executor_id,
            futures=futures,
        )
        backend = futures[0]._storage_config['backend']
        if internal_storage and internal_storage.backend == backend:
            executor_data.internal_storage = internal_storage
        else:
            executor_data.internal_storage = InternalStorage(
                futures[0]._storage_config
            )
        executor_jobs.append(executor_data)

    return executor_jobs


def _check_done(fs, return_when, download_results):
    """
    Checks if return_when% of futures are ready or done
    """
    if return_when == ANY_COMPLETED:
        # Stops at the first one, rather than counting every future on
        # every poll to compare the total against one
        return any(_future_is_complete(f, download_results) for f in fs)

    total_done = sum(
        1 for f in fs if _future_is_complete(f, download_results)
    )

    done_percentage = int(total_done * 100 / len(fs))
    return done_percentage >= return_when


def _ready_futures(exec_data, download_results):
    """
    Returns the futures of one executor that have data waiting on the other
    side: their status has arrived, but the caller has not fetched it yet.

    One pass, no call ids: this used to intersect a set of the futures that
    had arrived with a set of the ones not fetched yet, which walked the
    list four times and built a tuple per future on each. The futures of an
    executor are distinct objects, so the intersection was only ever asking
    both things of the same future
    """
    if download_results:
        return [
            f for f in exec_data.futures
            if (f.ready or f.success) and not f.done
        ]
    return [
        f for f in exec_data.futures
        if f.ready and not (f.success or f.done)
    ]


def _get_executor_data(
    fs,
    exec_data,
    download_results,
    throw_except,
    threadpool_size,
    pbar,
    pool=None,
):
    """
    Downloads the status, or the whole result, of every ready future of one
    executor. Returns how many were fetched, so that the caller can tell a
    productive poll from an empty one
    """
    fs_to_wait_on = _ready_futures(exec_data, download_results)
    if not fs_to_wait_on:
        return 0

    storage = exec_data.internal_storage

    def fetch(f):
        if download_results:
            f.result(throw_except=throw_except, internal_storage=storage)
        else:
            f.status(throw_except=throw_except, internal_storage=storage)

    if pool is None:
        with cf.ThreadPoolExecutor(max_workers=threadpool_size) as owned:
            list(owned.map(fetch, fs_to_wait_on))
    else:
        list(pool.map(fetch, fs_to_wait_on))

    if pbar:
        for f in fs_to_wait_on:
            if _future_is_complete(f, download_results) and pbar.n < pbar.total:
                pbar.update(1)
        pbar.refresh()

    new_futures = list(chain.from_iterable(
        f._new_futures for f in fs_to_wait_on if f._new_futures
    ))
    if new_futures:
        fs.extend(new_futures)
        exec_data.futures.extend(new_futures)
        if pbar:
            pbar.total += len(new_futures)
            pbar.refresh()

    return len(fs_to_wait_on)
