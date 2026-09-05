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

import asyncio
import concurrent.futures as cf
import threading
import time

import pytest

import lithops
import lithops.concurrent
from lithops.concurrent.futures import (
    ALL_COMPLETED,
    FIRST_COMPLETED,
    FIRST_EXCEPTION,
    BrokenExecutor,
    FunctionExecutor,
    Future,
    LocalhostExecutor,
    ProcessPoolExecutor,
    ServerlessExecutor,
    StandaloneExecutor,
    ThreadPoolExecutor,
    TimeoutError,
    _call,
    _exception_from_lithops,
    as_completed,
    wait,
)
from lithops.future import ResponseFuture
from lithops.retries import RetryingFunctionExecutor
from lithops.tests.functions import simple_map_function


class FakeLithopsFuture:
    """
    In-memory stand-in for ResponseFuture.

    It models the parts of the contract the adapter depends on: the state
    machine (`ready` once a status exists, `done` once the output has been
    read), `status()` returning None while the call is still running, and a
    `result()` that can be made to block the way a storage download does
    """

    def __init__(self, value=None, exc=None, finished=True, call_id='00000'):
        self.call_id = call_id
        self.stats = {'worker_exec_time': 0.01}
        self._value = None
        self._exception = Exception()
        self._state = ResponseFuture.State.Invoked
        self._status_calls = 0
        self._result_calls = 0
        self._storage_seen = []
        self._result_gate = None
        if finished or exc is not None:
            self.finish(value=value, exc=exc)

    # -- the ResponseFuture properties the adapter reads -------------------

    @property
    def ready(self):
        return self._state == ResponseFuture.State.Ready

    @property
    def error(self):
        return self._state == ResponseFuture.State.Error

    @property
    def success(self):
        return self._state in (
            ResponseFuture.State.Success, ResponseFuture.State.Error
        )

    @property
    def done(self):
        return self._state in (
            ResponseFuture.State.Done,
            ResponseFuture.State.Error,
            ResponseFuture.State.Unknown,
        )

    def status(self, throw_except=True, internal_storage=None, check_only=False):
        self._status_calls += 1
        self._storage_seen.append(internal_storage)
        if self._state == ResponseFuture.State.Invoked:
            return None
        if self.error and throw_except:
            raise self._exception[1]
        return {'type': '__end__'}

    def result(self, throw_except=True, internal_storage=None,
               retries=10, wait_dur_sec=1):
        self._result_calls += 1
        self._storage_seen.append(internal_storage)
        if self._result_gate is not None:
            self._result_gate.wait()
        if self.error:
            if throw_except:
                raise self._exception[1]
            return None
        self._state = ResponseFuture.State.Done
        return self._value

    # -- test helpers ------------------------------------------------------

    def finish(self, value=None, exc=None):
        if exc is not None:
            self._exception = (type(exc), exc, None)
            self._state = ResponseFuture.State.Error
        else:
            self._value = value
            self._state = ResponseFuture.State.Ready

    def lose(self):
        """Reproduces the state an interrupted native wait() leaves behind"""
        self._state = ResponseFuture.State.Unknown

    def block_result(self):
        self._result_gate = threading.Event()
        return self._result_gate


class FakeMonitor:
    """The daemon thread JobMonitor owns, which exits once its job is done"""

    def __init__(self):
        self.alive = True
        self.futures = []

    def is_alive(self):
        return self.alive


class FakeJobMonitor:
    """
    Stand-in for lithops.monitoring.JobMonitor. Records the futures it was
    asked to track so a test can tell whether the adapter restarted it
    """

    def __init__(self, started=True):
        self.monitor = FakeMonitor() if started else None
        self.starts = []
        self.stopped = False

    def start(self, fs, **kwargs):
        if self.monitor is None:
            self.monitor = FakeMonitor()
        self.monitor.alive = True
        self.monitor.futures = list(fs)
        self.starts.append(list(fs))

    def is_alive(self):
        return self.monitor.is_alive()

    def stop(self):
        self.stopped = True
        if self.monitor is not None:
            self.monitor.alive = False

    def cleanup(self):
        pass

    def prepare(self):
        if self.monitor is None:
            self.monitor = FakeMonitor()
            self.monitor.alive = False


