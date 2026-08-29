#
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
import sys
import logging
import atexit
import pickle
import tempfile
import subprocess as sp
from typing import Any, Dict, List, Optional, Tuple, Union
from collections.abc import Callable
from datetime import datetime

from lithops import constants
from lithops.future import ResponseFuture
from lithops.invokers import create_invoker
from lithops.storage import InternalStorage
from lithops.wait import (
    wait,
    ALL_COMPLETED,
    THREADPOOL_SIZE,
    ALWAYS,
    _partition_futures,
)
from lithops.job import create_map_job, create_reduce_job
from lithops.job.job import invalidate_function_cache
from lithops.config import (
    default_config,
    extract_localhost_config,
    extract_standalone_config,
    extract_serverless_config,
    get_log_info,
    extract_storage_config,
)
from lithops.constants import LOCALHOST, CLEANER_DIR, CLEANER_TMP_SUFFIX, SERVERLESS, STANDALONE
from lithops.utils import (
    setup_lithops_logger,
    is_lithops_worker,
    create_executor_id,
    create_futures_list,
    FuturesList,
    _as_future_list as wrap_as_future_list,
    log_prefix,
)
from lithops.localhost import LocalhostHandlerV1, LocalhostHandlerV2
from lithops.standalone import StandaloneHandler
from lithops.serverless import ServerlessHandler
from lithops.storage.utils import create_job_key, CloudObject
from lithops.monitor import JobMonitor


logger = logging.getLogger(__name__)


def _dump_cleaner_data(data: Dict[str, Any]) -> None:
    """
    Drops a request in the shared cleaner directory, which the cleaner
    process picks up and deletes once it has honoured it. Every Lithops
    process on this machine writes here, and the cleaner reads the directory
    while they do, so the request is written under a staging name the
    cleaner ignores and then renamed into place: the rename is atomic, and
    no cleaner can ever read a half written pickle
    """
    os.makedirs(CLEANER_DIR, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=CLEANER_DIR, suffix=CLEANER_TMP_SUFFIX, delete=False
    ) as temp:
        pickle.dump(data, temp)
    os.replace(temp.name, temp.name[:-len(CLEANER_TMP_SUFFIX)])


def _omit_none(mapping: Dict[str, Any]) -> Dict[str, Any]:
    """
    Keeps the entries the user actually set, so that they do not overwrite
    the config with None
    """
    return {key: value for key, value in mapping.items() if value is not None}


def _missing_plotting_extra(method_name: str) -> ModuleNotFoundError:
    """
    Error for a method that needs the optional plotting dependencies
    """
    return ModuleNotFoundError(
        f"Please install 'pip3 install lithops[plotting]' for "
        f"making use of the {method_name}() method"
    )


def _group_futures_by_job(
    futures: List[Any]
) -> List[Tuple[str, str, List[Any], List[Any]]]:
    """
    Splits the futures into consecutive runs of the same job, keeping the
    execution time and the memory of each of its activations. Every job runs
    a single function
    """
    groups = []
    for future in futures:
        if not groups or groups[-1][0] != future.job_id:
            groups.append((future.job_id, future.function_name, [], []))
        _, _, runtimes, memory = groups[-1]
        runtimes.append(future.stats['worker_exec_time'])
        memory.append(future.runtime_memory)
    return groups


