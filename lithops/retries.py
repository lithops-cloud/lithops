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

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from lithops import FunctionExecutor
from lithops.future import ResponseFuture
from lithops.storage.utils import CloudObject
from lithops.wait import (
    ALL_COMPLETED,
    ALWAYS,
    ANY_COMPLETED,
    THREADPOOL_SIZE,
    WAIT_DUR_SEC,
)
from six import reraise


class RetryingFuture:
    """
    A wrapper around `ResponseFuture` that adds retry capabilities.

    This class is used internally by Lithops to handle retry logic for
    failed function executions. It allows retrying a map function with
    the same input upon failure, up to a specified number of times.
    """

    def __init__(
        self,
        response_future: ResponseFuture,
        map_function: Callable[..., Any],
        input: Any,
        retries: Optional[int] = None,
        **kwargs
    ):
        """
        Initialize a RetryingFuture.

        :param response_future: The initial ResponseFuture object.
        :param map_function: The function to retry on failure.
        :param input: The input data for the map function.
        :param retries: Maximum number of retry attempts.
        :param kwargs: Additional arguments to pass to the map function.
        """
        self.response_future = response_future
        self.map_function = map_function
        self.input = input
        self.retries = retries or 0
        self.map_kwargs = kwargs
        self.failure_count = 0
        self.cancelled = False

    def _inc_failure_count(self):
        self.failure_count += 1

    def _should_retry(self):
        """
        Tells whether the call has retries left and was not cancelled
        """
        return not self.cancelled and self.failure_count <= self.retries

    def _retry(self, function_executor: FunctionExecutor):
        """
        Resubmits the map function with the same input, and takes the new
        activation as the future to follow from now on
        """
        self.response_future = function_executor.map(
            self.map_function, [self.input], **self.map_kwargs
        )[0]

    def cancel(self):
        """
        Gives up on any further retry. A task already running is left alone
        """
        self.cancelled = True

    @property
    def done(self):
        """
        Tells whether the function execution is complete
        """
        return self.response_future.done

    @property
    def error(self):
        """
        Tells whether the function execution raised
        """
        return self.response_future.error

    @property
    def _exception(self):
        """
        Returns the (type, value, traceback) tuple the execution raised
        """
        return self.response_future._exception

    @property
    def stats(self):
        """
        Returns the performance and usage metrics of the execution
        """
        return self.response_future.stats

    def _reraise_if_error(self):
        if self.response_future.error:
            reraise(*self.response_future._exception)

    def status(
        self,
        throw_except: bool = True,
        internal_storage: Any = None,
        check_only: bool = False,
    ):
        """
        Return the current status of the function execution.

        :param throw_except: Whether to raise any captured exception.
        :param internal_storage: Optional internal storage reference.
        :param check_only: If True, only checks status without updating.
        :return: Execution status string.
        """
        stat = self.response_future.status(
            throw_except=throw_except,
            internal_storage=internal_storage,
            check_only=check_only,
        )
        self._reraise_if_error()
        return stat

    def result(self, throw_except: bool = True, internal_storage: Any = None):
        """
        Get the result of the function execution.

        :param throw_except: Whether to raise any captured exception.
        :param internal_storage: Optional internal storage reference.
        :return: The result of the executed function.
        """
        res = self.response_future.result(
            throw_except=throw_except, internal_storage=internal_storage
        )
        self._reraise_if_error()
        return res