class FakeInnerExecutor:
    """
    Stand-in for lithops.FunctionExecutor. A MagicMock would answer every
    attribute, which hides whether the adapter reached for the job monitor
    or fell back to polling storage
    """

    def __init__(self, call_result=None, map_results=None, job_monitor=True,
                 data_cleaner=False):
        self.internal_storage = object()
        self.job_monitor = FakeJobMonitor() if job_monitor else None
        self.data_cleaner = data_cleaner
        self.call_async_calls = []
        self.map_calls = []
        self.cleaned = []
        self.exited = False
        self._call_result = call_result
        self._call_results = None
        self._map_results = map_results
        self._map_side_effect = None

    def call_async(self, func, data, **kwargs):
        self.call_async_calls.append((func, data, kwargs))
        if self._call_results is not None:
            return self._call_results.pop(0)
        if self._call_result is None:
            self._call_result = FakeLithopsFuture(value=256)
        return self._call_result

    def map(self, map_function, map_iterdata, **kwargs):
        self.map_calls.append((map_function, list(map_iterdata), kwargs))
        if self._map_side_effect is not None:
            return self._map_side_effect.pop(0)
        if self._map_results is None:
            self._map_results = [
                FakeLithopsFuture(value=1),
                FakeLithopsFuture(value=2),
                FakeLithopsFuture(value=3),
            ]
        return self._map_results

    def clean(self, **kwargs):
        self.cleaned.append(kwargs)

    def __exit__(self, exc_type, exc_value, traceback):
        self.exited = True
        if self.job_monitor is not None:
            self.job_monitor.stop()


def _adapter(inner=None, **kwargs):
    return FunctionExecutor(executor=inner or FakeInnerExecutor(), **kwargs)


class TestConcurrentFuturesApiSurface:

    def test_executor_is_concurrent_futures_executor(self):
        assert issubclass(FunctionExecutor, cf.Executor)
        assert issubclass(ProcessPoolExecutor, cf.Executor)
        assert issubclass(ThreadPoolExecutor, FunctionExecutor)
        assert issubclass(LocalhostExecutor, FunctionExecutor)
        assert issubclass(ServerlessExecutor, FunctionExecutor)
        assert issubclass(StandaloneExecutor, FunctionExecutor)

    def test_future_is_concurrent_futures_future(self):
        assert issubclass(Future, cf.Future)

    def test_pool_executor_names_are_function_executor(self):
        assert issubclass(ProcessPoolExecutor, FunctionExecutor)
        assert issubclass(ThreadPoolExecutor, FunctionExecutor)

    def test_mode_subclasses_pin_their_lithops_executor(self):
        from lithops import executors as native
        assert LocalhostExecutor._executor_cls is native.LocalhostExecutor
        assert ServerlessExecutor._executor_cls is native.ServerlessExecutor
        assert StandaloneExecutor._executor_cls is native.StandaloneExecutor
        assert ProcessPoolExecutor._executor_cls is native.FunctionExecutor

    def test_module_reexports_stdlib_constants(self):
        assert ALL_COMPLETED is cf.ALL_COMPLETED
        assert FIRST_COMPLETED is cf.FIRST_COMPLETED
        assert FIRST_EXCEPTION is cf.FIRST_EXCEPTION

    def test_package_reexports_the_public_names(self):
        assert lithops.concurrent.ProcessPoolExecutor is ProcessPoolExecutor
        assert lithops.concurrent.wait is wait
        assert set(lithops.concurrent.__all__) == set(
            lithops.concurrent.futures.__all__
        )

    def test_call_trampoline_applies_args_and_kwargs(self):
        def add(x, y, z=0):
            return x + y + z

        assert _call(add, (1, 2), {'z': 3}) == 6

    def test_exception_from_lithops_tuple(self):
        lf = FakeLithopsFuture(exc=ValueError('boom'))
        assert isinstance(_exception_from_lithops(lf), ValueError)
        assert str(_exception_from_lithops(lf)) == 'boom'

    def test_exception_from_lithops_without_a_reason(self):
        lf = FakeLithopsFuture(value=1)
        lf._state = ResponseFuture.State.Error
        exc = _exception_from_lithops(lf)
        assert isinstance(exc, Exception)
        assert 'without reporting an exception' in str(exc)


