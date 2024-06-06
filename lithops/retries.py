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
    A wrapper around `ResponseFuture` that takes care of retries.
    """

    def __init__(
        self,
        response_future: ResponseFuture,
        map_function: Callable[..., Any],
        input: Any,
        retries: Optional[int] = None,
        **kwargs
    ):
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
        return not self.cancelled and self.failure_count <= self.retries

    def _retry(self, function_executor: FunctionExecutor):
        inputs = [self.input]
        futures_list = function_executor.map(
            self.map_function, inputs, **self.map_kwargs
        )
        self.response_future = futures_list[0]

    def cancel(self):
        # cancelling will prevent any further retries, but won't affect any running tasks
        self.cancelled = True

    @property
    def done(self):
        return self.response_future.done

    @property
    def error(self):
        return self.response_future.error

    @property
    def _exception(self):
        return self.response_future._exception

    @property
    def stats(self):
        return self.response_future.stats

    def status(
        self,
        throw_except: bool = True,
        internal_storage: Any = None,
        check_only: bool = False,
    ):
        stat = self.response_future.status(
            throw_except=throw_except,
            internal_storage=internal_storage,
            check_only=check_only,
        )
        if self.response_future.error:
            reraise(*self.response_future._exception)
        return stat

    def result(self, throw_except: bool = True, internal_storage: Any = None):
        res = self.response_future.result(
            throw_except=throw_except, internal_storage=internal_storage
        )
        if self.response_future.error:
            reraise(*self.response_future._exception)
        return res


class RetryingFunctionExecutor:
    """
    A wrapper around `FunctionExecutor` that supports retries.
    """

    def __init__(self, executor: FunctionExecutor):
        self.executor = executor

    def __enter__(self):
        self.executor.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.executor.__exit__(exc_type, exc_value, traceback)

    def map(
        self,
        map_function: Callable,
        map_iterdata: List[Union[List[Any], Tuple[Any, ...], Dict[str, Any]]],
        chunksize: Optional[int] = None,
        extra_args: Optional[Union[List[Any], Tuple[Any, ...], Dict[str, Any]]] = None,
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
        futures_list = self.executor.map(
            map_function,
            map_iterdata,
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
        return [
            RetryingFuture(
                f,
                map_function=map_function,
                input=i,
                retries=retries,
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
            for i, f in zip(map_iterdata, futures_list)
        ]

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
        lookup = {f.response_future: f for f in fs}

        while True:
            response_futures = [f.response_future for f in fs]

            done, pending = self.executor.wait(
                response_futures,
                throw_except=throw_except,
                return_when=return_when,
                download_results=download_results,
                timeout=timeout,
                threadpool_size=threadpool_size,
                wait_dur_sec=wait_dur_sec,
                show_progressbar=show_progressbar,
            )

            retrying_done = []
            retrying_pending = [lookup[response_future] for response_future in pending]
            for response_future in done:
                retrying_future = lookup[response_future]
                if response_future.error:
                    retrying_future._inc_failure_count()
                    if retrying_future._should_retry():
                        retrying_future._retry(self.executor)
                        # put back into pending since we are retrying this input
                        retrying_pending.append(retrying_future)
                        lookup[retrying_future.response_future] = retrying_future
                    else:
                        retrying_done.append(retrying_future)
                else:
                    retrying_done.append(retrying_future)

            if return_when == ALWAYS:
                break
            elif return_when == ANY_COMPLETED and len(retrying_done) > 0:
                break
            elif return_when == ALL_COMPLETED and len(retrying_pending) == 0:
                break

        return retrying_done, retrying_pending

    def clean(
        self,
        fs: Optional[Union[ResponseFuture, List[ResponseFuture]]] = None,
        cs: Optional[List[CloudObject]] = None,
        clean_cloudobjects: Optional[bool] = True,
        clean_fn: Optional[bool] = False,
        force: Optional[bool] = False
    ):
        self.executor.clean(fs, cs, clean_cloudobjects, clean_fn, force)