class FunctionExecutor:
    """
    Base executor that contains the common logic for the Localhost, Serverless
    and Standalone executors.

    :param mode: Execution mode. One of: localhost, serverless or standalone
    :param config: Settings passed in here will override those in lithops_config
    :param config_file: Path to the lithops config file
    :param backend: Compute backend to run the functions
    :param storage: Storage backend to store Lithops data
    :param monitoring: Monitoring system implementation.
        One of: storage, rabbitmq
    :param log_level: Log level printing (INFO, DEBUG, ...).
        Set it to None to hide all logs.
        If this is param is set, all logging params in config
        are disabled
    :param kwargs: Any parameter that can be set in the compute
        backend section of the config file, can be set here
    """

    _cleaner_process = None

    def __init__(
        self,
        mode: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        config_file: Optional[str] = None,
        backend: Optional[str] = None,
        storage: Optional[str] = None,
        monitoring: Optional[str] = None,
        log_level: Union[str, bool, None] = False,
        **kwargs: Any
    ):
        self.is_lithops_worker = is_lithops_worker()
        self.executor_id = create_executor_id()
        self.futures = []
        self.cleaned_jobs = set()
        self.total_jobs = 0
        self.last_call = None
        self.log_path = None

        self._setup_logging(log_level, config_file, config)

        self.config = default_config(
            config_file=config_file,
            config_data=config,
            config_overwrite=self._build_config_overwrite(
                mode, backend, storage, monitoring, kwargs
            )
        )

        self.data_cleaner = self.config['lithops'].get('data_cleaner', True)
        if self.data_cleaner and not self.is_lithops_worker:
            atexit.register(
                self.clean,
                clean_cloudobjects=False,
                clean_fn=True,
                on_exit=True,
            )

        storage_config = extract_storage_config(self.config)
        self.internal_storage = InternalStorage(storage_config)
        self.storage = self.internal_storage.storage

        self.backend = self.config['lithops']['backend']
        self.mode = self.config['lithops']['mode']
        self.compute_handler = self._create_compute_handler()
        self.config['lithops']['backend_type'] = (
            self.compute_handler.get_backend_type()
        )

        self.job_monitor = JobMonitor(
            executor_id=self.executor_id,
            internal_storage=self.internal_storage,
            config=self.config
        )
        self.invoker = create_invoker(
            config=self.config,
            executor_id=self.executor_id,
            internal_storage=self.internal_storage,
            compute_handler=self.compute_handler,
            job_monitor=self.job_monitor
        )

        logger.debug(
            f'Function executor for {self.backend} created with ID: {self.executor_id}'
        )

    def __enter__(self):
        """Context manager method."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Context manager method."""
        self.job_monitor.stop()
        self.invoker.stop()
        self.compute_handler.clear()

    @staticmethod
    def _build_config_overwrite(mode, backend, storage, monitoring, kwargs):
        """
        Turns the arguments of the constructor into the config overwrite that
        takes precedence over the config file
        """
        return {
            'lithops': _omit_none({
                'mode': mode,
                'backend': backend,
                'storage': storage,
                'monitoring': monitoring,
            }),
            'backend': _omit_none(kwargs),
        }

    def _setup_logging(self, log_level, config_file, config):
        """
        Sets up the Lithops logger, unless the user already configured a
        logger of their own or asked for no logs at all
        """
        if self.is_lithops_worker:
            # Logging has already been set up in entry_point.py
            return
        if log_level:
            setup_lithops_logger(log_level)
        elif (
            log_level is False
            and logger.getEffectiveLevel() == logging.WARNING
        ):
            setup_lithops_logger(
                *get_log_info(
                    config_file=config_file, config_data=config
                )
            )

    def _create_compute_handler(self):
        """
        Builds the handler of the backend this executor runs on
        """
        if self.mode == LOCALHOST:
            localhost_config = extract_localhost_config(self.config)
            if localhost_config.get('version', 2) == 1:
                return LocalhostHandlerV1(localhost_config)
            return LocalhostHandlerV2(localhost_config)
        if self.mode == SERVERLESS:
            return ServerlessHandler(
                extract_serverless_config(self.config),
                self.internal_storage
            )
        if self.mode == STANDALONE:
            return StandaloneHandler(extract_standalone_config(self.config))
        return None

    def _create_job_id(self, call_type):
        """
        Numbers a new job of this executor, prefixed by the call that
        submitted it: A for call_async, M for map and R for reduce
        """
        job_id = str(self.total_jobs).zfill(3)
        self.total_jobs += 1
        return f'{call_type}{job_id}'

    @staticmethod
    def _as_future_list(futures):
        """Keep list subclasses (including FuturesList) unchanged; wrap a single future."""
        return wrap_as_future_list(futures)

    @staticmethod
    def _disable_iterdata_output(iterdata):
        """
        Marks the futures used as input as consumed, so that get_result()
        returns the output of this job only
        """
        if isinstance(iterdata, FuturesList):
            for fut in iterdata:
                fut._produce_output = False

    def _invoke(self, job):
        """
        Invokes a job and tracks its futures in this executor
        """
        futures = self.invoker.run_job(job)
        self.futures.extend(futures)
        return futures

    def _run_map_job(
        self,
        job_id,
        map_function,
        iterdata,
        runtime_memory=None,
        **job_kwargs,
    ):
        """
        Builds a map job and invokes it, returning the job and its futures
        """
        runtime_meta = self.invoker.select_runtime(job_id, runtime_memory)
        job = create_map_job(
            config=self.config,
            internal_storage=self.internal_storage,
            executor_id=self.executor_id,
            job_id=job_id,
            map_function=map_function,
            iterdata=iterdata,
            runtime_meta=runtime_meta,
            runtime_memory=runtime_memory,
            **job_kwargs
        )
        return job, self._invoke(job)

    def _run_reduce_job(
        self,
        reduce_job_id,
        reduce_function,
        map_job,
        map_futures,
        runtime_memory=None,
        **job_kwargs,
    ):
        """
        Builds a reduce job over the futures of a map job and invokes it
        """
        runtime_meta = self.invoker.select_runtime(
            reduce_job_id, runtime_memory
        )
        job = create_reduce_job(
            config=self.config,
            internal_storage=self.internal_storage,
            executor_id=self.executor_id,
            reduce_job_id=reduce_job_id,
            reduce_function=reduce_function,
            map_job=map_job,
            map_futures=map_futures,
            runtime_meta=runtime_meta,
            runtime_memory=runtime_memory,
            **job_kwargs
        )
        return self._invoke(job)

    def _submit_map(
        self,
        map_function,
        iterdata,
        runtime_memory=None,
        extra_env=None,
        include_modules=None,
        exclude_modules=None,
        timeout=None,
        chunksize=None,
        extra_args=None,
        obj_chunk_size=None,
        obj_chunk_number=None,
        obj_newline='\n',
        job_prefix='M'
    ):
        """
        Common path of call_async(), map() and the map stage of map_reduce()
        """
        job_id = self._create_job_id(job_prefix)
        job, futures = self._run_map_job(
            job_id=job_id,
            map_function=map_function,
            iterdata=iterdata,
            runtime_memory=runtime_memory,
            extra_env=extra_env,
            include_modules=include_modules,
            exclude_modules=exclude_modules,
            execution_timeout=timeout,
            chunksize=chunksize,
            extra_args=extra_args,
            obj_chunk_size=obj_chunk_size,
            obj_chunk_number=obj_chunk_number,
            obj_newline=obj_newline
        )
        self._disable_iterdata_output(iterdata)
        return job_id, job, futures

    def _cleanup_jobs(self, futures, exception=None, force=False):
        """
        Releases the backend resources of the given jobs and deletes their
        temporary data. Not every backend takes the exception that ended them
        """
        present_jobs = {f.job_key for f in futures}
        if exception is None:
            self.compute_handler.clear(present_jobs)
        else:
            self.compute_handler.clear(present_jobs, exception=exception)
        self.clean(clean_cloudobjects=False, force=force)

    def _stop_monitor_if_idle(self, extra_fs=None):
        """
        Stops the job monitor once there is no future left to watch, counting
        the ones that do not belong to this executor
        """
        tracked = list(self.futures)
        if extra_fs:
            seen = {id(fut) for fut in tracked}
            tracked.extend(fut for fut in extra_fs if id(fut) not in seen)
        if tracked and all(
            getattr(fut, 'ready', False) or fut.success or fut.done
            for fut in tracked
        ):
            self.job_monitor.stop()

    def call_async(
        self,
        func: Callable,
        data: Union[List[Any], Tuple[Any, ...], Dict[str, Any]],
        extra_env: Optional[Dict] = None,
        runtime_memory: Optional[int] = None,
        timeout: Optional[int] = None,
        include_modules: Optional[List] = [],
        exclude_modules: Optional[List] = []
    ) -> ResponseFuture:
        """
        For running one function execution asynchronously.

        :param func: The function to map over the data.
        :param data: Input data. Arguments can be passed as a
            list or tuple, or as a dictionary for keyword
            arguments.
        :param extra_env: Additional env variables for function
            environment.
        :param runtime_memory: Memory to use to run the function.
        :param timeout: Time that the function has to complete
            its execution before raising a timeout.
        :param include_modules: Explicitly pickle these
            dependencies.
        :param exclude_modules: Explicitly keep these modules
            from pickled dependencies.

        :return: Response future.
        """
        self.last_call = 'call_async'
        _, _, futures = self._submit_map(
            func,
            [data],
            runtime_memory=runtime_memory,
            extra_env=extra_env,
            include_modules=include_modules,
            exclude_modules=exclude_modules,
            timeout=timeout,
            job_prefix='A'
        )

        return futures[0]

    def map(
        self,
        map_function: Callable,
        map_iterdata: List[Union[
            List[Any], Tuple[Any, ...], Dict[str, Any]
        ]],
        chunksize: Optional[int] = None,
        extra_args: Optional[Union[
            List[Any], Tuple[Any, ...], Dict[str, Any]
        ]] = None,
        extra_env: Optional[Dict[str, str]] = None,
        runtime_memory: Optional[int] = None,
        obj_chunk_size: Optional[int] = None,
        obj_chunk_number: Optional[int] = None,
        obj_newline: Optional[str] = '\n',
        timeout: Optional[int] = None,
        include_modules: Optional[List[str]] = [],
        exclude_modules: Optional[List[str]] = []
    ) -> FuturesList:
        """
        Spawn multiple function activations based on the items
        of an input list.

        :param map_function: The function to map over the data
        :param map_iterdata: An iterable of input data
            (e.g python list).
        :param chunksize: Split map_iterdata in chunks of this
            size. Lithops spawns 1 worker per resulting chunk
        :param extra_args: Additional arguments to pass to each
            map_function activation
        :param extra_env: Additional environment variables for
            function environment
        :param runtime_memory: Memory (in MB) to use to run
            the functions
        :param obj_chunk_size: Used for data processing. Chunk
            size to split each object in bytes. Must be >= 1MiB.
            'None' for processing the whole file in one
            function activation
        :param obj_chunk_number: Used for data processing. Number
            of chunks to split each object. 'None' for processing
            the whole file in one function activation. chunk_n
            has prevalence over chunk_size if both parameters
            are set
        :param obj_newline: new line character for keeping line
            integrity of partitions. 'None' for disabling line
            integrity logic and get partitions of the exact same
            size in the functions
        :param timeout: Max time per function activation (seconds)
        :param include_modules: Explicitly pickle these
            dependencies. All required dependencies are pickled
            if default empty list. No one dependency is pickled
            if it is explicitly set to None
        :param exclude_modules: Explicitly keep these modules
            from pickled dependencies. It is not taken into
            account if you set include_modules.

        :return: A list with size `len(map_iterdata)` of futures
            for each job (Futures are also internally stored
            by Lithops).
        """
        self.last_call = 'map'
        _, _, futures = self._submit_map(
            map_function,
            map_iterdata,
            runtime_memory=runtime_memory,
            extra_env=extra_env,
            include_modules=include_modules,
            exclude_modules=exclude_modules,
            timeout=timeout,
            chunksize=chunksize,
            extra_args=extra_args,
            obj_chunk_size=obj_chunk_size,
            obj_chunk_number=obj_chunk_number,
            obj_newline=obj_newline
        )

        return create_futures_list(futures, self)

    def map_reduce(
        self,
        map_function: Callable,
        map_iterdata: List[Union[
            List[Any], Tuple[Any, ...], Dict[str, Any]
        ]],
        reduce_function: Callable,
        chunksize: Optional[int] = None,
        extra_args: Optional[Union[
            List[Any], Tuple[Any, ...], Dict[str, Any]
        ]] = None,
        extra_args_reduce: Optional[Union[
            List[Any], Tuple[Any, ...], Dict[str, Any]
        ]] = None,
        extra_env: Optional[Dict[str, str]] = None,
        map_runtime_memory: Optional[int] = None,
        reduce_runtime_memory: Optional[int] = None,
        timeout: Optional[int] = None,
        obj_chunk_size: Optional[int] = None,
        obj_chunk_number: Optional[int] = None,
        obj_newline: Optional[str] = '\n',
        obj_reduce_by_key: Optional[bool] = False,
        spawn_reducer: Optional[int] = 20,
        include_modules: Optional[List[str]] = [],
        exclude_modules: Optional[List[str]] = []
    ) -> FuturesList:
        """
        Map the map_function over the data and apply the
        reduce_function across all futures.

        :param map_function: The function to map over the data
        :param map_iterdata: An iterable of input data
        :param reduce_function: The function to reduce over
            the futures
        :param chunksize: Split map_iterdata in chunks of this
            size. Lithops spawns 1 worker per resulting chunk.
            Default 1
        :param extra_args: Additional arguments to pass to
            function activation. Default None
        :param extra_args_reduce: Additional arguments to pass
            to the reduce function activation. Default None
        :param extra_env: Additional environment variables for
            action environment. Default None
        :param map_runtime_memory: Memory to use to run the map
            function. Default None (loaded from config)
        :param reduce_runtime_memory: Memory to use to run the
            reduce function. Default None (loaded from config)
        :param timeout: Time that the functions have to complete
            their execution before raising a timeout
        :param obj_chunk_size: the size of the data chunks to
            split each object. 'None' for processing the whole
            file in one function activation
        :param obj_chunk_number: Number of chunks to split each
            object. 'None' for processing the whole file in one
            function activation
        :param obj_newline: New line character for keeping line
            integrity of partitions. 'None' for disabling line
            integrity logic and get partitions of the exact same
            size in the functions
        :param obj_reduce_by_key: Set one reducer per object
            after running the partitioner. By default there is
            one reducer for all the objects
        :param spawn_reducer: Percentage of done map functions
            before spawning the reduce function
        :param include_modules: Explicitly pickle these
            dependencies.
        :param exclude_modules: Explicitly keep these modules
            from pickled dependencies.

        :return: A list with size `len(map_iterdata)` of futures.
        """
        self.last_call = 'map_reduce'
        map_job_id, map_job, map_futures = self._submit_map(
            map_function,
            map_iterdata,
            runtime_memory=map_runtime_memory,
            extra_env=extra_env,
            include_modules=include_modules,
            exclude_modules=exclude_modules,
            timeout=timeout,
            chunksize=chunksize,
            extra_args=extra_args,
            obj_chunk_size=obj_chunk_size,
            obj_chunk_number=obj_chunk_number,
            obj_newline=obj_newline
        )

        if spawn_reducer != ALWAYS:
            self.wait(map_futures, return_when=spawn_reducer)
            logger.debug(
                f'{log_prefix(self.executor_id, map_job_id)} - {spawn_reducer}% of map '
                f'activations done. Spawning reduce stage'
            )

        reduce_futures = self._run_reduce_job(
            reduce_job_id=map_job_id.replace('M', 'R'),
            reduce_function=reduce_function,
            map_job=map_job,
            map_futures=map_futures,
            runtime_memory=reduce_runtime_memory,
            extra_args=extra_args_reduce,
            obj_reduce_by_key=obj_reduce_by_key,
            extra_env=extra_env,
            include_modules=include_modules,
            exclude_modules=exclude_modules
        )

        for future in map_futures:
            future._set_mapreduce()

        return create_futures_list(map_futures + reduce_futures, self)

    def wait(
        self,
        fs: Optional[Union[
            ResponseFuture, FuturesList, List[ResponseFuture]
        ]] = None,
        throw_except: Optional[bool] = True,
        return_when: Optional[Any] = ALL_COMPLETED,
        download_results: Optional[bool] = False,
        timeout: Optional[int] = None,
        threadpool_size: Optional[int] = THREADPOOL_SIZE,
        wait_dur_sec: Optional[int] = None,
        show_progressbar: Optional[bool] = True
    ) -> Tuple[FuturesList, FuturesList]:
        """
        Wait for the Future instances (possibly created by
        different Executor instances) given by fs to complete.
        Returns a named 2-tuple of sets. The first set, named
        done, contains the futures that completed (finished or
        cancelled futures) before the wait completed. The second
        set, named not_done, contains the futures that did not
        complete (pending or running futures). timeout can be
        used to control the maximum number of seconds to wait
        before returning.

        :param fs: Futures list. Default None
        :param throw_except: Re-raise exception if call raised.
            Default True
        :param return_when: Percentage of done futures
        :param download_results: Download results. Default false
            (Only get statuses)
        :param timeout: Timeout of waiting for results
        :param threadpool_size: Number of threads to use.
            Default 64
        :param wait_dur_sec: Time interval between each check.
            Default 1 second
        :param show_progressbar: whether or not to show the
            progress bar.

        :return: `(fs_done, fs_notdone)` where `fs_done` is a
            list of futures that have completed and `fs_notdone`
            is a list of futures that have not completed.
        """
        futures = self._as_future_list(fs or self.futures)

        try:
            wait(
                fs=futures,
                internal_storage=self.internal_storage,
                job_monitor=self.job_monitor,
                download_results=download_results,
                throw_except=throw_except,
                return_when=return_when,
                timeout=timeout,
                threadpool_size=threadpool_size,
                wait_dur_sec=wait_dur_sec,
                show_progressbar=show_progressbar,
                futures_from_executor_wait=not fs,
            )

            if self.data_cleaner and return_when == ALL_COMPLETED:
                self._cleanup_jobs(futures)
            self._stop_monitor_if_idle(futures)

        except (KeyboardInterrupt, Exception) as e:
            self.invoker.stop()
            self.job_monitor.remove(futures)
            for future in futures:
                future._set_exception()
            if self.data_cleaner:
                self._cleanup_jobs(futures, exception=e, force=True)
            self._stop_monitor_if_idle(futures)
            raise

        fs_done, fs_notdone = _partition_futures(futures, download_results)
        return (
            create_futures_list(fs_done, self),
            create_futures_list(fs_notdone, self),
        )

    def get_result(
        self,
        fs: Optional[Union[
            ResponseFuture, FuturesList, List[ResponseFuture]
        ]] = None,
        throw_except: Optional[bool] = True,
        timeout: Optional[int] = None,
        threadpool_size: Optional[int] = THREADPOOL_SIZE,
        wait_dur_sec: Optional[int] = None,
        show_progressbar: Optional[bool] = True
    ):
        """
        For getting the results from all function activations

        :param fs: Futures list. Default None
        :param throw_except: Reraise exception if call raised. Default True.
        :param timeout: Timeout for waiting for results.
        :param threadpool_size: Number of threads to use. Default 64
        :param wait_dur_sec: Time interval between each check. Default 1 second
        :param show_progressbar: whether or not to show the progress bar.

        :return: The result of the future/s
        """
        pending_to_read = (
            len(fs) if fs
            else sum(1 for f in self.futures if not f._read and not f.futures)
        )

        logger.info(
            f'{log_prefix(self.executor_id)} - Getting results from '
            f'{pending_to_read} function activations'
        )

        fs_done, _ = self.wait(
            fs=fs,
            throw_except=throw_except,
            timeout=timeout,
            download_results=True,
            threadpool_size=threadpool_size,
            wait_dur_sec=wait_dur_sec,
            show_progressbar=show_progressbar
        )

        result = []
        for future in fs_done:
            if future.futures or not future._produce_output:
                continue
            if not fs and future._read:
                continue
            result.append(future.result(
                throw_except=throw_except,
                internal_storage=self.internal_storage
            ))
            if not fs:
                future._read = True

        logger.debug(
            f'{log_prefix(self.executor_id)} - Finished getting results'
        )

        if len(result) == 1 and self.last_call != 'map':
            return result[0]

        return result

    def plot(
        self,
        fs: Optional[Union[
            ResponseFuture, List[ResponseFuture], FuturesList
        ]] = None,
        dst: Optional[str] = None,
        figsize: Optional[tuple] = (10, 6)
    ):
        """
        Creates timeline and histogram of the current execution in dst.

        :param fs: list of futures.
        :param dst: destination path to save .png plots.
        :param figsize: size of the plots, in inches.
        """
        ftrs = fs or self.futures
        if isinstance(ftrs, ResponseFuture):
            ftrs = [ftrs]

        ftrs_to_plot = [
            f for f in ftrs
            if (f.success or f.done) and not f.error
        ]

        if not ftrs_to_plot:
            logger.debug(
                f'{log_prefix(self.executor_id)} - No futures ready to plot'
            )
            return

        try:
            logging.getLogger('matplotlib').setLevel(logging.WARNING)
            from lithops.plots import create_timeline, create_histogram
        except ImportError:
            raise _missing_plotting_extra('plot')

        logger.info(f'{log_prefix(self.executor_id)} - Creating execution plots')

        create_timeline(ftrs_to_plot, dst, figsize)
        create_histogram(ftrs_to_plot, dst, figsize)

    @staticmethod
    def _spawn_cleaner_process():
        """
        Starts the process that honours the pending cleaner requests. One
        cleaner picks up every request, so a running one is left alone
        """
        cleaner = FunctionExecutor._cleaner_process
        if cleaner and cleaner.poll() is None:
            return

        FunctionExecutor._cleaner_process = sp.Popen(
            [sys.executable, '-m', 'lithops.scripts.cleaner'],
            start_new_session=True,
            env=os.environ.copy(),
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL
        )

    def clean(
        self,
        fs: Optional[Union[ResponseFuture, List[ResponseFuture]]] = None,
        cs: Optional[List[CloudObject]] = None,
        clean_cloudobjects: Optional[bool] = True,
        clean_fn: Optional[bool] = False,
        force: Optional[bool] = False,
        on_exit: Optional[bool] = False
    ):
        """
        Deletes all the temp files from storage. These files
        include the function, the data serialization and the
        function invocation results. It can also clean
        cloudobjects.

        :param fs: List of futures to clean
        :param cs: List of cloudobjects to clean
        :param clean_cloudobjects: Delete all cloudobjects
            created with this executor
        :param clean_fn: Delete cached functions in this executor
        :param force: Clean all future objects even if they have
            not been completed
        :param on_exit: do not print logs on exit
        """
        if not hasattr(self, 'internal_storage'):
            return

        storage_config = self.internal_storage.get_storage_config()

        if cs:
            _dump_cleaner_data({
                'cos_to_clean': list(cs),
                'storage_config': storage_config
            })
            if not fs:
                return

        if clean_fn:
            invalidate_function_cache(self.executor_id)
            _dump_cleaner_data({
                'fn_to_clean': self.executor_id,
                'storage_config': storage_config
            })

        futures = self._as_future_list(fs or self.futures)
        present_jobs = {
            create_job_key(f.executor_id, f.job_id)
            for f in futures
            if (f.executor_id.count('-') == 1 and f.done) or force
        }
        jobs_to_clean = present_jobs - self.cleaned_jobs

        if jobs_to_clean:
            if not on_exit:
                logger.info(
                    f'{log_prefix(self.executor_id)} - Cleaning temporary data'
                )
            _dump_cleaner_data({
                'jobs_to_clean': jobs_to_clean,
                'clean_cloudobjects': clean_cloudobjects,
                'storage_config': storage_config
            })
            self.cleaned_jobs.update(jobs_to_clean)

        if jobs_to_clean or cs:
            self._spawn_cleaner_process()

    def job_summary(self, cloud_objects_n: Optional[int] = 0):
        """
        Logs information of a job executed by the calling
        function executor. currently supports: code_engine,
        ibm_vpc and ibm_cf.

        :param cloud_objects_n: number of cloud object used in
            COS, declared by user.
        """
        try:
            import pandas as pd
            import numpy as np
        except ImportError:
            raise _missing_plotting_extra('job_summary')

        if not hasattr(self.compute_handler.backend, 'calc_cost'):
            logger.warning(
                f"Could not log job: {self.compute_handler.backend.name} "
                "backend isn't supported by this function."
            )
            return

        def append_rows(rows):
            pd.DataFrame(rows).to_csv(
                self.log_path, mode='a', header=False, index=False
            )

        if self.log_path:
            # Carry over the cloud objects of the summary written last time,
            # the last cell of the last row of its log
            previous = pd.read_csv(self.log_path)
            cloud_objects_n += float(previous.iloc[-1].iloc[-1])
        else:
            self.log_path = os.path.join(
                constants.LOGS_DIR,
                datetime.now().strftime("%Y-%m-%d_%H-%M-%S.csv"),
            )

        # Writing the header alone overrides the summary of a previous call
        headers = [
            'Job_ID', 'Function', 'Invocations', 'Memory(MB)',
            'AvgRuntime', 'Cost', 'CloudObjects',
        ]
        pd.DataFrame([], columns=headers).to_csv(self.log_path, index=False)

        futures = self._as_future_list(self.futures)
        for job_id, job_func, runtimes, memory in _group_futures_by_job(futures):
            cost = self.compute_handler.backend.calc_cost(runtimes, memory)
            append_rows([[
                job_id, job_func, len(runtimes), sum(memory),
                np.round(np.average(runtimes), 10), cost, ' ',
            ]])

        summary = pd.read_csv(self.log_path)
        total_average = (
            sum(summary.AvgRuntime * summary.Invocations)
            / summary.Invocations.sum()
        )
        append_rows([[
            'Summary',
            ' ',
            summary.Invocations.sum(),
            summary['Memory(MB)'].sum(),
            round(total_average, 10),
            summary.Cost.sum(),
            cloud_objects_n,
        ]])

        logger.info(f"View log file logs at {self.log_path}")