class TestSubmit:

    def test_submit_dispatches_call_async_with_args_kwargs(self):
        inner = FakeInnerExecutor()
        with _adapter(inner) as ex:
            fut = ex.submit(pow, 2, 8)
            func, data, _ = inner.call_async_calls[0]
            assert func is _call
            assert data == (pow, (2, 8), {})
            assert isinstance(fut, cf.Future)
            assert fut.result(timeout=5) == 256
            assert fut.lithops_future is inner._call_result

    def test_submit_passes_keyword_arguments_to_the_callable(self):
        inner = FakeInnerExecutor(FakeLithopsFuture(value=9))
        with _adapter(inner) as ex:
            ex.submit(pow, 3, exp=2)
            assert inner.call_async_calls[0][1] == (pow, (3,), {'exp': 2})

    def test_submit_falls_back_to_map_without_call_async(self):
        inner = FakeInnerExecutor(map_results=[FakeLithopsFuture(value=9)])
        inner.call_async = None
        with _adapter(inner) as ex:
            assert ex.submit(pow, 3, 2).result(timeout=5) == 9
        assert len(inner.map_calls) == 1

    def test_submit_returns_a_done_future_with_stats(self):
        lf = FakeLithopsFuture(value=4)
        lf.stats = {'worker_exec_time': 1.5}
        with _adapter(FakeInnerExecutor(lf)) as ex:
            fut = ex.submit(pow, 2, 2)
            assert fut.result(timeout=5) == 4
            assert fut.done()
            assert fut.exception(timeout=5) is None
            assert fut.stats['worker_exec_time'] == 1.5

    def test_submit_propagates_worker_exception(self):
        lf = FakeLithopsFuture(exc=ZeroDivisionError('x'))
        with _adapter(FakeInnerExecutor(lf)) as ex:
            fut = ex.submit(lambda: 1 / 0)
            with pytest.raises(ZeroDivisionError, match='x'):
                fut.result(timeout=5)
            assert isinstance(fut.exception(timeout=5), ZeroDivisionError)

    def test_submitted_future_is_running_and_declines_cancel(self):
        lf = FakeLithopsFuture(finished=False)
        with _adapter(FakeInnerExecutor(lf)) as ex:
            fut = ex.submit(pow, 2, 2)
            assert fut.running()
            assert fut.cancel() is False
            assert not fut.cancelled()
            lf.finish(value=4)
            assert fut.result(timeout=5) == 4

    def test_lost_activation_raises_instead_of_returning_none(self):
        """
        A future Lithops marks Unknown is done, but has no result. It is one
        lost call, not a dead executor, so it must not raise BrokenExecutor
        """
        lf = FakeLithopsFuture(finished=False)
        with _adapter(FakeInnerExecutor(lf)) as ex:
            fut = ex.submit(pow, 2, 2)
            lf.lose()
            with pytest.raises(RuntimeError, match='lost track') as raised:
                fut.result(timeout=5)
            assert not isinstance(raised.value, BrokenExecutor)
            assert ex.submit(pow, 2, 2) is not None

    def test_missing_output_surfaces_as_an_error(self):
        """result() flips the future to Error when the output never lands."""
        lf = FakeLithopsFuture(value=None)

        def failing_result(throw_except=True, internal_storage=None,
                           retries=10, wait_dur_sec=1):
            lf._state = ResponseFuture.State.Error
            return None

        lf.result = failing_result
        with _adapter(FakeInnerExecutor(lf)) as ex:
            with pytest.raises(Exception, match='without reporting an exception'):
                ex.submit(pow, 2, 2).result(timeout=5)

    def test_job_kwargs_are_forwarded(self):
        inner = FakeInnerExecutor()
        with _adapter(
            inner,
            runtime_memory=512,
            extra_env={'A': '1'},
            execution_timeout=30,
            include_modules=['pkg'],
            exclude_modules=['pkg.tests'],
        ) as ex:
            ex.submit(pow, 2, 2)
        kwargs = inner.call_async_calls[0][2]
        assert kwargs == {
            'runtime_memory': 512,
            'extra_env': {'A': '1'},
            'timeout': 30,
            'include_modules': ['pkg'],
            'exclude_modules': ['pkg.tests'],
        }

    def test_no_job_kwargs_are_sent_when_none_are_set(self):
        inner = FakeInnerExecutor()
        with _adapter(inner) as ex:
            ex.submit(pow, 2, 2)
        assert inner.call_async_calls[0][2] == {}