class RetryingFunctionExecutor:
    """
    Wrapper around FunctionExecutor with automatic retries.

    Same public interface as FunctionExecutor, plus a `retries`
    parameter on map() for per-invocation retry budget.

    :param executor: FunctionExecutor (localhost, serverless,
        or standalone)
    """

    def __init__(self, executor: FunctionExecutor):
        self.executor = executor
        self.config = executor.config

    def __enter__(self):
        """
        Context manager entry. Delegates to the inner FunctionExecutor.
        """
        self.executor.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Context manager exit. Delegates to the inner FunctionExecutor.
        """
        self.executor.__exit__(exc_type, exc_value, traceback)

    def _retries_to_use(self, retries):
        if retries is not None:
            return retries
        return self.config.get('lithops', {}).get('retries', 0)

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
        exclude_modules: Optional[List[str]] = [],
        retries: Optional[int] = None,
    ) -> List[RetryingFuture]:
        """
        Spawn multiple function activations with automatic retry on failure.

        :param map_function: The function to map over the data.
        :param map_iterdata: An iterable of input data (e.g., Python list).
        :param chunksize: Split map_iterdata in chunks of this
            size. One worker per chunk.
        :param extra_args: Additional arguments to pass to each
            function.
        :param extra_env: Additional environment variables for
            the function environment.
        :param runtime_memory: Memory (in MB) to allocate per
            function activation.
        :param obj_chunk_size: For file processing. Split each
            object into chunks of this size (in bytes).
        :param obj_chunk_number: For file processing. Number of
            chunks to split each object into.
        :param obj_newline: Newline character for line integrity
            in file partitioning.
        :param timeout: Max time per function activation
            (in seconds).
        :param include_modules: Explicitly pickle these
            dependencies.
        :param exclude_modules: Explicitly exclude these modules
            from pickling.
        :param retries: Number of retries for each function
            activation upon failure.

        :return: A list of RetryingFuture objects, one for each
            function activation.
        """

        retries_to_use = self._retries_to_use(retries)

        map_kwargs = dict(
            chunksize=chunksize,
            extra_args=extra_args,
            extra_env=extra_env,
            runtime_memory=runtime_memory,
            obj_chunk_size=obj_chunk_size,
            obj_chunk_number=obj_chunk_number,
            obj_newline=obj_newline,
            timeout=timeout,
            include_modules=include_modules,
            exclude_modules=exclude_modules,
        )

        futures_list = self.executor.map(
            map_function,
            map_iterdata,
            **map_kwargs,
        )
        return [
            RetryingFuture(
                f,
                map_function=map_function,
                input=i,
                retries=retries_to_use,
                **map_kwargs,
            )
            for i, f in zip(map_iterdata, futures_list)
        ]

    def _split_done_and_retried(self, done, pending, lookup):
        """
        Sorts the futures the inner executor reported as done into the ones
        that are really finished and the ones that failed and got
        resubmitted, extending the lookup with every new response future
        """
        retrying_done = []
        retrying_pending = [
            lookup[response_future] for response_future in pending
        ]

        for response_future in done:
            retrying_future = lookup[response_future]
            if not response_future.error:
                retrying_done.append(retrying_future)
                continue

            retrying_future._inc_failure_count()
            if not retrying_future._should_retry():
                retrying_done.append(retrying_future)
                continue

            retrying_future._retry(self.executor)
            retrying_pending.append(retrying_future)
            lookup[retrying_future.response_future] = retrying_future

        return retrying_done, retrying_pending

    @staticmethod
    def _wait_is_over(return_when, retrying_done, retrying_pending):
        """
        Tells whether the completion policy is satisfied, which for anything
        but ALWAYS may take several rounds because of the retries
        """
        if return_when == ALWAYS:
            return True
        if return_when == ANY_COMPLETED:
            return bool(retrying_done)
        if return_when == ALL_COMPLETED:
            return not retrying_pending
        return False

    def wait(
        self,
        fs: List[RetryingFuture],
        throw_except: Optional[bool] = True,
        return_when: Optional[Any] = ALL_COMPLETED,
        download_results: Optional[bool] = False,
        timeout: Optional[int] = None,
        threadpool_size: Optional[int] = THREADPOOL_SIZE,
        wait_dur_sec: Optional[int] = WAIT_DUR_SEC,
        show_progressbar: Optional[bool] = True,
    ) -> Tuple[List[RetryingFuture], List[RetryingFuture]]:
        """
        Wait for a set of futures to complete, retrying any that fail.

        :param fs: List of RetryingFuture objects to wait on.
        :param throw_except: Raise exceptions encountered during execution.
        :param return_when: Completion policy. One of: ALWAYS,
            ANY_COMPLETED, or ALL_COMPLETED.
        :param download_results: Whether to download results after completion.
        :param timeout: Maximum wait time (in seconds).
        :param threadpool_size: Number of threads used for polling.
        :param wait_dur_sec: Polling interval (in seconds).
        :param show_progressbar: Show progress bar for the wait operation.

        :return: A tuple (done, pending) of lists of RetryingFutures.
        """
        lookup = {f.response_future: f for f in fs}

        while True:
            # A retry replaces the response future of a RetryingFuture, so
            # the list has to be rebuilt on every round
            done, pending = self.executor.wait(
                [f.response_future for f in fs],
                throw_except=throw_except,
                return_when=return_when,
                download_results=download_results,
                timeout=timeout,
                threadpool_size=threadpool_size,
                wait_dur_sec=wait_dur_sec,
                show_progressbar=show_progressbar,
            )

            retrying_done, retrying_pending = self._split_done_and_retried(
                done, pending, lookup
            )

            if self._wait_is_over(
                return_when, retrying_done, retrying_pending
            ):
                return retrying_done, retrying_pending

    def clean(
        self,
        fs: Optional[Union[ResponseFuture, List[ResponseFuture]]] = None,
        cs: Optional[List[CloudObject]] = None,
        clean_cloudobjects: Optional[bool] = True,
        clean_fn: Optional[bool] = False,
        force: Optional[bool] = False
    ):
        """
        Cleans up temporary files and objects related to this
        executor, including:
        - Function packages
        - Serialized input/output data
        - Cloud objects (if specified)

        :param fs: List of futures to clean.
        :param cs: List of cloudobjects to clean.
        :param clean_cloudobjects: Whether to delete all
            cloudobjects created with this executor.
        :param clean_fn: Whether to delete cached functions.
        :param force: Force cleanup even for unfinished futures.
        """
        self.executor.clean(fs, cs, clean_cloudobjects, clean_fn, force)