class LocalhostExecutor(FunctionExecutor):
    """
    Initialize a LocalhostExecutor class.

    :param config: Settings passed in here will override those in config file.
    :param config_file: Path to the lithops config file
    :param storage: Name of the storage backend to use.
    :param monitoring: monitoring system.
    :param log_level: log level to use during the execution.
    :param kwargs: Any parameter that can be set in the compute
        backend section of the config file, can be set here
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        config_file: Optional[str] = None,
        storage: Optional[str] = None,
        monitoring: Optional[str] = None,
        log_level: Union[str, bool, None] = False,
        **kwargs: Any
    ):
        super().__init__(
            backend=LOCALHOST,
            config=config,
            config_file=config_file,
            storage=storage or LOCALHOST,
            log_level=log_level,
            monitoring=monitoring,
            **kwargs
        )


class _FixedModeExecutor(FunctionExecutor):
    """FunctionExecutor subclass that pins execution mode via `_mode`."""

    _mode = None

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        config_file: Optional[str] = None,
        backend: Optional[str] = None,
        storage: Optional[str] = None,
        monitoring: Optional[str] = None,
        log_level: Union[str, bool, None] = False,
        **kwargs: Any
    ):
        super().__init__(
            config=config,
            config_file=config_file,
            mode=self._mode,
            backend=backend,
            storage=storage,
            monitoring=monitoring,
            log_level=log_level,
            **kwargs
        )


class ServerlessExecutor(_FixedModeExecutor):
    """
    Initialize a ServerlessExecutor class.

    :param config: Settings passed in here will override those in config file
    :param config_file: Path to the lithops config file
    :param backend: Name of the serverless compute backend to use
    :param storage: Name of the storage backend to use
    :param monitoring: monitoring system
    :param log_level: log level to use during the execution
    :param kwargs: Any parameter that can be set in the compute
        backend section of the config file, can be set here
    """

    _mode = SERVERLESS


class StandaloneExecutor(_FixedModeExecutor):
    """
    Initialize a StandaloneExecutor class.

    :param config: Settings passed in here will override those in config file
    :param config_file: Path to the lithops config file
    :param backend: Name of the standalone compute backend to use
    :param storage: Name of the storage backend to use
    :param monitoring: monitoring system
    :param log_level: log level to use during the execution
    """

    _mode = STANDALONE