class TestMap:

    def test_map_uses_one_lithops_map_and_yields_results_in_order(self):
        inner = FakeInnerExecutor()
        with _adapter(inner) as ex:
            mapped = ex.map(abs, [-1, 2, -3])
            assert not isinstance(mapped, cf.Future)
            assert len(inner.map_calls) == 1
            mapped_fn, payloads, _ = inner.map_calls[0]
            assert mapped_fn is _call
            assert payloads == [
                (abs, (-1,), {}),
                (abs, (2,), {}),
                (abs, (-3,), {}),
            ]
            assert list(mapped) == [1, 2, 3]

    def test_map_zips_multiple_iterables(self):
        inner = FakeInnerExecutor(map_results=[
            FakeLithopsFuture(value=10),
            FakeLithopsFuture(value=12),
        ])
        with _adapter(inner) as ex:
            results = list(ex.map(simple_map_function, [4, 5], [6, 7]))
            assert inner.map_calls[0][1] == [
                (simple_map_function, (4, 6), {}),
                (simple_map_function, (5, 7), {}),
            ]
            assert results == [10, 12]

    def test_map_stops_at_the_shortest_iterable(self):
        inner = FakeInnerExecutor(map_results=[FakeLithopsFuture(value=1)])
        with _adapter(inner) as ex:
            list(ex.map(simple_map_function, [1, 2, 3], [9]))
        assert len(inner.map_calls[0][1]) == 1

    def test_map_over_nothing_submits_no_job(self):
        inner = FakeInnerExecutor()
        with _adapter(inner) as ex:
            assert list(ex.map(abs, [])) == []
        assert inner.map_calls == []

    def test_map_leaves_chunksize_to_the_lithops_config_by_default(self):
        """
        Passing the standard library default of 1 would silently override a
        chunksize set in the Lithops configuration
        """
        inner = FakeInnerExecutor()
        with _adapter(inner) as ex:
            list(ex.map(abs, [-1, 2, -3]))
        assert inner.map_calls[0][2]['chunksize'] is None

    def test_map_forwards_an_explicit_chunksize(self):
        inner = FakeInnerExecutor()
        with _adapter(inner) as ex:
            list(ex.map(abs, [-1, 2, -3], chunksize=2))
        assert inner.map_calls[0][2]['chunksize'] == 2

    def test_map_rejects_non_positive_chunksize(self):
        with _adapter() as ex:
            with pytest.raises(ValueError, match='chunksize'):
                ex.map(abs, [1], chunksize=0)

    def test_map_rejects_negative_buffersize(self):
        with _adapter() as ex:
            with pytest.raises(ValueError, match='buffersize'):
                ex.map(abs, [1], buffersize=-1)

    def test_map_buffersize_submits_in_windows(self):
        inner = FakeInnerExecutor()
        inner._map_side_effect = [
            [FakeLithopsFuture(value=1)],
            [FakeLithopsFuture(value=2)],
            [FakeLithopsFuture(value=3)],
        ]
        with _adapter(inner) as ex:
            assert list(ex.map(abs, [-1, -2, -3], buffersize=1)) == [1, 2, 3]
        assert len(inner.map_calls) == 3

    def test_map_is_eager(self):
        """Every call is submitted before the iterator is consumed."""
        inner = FakeInnerExecutor()
        with _adapter(inner) as ex:
            ex.map(abs, [-1, 2, -3])
            assert len(inner.map_calls) == 1

    def test_map_propagates_the_first_exception_in_order(self):
        inner = FakeInnerExecutor(map_results=[
            FakeLithopsFuture(value=0),
            FakeLithopsFuture(exc=ValueError('nope')),
            FakeLithopsFuture(value=2),
        ])
        with _adapter(inner) as ex:
            it = ex.map(abs, [0, 1, 2])
            assert next(it) == 0
            with pytest.raises(ValueError, match='nope'):
                next(it)

    def test_map_timeout_raises(self):
        lf = FakeLithopsFuture(finished=False)
        inner = FakeInnerExecutor(map_results=[lf])
        ex = _adapter(inner)
        try:
            it = ex.map(abs, [1], timeout=0.2)
            with pytest.raises(TimeoutError):
                next(it)
        finally:
            lf.finish(value=1)
            ex.shutdown(wait=True)

    def test_map_timeout_is_not_extended_by_a_slow_download(self):
        """
        The download runs off the caller's thread, so a result that is ready
        but slow to fetch must not push result(timeout) past its deadline
        """
        lf = FakeLithopsFuture(value=1)
        gate = lf.block_result()
        inner = FakeInnerExecutor(map_results=[lf])
        ex = _adapter(inner)
        try:
            it = ex.map(abs, [1], timeout=0.3)
            start = time.monotonic()
            with pytest.raises(TimeoutError):
                next(it)
            assert time.monotonic() - start < 2
        finally:
            gate.set()
            ex.shutdown(wait=True)


class TestCompletionTracking:

    def test_watcher_completes_a_future_that_finishes_later(self):
        lf = FakeLithopsFuture(finished=False)
        with _adapter(FakeInnerExecutor(lf)) as ex:
            fut = ex.submit(pow, 2, 10)
            assert not cf.Future.done(fut)
            lf.finish(value=1024)
            assert fut.result(timeout=5) == 1024

    def test_the_job_monitor_state_is_used_instead_of_polling_storage(self):
        """
        Lithops' job monitor already keeps every future's state current with
        one batched listing per round. Reading each future's status here as
        well would be one storage request per future per round
        """
        lf = FakeLithopsFuture(finished=False)
        with _adapter(FakeInnerExecutor(lf)) as ex:
            fut = ex.submit(pow, 2, 10)
            time.sleep(0.5)
            assert lf._status_calls == 0
            lf.finish(value=1024)
            assert fut.result(timeout=5) == 1024
        # One read of the status, once, to resolve the completed call
        assert lf._status_calls == 1

    def test_storage_is_polled_when_there_is_no_job_monitor(self):
        lf = FakeLithopsFuture(finished=False)
        inner = FakeInnerExecutor(lf, job_monitor=False)
        with _adapter(inner) as ex:
            fut = ex.submit(pow, 2, 10)
            lf.finish(value=1024)
            assert fut.result(timeout=5) == 1024
        assert lf._status_calls >= 1

    def test_the_internal_storage_handler_is_reused(self):
        """Otherwise every read builds a new client from the config."""
        lf = FakeLithopsFuture(value=7)
        inner = FakeInnerExecutor(lf)
        with _adapter(inner) as ex:
            assert ex.submit(pow, 7, 1).result(timeout=5) == 7
        assert lf._storage_seen
        assert all(seen is inner.internal_storage for seen in lf._storage_seen)

    def test_a_dead_job_monitor_is_restarted(self):
        """
        The monitor is a daemon that exits once everything it knows about is
        done, so a job submitted as it wound down would never be watched
        """
        lf = FakeLithopsFuture(finished=False)
        inner = FakeInnerExecutor(lf)
        with _adapter(inner) as ex:
            fut = ex.submit(pow, 2, 10)
            inner.job_monitor.monitor.alive = False
            deadline = time.monotonic() + 5
            while not inner.job_monitor.starts and time.monotonic() < deadline:
                time.sleep(0.05)
            assert inner.job_monitor.starts == [[lf]]
            lf.finish(value=1024)
            assert fut.result(timeout=5) == 1024

    def test_a_monitor_that_never_ran_is_left_alone(self):
        """JobMonitor.is_alive() raises when no monitor thread was created."""
        lf = FakeLithopsFuture(finished=False)
        inner = FakeInnerExecutor(lf)
        inner.job_monitor = FakeJobMonitor(started=False)
        with _adapter(inner) as ex:
            fut = ex.submit(pow, 2, 10)
            time.sleep(0.3)
            assert inner.job_monitor.starts == []
            lf.finish(value=1024)
            assert fut.result(timeout=5) == 1024

    def test_downloads_do_not_serialize_behind_each_other(self):
        """
        A future whose result is slow to fetch must not hold up the ones
        behind it, which a single watcher thread doing the downloads would
        """
        slow = FakeLithopsFuture(value='slow')
        gate = slow.block_result()
        quick = FakeLithopsFuture(value='quick')
        inner = FakeInnerExecutor(map_results=[slow, quick])
        with _adapter(inner) as ex:
            it = ex.map(abs, [1, 2])
            futures = list(ex._pending)
            done, _ = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
            assert done
            gate.set()
            assert list(it) == ['slow', 'quick']

    def test_a_result_is_downloaded_once(self):
        lf = FakeLithopsFuture(value=5)
        with _adapter(FakeInnerExecutor(lf)) as ex:
            fut = ex.submit(abs, -5)
            assert [fut.result(timeout=5) for _ in range(3)] == [5, 5, 5]
            assert fut.done()
        assert lf._result_calls == 1

    def test_done_does_not_block_on_a_slow_download(self):
        lf = FakeLithopsFuture(value=1)
        gate = lf.block_result()
        ex = _adapter(FakeInnerExecutor(lf))
        try:
            fut = ex.submit(abs, -1)
            start = time.monotonic()
            for _ in range(5):
                fut.done()
            assert time.monotonic() - start < 1
        finally:
            gate.set()
            ex.shutdown(wait=True)

    def test_a_dead_watcher_breaks_the_pending_futures(self):
        """
        Nothing else resolves futures, so a watcher that died has to fail
        them rather than leave every result() blocked for good
        """
        def boom(lf):
            raise RuntimeError('the watcher blew up')

        lf = FakeLithopsFuture(finished=False)
        ex = _adapter(FakeInnerExecutor(lf))
        fut = ex.submit(pow, 2, 2)
        ex._is_ready = boom
        ex._wake.set()
        with pytest.raises(BrokenExecutor, match='blew up'):
            fut.result(timeout=5)
        with pytest.raises(BrokenExecutor):
            ex.submit(pow, 2, 2)
        ex.shutdown(wait=False)

    def test_futures_from_many_threads_all_complete(self):
        inner = FakeInnerExecutor()
        inner._call_results = [FakeLithopsFuture(value=i) for i in range(30)]
        results = []
        with _adapter(inner) as ex:
            def go():
                results.append(ex.submit(abs, -1).result(timeout=10))

            threads = [threading.Thread(target=go) for _ in range(30)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
        assert sorted(results) == list(range(30))


class TestWaitAndAsCompleted:

    def test_wait_and_as_completed(self):
        inner = FakeInnerExecutor()
        inner._call_results = [
            FakeLithopsFuture(value=256),
            FakeLithopsFuture(value=8),
        ]
        with _adapter(inner) as ex:
            f1 = ex.submit(pow, 2, 8)
            f2 = ex.submit(pow, 2, 3)
            done, not_done = wait([f1], return_when=ALL_COMPLETED)
            assert f1 in done
            assert not not_done
            assert {f.result() for f in as_completed([f1, f2])} == {256, 8}

    def test_wait_first_completed(self):
        pending = FakeLithopsFuture(finished=False)
        inner = FakeInnerExecutor()
        inner._call_results = [FakeLithopsFuture(value='ok'), pending]
        with _adapter(inner) as ex:
            finished = ex.submit(str, 'ok')
            still = ex.submit(str, 'later')
            done, not_done = wait(
                [finished, still], return_when=FIRST_COMPLETED, timeout=5
            )
            assert finished in done
            assert still in not_done
            pending.finish(value='later')
            assert still.result(timeout=5) == 'later'

    def test_wait_first_exception(self):
        inner = FakeInnerExecutor()
        inner._call_results = [
            FakeLithopsFuture(exc=RuntimeError('bad')),
            FakeLithopsFuture(finished=False),
        ]
        with _adapter(inner) as ex:
            failed = ex.submit(str, 'a')
            still = ex.submit(str, 'b')
            done, _ = wait(
                [failed, still], return_when=FIRST_EXCEPTION, timeout=5
            )
            assert failed in done
            inner._call_results = None
            still.lithops_future.finish(value='b')

    def test_wait_times_out_on_a_pending_future(self):
        lf = FakeLithopsFuture(finished=False)
        ex = _adapter(FakeInnerExecutor(lf))
        try:
            fut = ex.submit(str, 'x')
            done, not_done = wait([fut], timeout=0.2)
            assert not done
            assert not_done == {fut}
        finally:
            lf.finish(value='x')
            ex.shutdown(wait=True)

    def test_wait_mixes_in_stdlib_futures(self):
        with _adapter() as ex, cf.ThreadPoolExecutor(1) as pool:
            ours = ex.submit(pow, 2, 8)
            theirs = pool.submit(pow, 2, 8)
            done, not_done = wait([ours, theirs], timeout=5)
            assert done == {ours, theirs}
            assert not not_done


class TestLifecycle:

    def test_submit_after_shutdown_raises(self):
        ex = _adapter()
        ex.shutdown(wait=False)
        with pytest.raises(RuntimeError, match='shutdown'):
            ex.submit(pow, 2, 2)

    def test_context_manager_shuts_down(self):
        with _adapter(FakeInnerExecutor()) as ex:
            ex.submit(pow, 2, 8)
        with pytest.raises(RuntimeError, match='shutdown'):
            ex.submit(pow, 2, 2)

    def test_shutdown_waits_for_the_futures_in_flight(self):
        lf = FakeLithopsFuture(finished=False)
        inner = FakeInnerExecutor(lf)
        ex = FunctionExecutor(executor=inner)
        fut = ex.submit(pow, 2, 2)
        threading.Timer(0.2, lambda: lf.finish(value=4)).start()
        ex.shutdown(wait=True)
        assert cf.Future.done(fut)
        assert fut.result() == 4

    def test_shutdown_is_idempotent(self):
        ex = _owning_adapter()
        ex.shutdown()
        ex.shutdown()
        assert ex._inner.exited

    def test_shutdown_without_waiting_still_releases_the_executor(self):
        """
        Otherwise the job monitor and invoker threads outlive the executor
        """
        lf = FakeLithopsFuture(finished=False)
        ex = _owning_adapter(lf)
        inner = ex._inner
        ex.submit(pow, 2, 2)
        ex.shutdown(wait=False)
        assert not inner.exited
        lf.finish(value=4)
        deadline = time.monotonic() + 5
        while not inner.exited and time.monotonic() < deadline:
            time.sleep(0.05)
        assert inner.exited

    def test_shutdown_of_an_idle_executor_releases_it_at_once(self):
        ex = _owning_adapter()
        ex.shutdown(wait=False)
        assert ex._inner.exited

    def test_owned_executor_is_torn_down(self):
        ex = _owning_adapter()
        with ex:
            ex.submit(pow, 2, 8)
        assert ex._inner.exited
        assert ex._inner.job_monitor.stopped

    def test_wrapped_executor_is_not_torn_down(self):
        inner = FakeInnerExecutor()
        with _adapter(inner):
            pass
        assert not inner.exited
        assert not inner.job_monitor.stopped

    def test_owned_executor_cleans_its_temporary_data(self):
        ex = _owning_adapter(data_cleaner=True)
        with ex:
            ex.submit(pow, 2, 8)
        assert ex._inner.cleaned == [{'clean_cloudobjects': False}]

    def test_no_cleaning_when_the_data_cleaner_is_off(self):
        ex = _owning_adapter(data_cleaner=False)
        with ex:
            ex.submit(pow, 2, 8)
        assert ex._inner.cleaned == []

    def test_wrapped_executor_data_is_not_cleaned(self):
        inner = FakeInnerExecutor(data_cleaner=True)
        with _adapter(inner) as ex:
            ex.submit(pow, 2, 8)
        assert inner.cleaned == []

    def test_shutdown_cancel_futures_does_not_hang(self):
        """
        Lithops cannot recall a dispatched call, so cancel() declines and
        shutdown still has to wait the futures out
        """
        lf = FakeLithopsFuture(finished=False)
        ex = _adapter(FakeInnerExecutor(lf))
        fut = ex.submit(pow, 2, 2)
        threading.Timer(0.2, lambda: lf.finish(value=4)).start()
        ex.shutdown(wait=True, cancel_futures=True)
        assert not fut.cancelled()
        assert fut.result() == 4

    def test_the_watcher_thread_does_not_outlive_the_executor(self):
        with _adapter(FakeInnerExecutor()) as ex:
            ex.submit(pow, 2, 8)
            watcher = ex._watcher
        assert not watcher.is_alive()


class TestConstruction:

    def test_initializer_is_rejected(self):
        with pytest.raises(NotImplementedError, match='initializer'):
            FunctionExecutor(
                executor=FakeInnerExecutor(), initializer=lambda: None
            )

    def test_retrying_executor_is_rejected(self):
        """Its retries come from its own wait(), which nothing here calls."""
        retrying = RetryingFunctionExecutor.__new__(RetryingFunctionExecutor)
        with pytest.raises(TypeError, match='RetryingFunctionExecutor'):
            FunctionExecutor(executor=retrying)

    def test_stdlib_pool_kwargs_are_accepted_when_wrapping(self):
        ex = FunctionExecutor(
            executor=FakeInnerExecutor(),
            mp_context=object(),
            max_tasks_per_child=2,
            thread_name_prefix='t',
        )
        ex.shutdown(wait=False)

    def test_stdlib_pool_kwargs_never_reach_the_lithops_executor(self):
        seen = {}

        class Recording(FunctionExecutor):
            _executor_cls = staticmethod(
                lambda **kwargs: seen.update(kwargs) or FakeInnerExecutor()
            )

        Recording(
            4, mp_context=object(), max_tasks_per_child=2,
            thread_name_prefix='t', backend='localhost',
        ).shutdown(wait=False)
        assert seen == {'max_workers': 4, 'backend': 'localhost'}

    def test_max_workers_is_ignored_when_wrapping(self):
        inner = FakeInnerExecutor()
        with FunctionExecutor(8, executor=inner) as ex:
            assert ex.lithops_executor is inner

    def test_lithops_executor_is_exposed(self):
        inner = FakeInnerExecutor()
        with _adapter(inner) as ex:
            assert ex.lithops_executor is inner


class TestFutureObject:

    def test_a_future_without_an_adapter_behaves_like_the_stdlib_one(self):
        fut = Future()
        assert fut.lithops_future is None
        assert fut.stats == {}
        assert not fut.done()
        fut.set_result(3)
        assert fut.result() == 3

    def test_stats_come_from_the_lithops_future(self):
        lf = FakeLithopsFuture(value=1)
        lf.stats = {'worker_exec_time': 2.5}
        assert Future(lithops_future=lf).stats == {'worker_exec_time': 2.5}


def _owning_adapter(lf=None, data_cleaner=False):
    """An adapter that built its own executor, so it owns the teardown."""
    inner = FakeInnerExecutor(lf, data_cleaner=data_cleaner)

    class Owning(FunctionExecutor):
        _executor_cls = staticmethod(lambda **kwargs: inner)

    return Owning()


def _same_api(executor):
    """The interchangeability check from issue 1427."""
    with executor:
        future = executor.submit(pow, 323, 1235)
        value = future.result(timeout=30)
        mapped = list(executor.map(abs, [-1, 2, -3], timeout=30))
    return value, mapped


class TestConcurrentFuturesLive:
    """Runs real Lithops jobs. Uses the same config as the rest of the suite."""

    def test_submit_and_map_match_threadpoolexecutor(self):
        expected = _same_api(cf.ThreadPoolExecutor(max_workers=2))
        got = _same_api(
            FunctionExecutor(config=pytest.lithops_config, log_level=None)
        )
        assert got == expected

    def test_submit_keyword_only_and_positional(self):
        def greet(name, suffix='!'):
            return f'hello {name}{suffix}'

        with FunctionExecutor(config=pytest.lithops_config, log_level=None) as ex:
            assert ex.submit(greet, 'lithops', suffix='.').result(timeout=30) == (
                'hello lithops.'
            )
            assert list(ex.map(greet, ['a', 'b'], ['?', '!'])) == [
                'hello a?',
                'hello b!',
            ]

    def test_as_completed_yields_each_future_once(self):
        with FunctionExecutor(config=pytest.lithops_config, log_level=None) as ex:
            futures = [ex.submit(abs, n) for n in (-2, 0, 5)]
            results = [f.result() for f in as_completed(futures, timeout=30)]
        assert sorted(results) == [0, 2, 5]

    def test_wait_all_completed(self):
        with FunctionExecutor(config=pytest.lithops_config, log_level=None) as ex:
            futures = [ex.submit(pow, 2, n) for n in (3, 4)]
            done, not_done = wait(futures, timeout=30, return_when=ALL_COMPLETED)
        assert not not_done
        assert {f.result() for f in done} == {8, 16}

    def test_map_raises_the_callables_exception(self):
        def boom(x):
            if x:
                raise ValueError('nope')
            return x

        with FunctionExecutor(config=pytest.lithops_config, log_level=None) as ex:
            it = ex.map(boom, [0, 1])
            assert next(it) == 0
            with pytest.raises(ValueError, match='nope'):
                next(it)

    def test_future_is_awaitable_via_asyncio_wrap_future(self):
        async def run():
            with FunctionExecutor(config=pytest.lithops_config, log_level=None) as ex:
                wrapped = asyncio.wrap_future(ex.submit(pow, 2, 8))
                return await wrapped

        assert asyncio.run(run()) == 256

    def test_the_executor_is_reusable_across_batches(self):
        """
        The Lithops job monitor exits once the first batch is done, so a
        second one has to bring it back
        """
        with FunctionExecutor(config=pytest.lithops_config, log_level=None) as ex:
            assert list(ex.map(abs, [-1, -2])) == [1, 2]
            time.sleep(1)
            assert list(ex.map(abs, [-3, -4])) == [3, 4]
            assert ex.submit(abs, -5).result(timeout=30) == 5

    def test_costs_no_more_storage_reads_than_the_native_api(self):
        """
        Lithops' job monitor already tracks every call with one batched
        listing per round. Reading each future's status here as well would
        put the adapter's cost at one storage request per future per round
        """
        from lithops.storage.storage import InternalStorage

        def count(run):
            reads = {'n': 0}
            original = InternalStorage.get_call_status

            def counting(self, *args, **kwargs):
                reads['n'] += 1
                return original(self, *args, **kwargs)

            InternalStorage.get_call_status = counting
            try:
                run()
            finally:
                InternalStorage.get_call_status = original
            return reads['n']

        data = list(range(4))
        expected = [x * 2 for x in data]

        def with_adapter():
            with FunctionExecutor(
                config=pytest.lithops_config, log_level=None
            ) as ex:
                assert sorted(ex.map(_sleep_and_double, data)) == expected

        def with_native_api(self=None):
            with lithops.FunctionExecutor(
                config=pytest.lithops_config, log_level=None
            ) as ex:
                futures = ex.map(_sleep_and_double, data)
                results = ex.get_result(futures, show_progressbar=False)
                assert sorted(results) == expected

        native = count(with_native_api)
        adapter = count(with_adapter)
        # Generous, on purpose: the regression this guards against is the
        # adapter reading every status every round, which is an order of
        # magnitude, not the drift between two live runs on a busy machine
        assert adapter <= native * 3 + 50, (adapter, native)


def _sleep_and_double(x):
    import time
    time.sleep(3)
    return x * 2
