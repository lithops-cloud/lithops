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

"""
concurrent.futures-compatible executors backed by Lithops.

The native Lithops executors (``lithops.FunctionExecutor`` and friends)
are intentionally different from ``concurrent.futures``: ``map()`` returns
futures, there is no ``submit()``, and ``wait()`` lives on the executor.
This module is the drop-in interface for code that already talks to
``ThreadPoolExecutor`` / ``ProcessPoolExecutor``:

.. code-block:: python

    from lithops.concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor() as executor:
        future = executor.submit(pow, 2, 8)
        print(future.result())
        print(list(executor.map(abs, [-1, 2, -3])))

``Future`` subclasses ``concurrent.futures.Future``, so the standard
library's ``wait()`` and ``as_completed()`` work unchanged, including
with futures from other executors.
"""

from __future__ import annotations

import collections
import inspect
import logging
import threading
import time
from concurrent.futures import (
    ALL_COMPLETED,
    FIRST_COMPLETED,
    FIRST_EXCEPTION,
    BrokenExecutor,
    CancelledError,
    Executor as _CfExecutor,
    Future as _CfFuture,
    InvalidStateError,
    ThreadPoolExecutor as _CfThreadPool,
    TimeoutError,
    as_completed as _cf_as_completed,
    wait as _cf_wait,
)

from lithops.executors import (
    FunctionExecutor as _LithopsFunctionExecutor,
    LocalhostExecutor as _LithopsLocalhostExecutor,
    ServerlessExecutor as _LithopsServerlessExecutor,
    StandaloneExecutor as _LithopsStandaloneExecutor,
)
from lithops.future import ResponseFuture as _ResponseFuture
from lithops.retries import RetryingFunctionExecutor as _RetryingFunctionExecutor

logger = logging.getLogger(__name__)

# Re-exported so ``from lithops.concurrent.futures import wait`` is the
# concurrent.futures API, not lithops.wait (which uses a different
# return_when convention).
Executor = _CfExecutor

__all__ = [
    'ALL_COMPLETED',
    'FIRST_COMPLETED',
    'FIRST_EXCEPTION',
    'BrokenExecutor',
    'CancelledError',
    'Executor',
    'FunctionExecutor',
    'Future',
    'InvalidStateError',
    'LocalhostExecutor',
    'ProcessPoolExecutor',
    'ServerlessExecutor',
    'StandaloneExecutor',
    'ThreadPoolExecutor',
    'TimeoutError',
    'as_completed',
    'wait',
]


# How often the watcher re-reads the state the Lithops job monitor keeps in
# memory. Cheap, so it can be tight
_WATCHER_POLL_SEC = 0.1

# How often the watcher asks storage directly, which it only does for an
# executor that has no job monitor of its own
_UNMONITORED_POLL_SEC = 1.0

# Downloads of the results run here rather than in the watcher, so that one
# slow object does not hold up every other completion. Same size Lithops
# uses for its own wait()
_RESOLVER_THREADS = 64


def _call(fn, args, kwargs):
    """
    Worker-side trampoline for submit(). Lithops binds each iterdata
    element to the map function's signature, so *args/**kwargs have to
    travel as a single tuple rather than as Lithops extra_args
    """
    return fn(*args, **kwargs)


def _result_or_cancel(fut, timeout=None):
    """
    Same helper concurrent.futures.Executor.map uses: wait for one
    result, then drop the reference so a completed future can be freed
    """
    try:
        try:
            return fut.result(timeout)
        finally:
            fut.cancel()
    finally:
        del fut


def _lithops_finished(lf):
    """
    True once Lithops has a terminal or readable status. ResponseFuture
    uses properties; duck-typed wrappers (RetryingFuture) expose a subset
    """
    return bool(
        getattr(lf, 'done', False)
        or getattr(lf, 'error', False)
        or getattr(lf, 'success', False)
        or getattr(lf, 'ready', False)
    )


def _lithops_unknown(lf):
    """
    Lithops moves a future to Unknown when the job it belonged to was
    abandoned, typically by an interrupted native wait(). ``done`` is true
    for it, but there is no result behind it and no exception either
    """
    return getattr(lf, '_state', None) == _ResponseFuture.State.Unknown


def _unwrap(lf):
    """The ResponseFuture behind a wrapper such as RetryingFuture"""
    return getattr(lf, 'response_future', lf)


def _exception_from_lithops(lf):
    """
    Turns the (type, value, traceback) tuple Lithops stores into the
    exception instance concurrent.futures.Future.set_exception expects
    """
    exc = getattr(lf, '_exception', None)
    if isinstance(exc, tuple) and len(exc) >= 2:
        value = exc[1]
        if isinstance(value, BaseException):
            return value
    # A fresh ResponseFuture holds a bare Exception() as its placeholder, so
    # an empty one means the failure was never given a reason
    if isinstance(exc, BaseException) and (exc.args or type(exc) is not Exception):
        return exc
    return Exception(_failure_message(lf))


def _failure_message(lf):
    call_id = getattr(lf, 'call_id', None)
    where = f' (call {call_id})' if call_id else ''
    return f'The Lithops call failed without reporting an exception{where}'


def _unknown_state_error(lf):
    # Not a BrokenExecutor: one call was lost, the executor itself is fine
    # and still takes work
    call_id = getattr(lf, 'call_id', None)
    where = f' (call {call_id})' if call_id else ''
    return RuntimeError(
        f'Lithops lost track of the activation{where}: it is marked done '
        'but never reported a status, so there is no result to read'
    )


def _storage_of(executor):
    """
    InternalStorage of a FunctionExecutor, or of an executor that wraps one
    """
    inner = getattr(executor, 'executor', executor)
    return getattr(inner, 'internal_storage', None)


# One entry per (class, method) pair, so the signature of a Lithops future is
# only ever read once however many calls go through it
_TAKES_STORAGE = {}


def _accepts_storage(fn):
    key = (type(getattr(fn, '__self__', fn)), getattr(fn, '__name__', None))
    cached = _TAKES_STORAGE.get(key)
    if cached is None:
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            params = {}
        cached = _TAKES_STORAGE[key] = 'internal_storage' in params or any(
            param.kind is inspect.Parameter.VAR_KEYWORD
            for param in params.values()
        )
    return cached


def _with_storage(fn, storage, **kwargs):
    """
    Calls a Lithops future method, handing it the internal storage handler
    only when its signature takes one. Duck-typed futures do not all accept
    it, and a blanket ``except TypeError`` would also swallow one raised
    inside the call and run it a second time
    """
    if storage is not None and _accepts_storage(fn):
        kwargs['internal_storage'] = storage
    return fn(**kwargs)


def _set_result(fut, value):
    try:
        fut.set_result(value)
    except InvalidStateError:
        pass


def _set_exception(fut, exc):
    try:
        fut.set_exception(exc)
    except InvalidStateError:
        pass


class Future(_CfFuture):
    """
    A concurrent.futures.Future backed by a Lithops ResponseFuture.

    Created by :meth:`FunctionExecutor.submit`. The underlying Lithops
    future is available as :attr:`lithops_future` for stats and other
    Lithops-specific attributes.
    """

    def __init__(self, lithops_future=None, adapter=None):
        super().__init__()
        self._lithops_future = lithops_future
        self._adapter = adapter

    @property
    def lithops_future(self):
        """The Lithops ResponseFuture this object is tracking."""
        return self._lithops_future

    @property
    def stats(self):
        """Execution stats from the Lithops future, once they are available."""
        lf = self._lithops_future
        return getattr(lf, 'stats', {}) if lf is not None else {}

    def _sync(self):
        """
        Hands the future over for resolution the moment Lithops has a status
        for it, so a caller arriving between two watcher rounds does not have
        to sit through one. Never blocks: the download happens elsewhere and
        the caller goes on to wait on its own condition, timeout included
        """
        adapter = self._adapter
        if adapter is not None:
            adapter._nudge(self)

    def done(self):
        self._sync()
        return super().done()

    def result(self, timeout=None):
        self._sync()
        return super().result(timeout)

    def exception(self, timeout=None):
        self._sync()
        return super().exception(timeout)


class FunctionExecutor(_CfExecutor):
    """
    concurrent.futures.Executor that runs callables on Lithops workers.

    ``submit(fn, *args, **kwargs)`` and ``map(fn, *iterables)`` follow the
    standard library: ``map`` is eager and yields *results*, not futures.
    Internally, ``map`` is a single Lithops ``map()`` job rather than one
    ``submit`` per item, so a large iterator still benefits from Lithops
    batching.

    :param max_workers: Passed through to the Lithops compute backend
    :param executor: An existing ``lithops.FunctionExecutor`` (or
        compatible object) to wrap. When omitted, one is created from
        ``**kwargs``
    :param initializer: Not supported; Lithops workers are ephemeral.
        Providing a callable raises ``NotImplementedError``
    :param initargs: Ignored unless ``initializer`` is set
    :param runtime_memory: Memory (MB) for every submitted call
    :param extra_env: Extra environment variables for every submitted call
    :param execution_timeout: Max seconds each function activation may run
    :param include_modules: Modules to pickle into the worker payload
    :param exclude_modules: Modules to keep out of the worker payload
    :param kwargs: Forwarded to the Lithops executor constructor
        (``config``, ``backend``, ``storage``, ``log_level``, ...)
    """

    _executor_cls = _LithopsFunctionExecutor

    def __init__(
        self,
        max_workers=None,
        *,
        executor=None,
        initializer=None,
        initargs=(),
        runtime_memory=None,
        extra_env=None,
        execution_timeout=None,
        include_modules=None,
        exclude_modules=None,
        **kwargs,
    ):
        if initializer is not None:
            raise NotImplementedError(
                'initializer is not supported; Lithops workers are ephemeral'
            )
        if isinstance(executor, _RetryingFunctionExecutor):
            # Its retries are driven from its own wait(), which nothing here
            # calls, so wrapping it would quietly give you no retries at all
            raise TypeError(
                'RetryingFunctionExecutor is not supported: its retries are '
                'driven by its own wait(), which this adapter never calls. '
                'Wrap the FunctionExecutor it holds instead'
            )

        # Drop-in replacements of ProcessPoolExecutor / ThreadPoolExecutor
        # pass these; they are not Lithops backend keys
        for key in ('mp_context', 'max_tasks_per_child', 'thread_name_prefix'):
            kwargs.pop(key, None)

        self._runtime_memory = runtime_memory
        self._extra_env = extra_env
        self._execution_timeout = execution_timeout
        self._include_modules = include_modules
        self._exclude_modules = exclude_modules

        self._owns_executor = executor is None
        if executor is None:
            if max_workers is not None:
                kwargs['max_workers'] = max_workers
            executor = self._executor_cls(**kwargs)
        elif max_workers is not None:
            logger.debug(
                'max_workers is ignored when wrapping an existing executor'
            )
        self._inner = executor

        self._lock = threading.RLock()
        self._is_shutdown = False
        self._broken = None
        self._torn_down = False
        self._pending = {}
        self._resolving = set()
        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._watcher = None
        self._resolver = None
        self._reaper = None

    @property
    def lithops_executor(self):
        """The wrapped Lithops FunctionExecutor."""
        return self._inner

    def _lithops_inner(self):
        """
        The Lithops FunctionExecutor, unwrapping an executor that holds one
        """
        return getattr(self._inner, 'executor', self._inner)

    def _job_monitor(self):
        return getattr(self._lithops_inner(), 'job_monitor', None)

    def _job_kwargs(self):
        kwargs = {}
        if self._runtime_memory is not None:
            kwargs['runtime_memory'] = self._runtime_memory
        if self._extra_env is not None:
            kwargs['extra_env'] = self._extra_env
        if self._execution_timeout is not None:
            kwargs['timeout'] = self._execution_timeout
        if self._include_modules is not None:
            kwargs['include_modules'] = self._include_modules
        if self._exclude_modules is not None:
            kwargs['exclude_modules'] = self._exclude_modules
        return kwargs

    # -- completion tracking ------------------------------------------------

    def _ensure_watcher(self):
        """
        Starts the thread that copies Lithops completion into the
        concurrent.futures.Future condition, so wait() and as_completed()
        wake up without the caller having to poll
        """
        with self._lock:
            if self._watcher is not None and self._watcher.is_alive():
                return
            self._stop_event.clear()
            self._watcher = threading.Thread(
                target=self._watch,
                name='lithops-cf-watcher',
                daemon=True,
            )
            self._watcher.start()

    def _watch(self):
        poll = (
            _WATCHER_POLL_SEC if self._job_monitor() is not None
            else _UNMONITORED_POLL_SEC
        )
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    pairs = [
                        (fut, lf) for fut, lf in self._pending.items()
                        if fut not in self._resolving
                    ]
                    idle = not self._pending
                if idle and self._is_shutdown:
                    break
                if pairs:
                    self._revive_job_monitor([lf for _, lf in pairs])
                    for fut, lf in pairs:
                        if _CfFuture.done(fut):
                            self._forget(fut)
                        elif self._is_ready(lf):
                            self._schedule(fut, lf)
                self._wake.wait(timeout=poll)
                self._wake.clear()
        except BaseException as exc:
            self._break(exc)

    def _revive_job_monitor(self, lfs):
        """
        The Lithops job monitor is what moves futures into their Ready state,
        and the invoker starts one per job. It is a daemon that winds down
        once everything it knows about is done, so a job submitted just as it
        was exiting can be left unwatched. Native wait() guards the same way
        """
        job_monitor = self._job_monitor()
        # No monitor thread has ever run: nothing was submitted through the
        # invoker, and JobMonitor.is_alive() would fail on the missing one
        if job_monitor is None or getattr(job_monitor, 'monitor', None) is None:
            return
        try:
            if job_monitor.is_alive():
                return
            unfinished = [
                _unwrap(lf) for lf in lfs if not _lithops_finished(lf)
            ]
            if unfinished:
                job_monitor.start(fs=unfinished)
        except Exception:
            logger.debug(
                'Could not restart the Lithops job monitor', exc_info=True
            )

    def _is_ready(self, lf):
        """
        Whether the Lithops future has a status waiting to be read.

        The job monitor keeps that state up to date in memory for every
        executor that has one, so this costs nothing. Only an executor
        without a monitor is polled through storage, and then once a second:
        a per-future status read on the watcher interval would be one storage
        request per future per round
        """
        if _lithops_finished(lf):
            return True
        if self._job_monitor() is not None:
            return False
        return self._peek_status(lf) is not None

    def _peek_status(self, lf):
        status_fn = getattr(lf, 'status', None)
        if status_fn is None:
            return None
        try:
            return _with_storage(
                status_fn,
                _storage_of(self._inner),
                throw_except=False,
                check_only=True,
            )
        except Exception:
            logger.debug('Error reading the status of a call', exc_info=True)
            return None

    def _nudge(self, fut):
        """
        Fast path for a caller that reached the future first. Only looks at
        state already in memory, so done() and a timed result() never block
        on storage
        """
        if _CfFuture.done(fut) or self._broken is not None:
            return
        lf = fut._lithops_future
        if lf is not None and _lithops_finished(lf):
            self._schedule(fut, lf)

    def _resolver_pool(self):
        with self._lock:
            if self._resolver is None:
                self._resolver = _CfThreadPool(
                    max_workers=_RESOLVER_THREADS,
                    thread_name_prefix='lithops-cf-resolver',
                )
            return self._resolver

    def _schedule(self, fut, lf):
        """
        Queues the download of one result, at most once per future
        """
        with self._lock:
            if fut in self._resolving or fut not in self._pending:
                return
            self._resolving.add(fut)
        try:
            self._resolver_pool().submit(self._resolve, fut, lf)
        except RuntimeError:
            # The pool is already shutting down; finish it here instead of
            # leaving the future hanging
            self._resolve(fut, lf)

    def _resolve(self, fut, lf):
        try:
            if not _CfFuture.done(fut):
                self._apply_lithops_outcome(fut, lf)
        except Exception as exc:
            _set_exception(fut, exc)
        finally:
            with self._lock:
                self._resolving.discard(fut)
                self._pending.pop(fut, None)
            self._wake.set()

    def _apply_lithops_outcome(self, fut, lf):
        storage = _storage_of(self._inner)

        status_fn = getattr(lf, 'status', None)
        if status_fn is not None:
            _with_storage(status_fn, storage, throw_except=False)

        if getattr(lf, 'error', False):
            _set_exception(fut, _exception_from_lithops(lf))
            return
        if _lithops_unknown(lf):
            # Counts as done for Lithops, but there is no result behind it.
            # Saying so beats handing the caller a silent None
            _set_exception(fut, _unknown_state_error(lf))
            return

        value = _with_storage(lf.result, storage, throw_except=False)
        # result() marks the future as failed when the output never showed up
        if getattr(lf, 'error', False):
            _set_exception(fut, _exception_from_lithops(lf))
            return
        _set_result(fut, value)

    def _break(self, exc):
        """
        The watcher is the only thing that hands futures to the resolver, so
        if it dies every result() and wait() would block for good. Fail them
        loudly instead
        """
        logger.error(
            'The Lithops concurrent.futures watcher thread died', exc_info=exc
        )
        broken = BrokenExecutor(f'the Lithops watcher thread died: {exc!r}')
        broken.__cause__ = exc
        with self._lock:
            self._broken = broken
            pending = list(self._pending)
            self._pending.clear()
            self._resolving.clear()
        for fut in pending:
            _set_exception(fut, broken)

    def _forget(self, fut):
        with self._lock:
            self._pending.pop(fut, None)

    def _track(self, lfs):
        futures = []
        with self._lock:
            for lf in lfs:
                fut = Future(lithops_future=lf, adapter=self)
                # Lithops has already dispatched the call, so the future is
                # running as far as the caller is concerned and cancel() has
                # to decline
                fut.set_running_or_notify_cancel()
                self._pending[fut] = lf
                futures.append(fut)
        self._ensure_watcher()
        self._wake.set()
        return futures

    def _check_running(self):
        if self._broken is not None:
            raise self._broken
        if self._is_shutdown:
            raise RuntimeError('cannot schedule new futures after shutdown')

    # -- concurrent.futures.Executor ----------------------------------------

    def submit(self, fn, /, *args, **kwargs):
        with self._lock:
            self._check_running()
        payload = (fn, args, kwargs)
        job_kwargs = self._job_kwargs()
        call_async = getattr(self._inner, 'call_async', None)
        if call_async is not None:
            lf = call_async(_call, payload, **job_kwargs)
        else:
            # A duck-typed executor may only expose map()
            lf = self._inner.map(_call, [payload], **job_kwargs)[0]
        return self._track([lf])[0]

    def map(
        self,
        fn,
        *iterables,
        timeout=None,
        chunksize=None,
        buffersize=None,
    ):
        """
        Eager map, as in the standard library: it returns an iterator over
        the *results*, and every call is submitted before it does.

        ``chunksize`` is how many items each Lithops worker takes, which is
        what it means for the standard ``ProcessPoolExecutor`` too. Left
        unset, the Lithops configuration decides, rather than the standard
        library default of one item per worker overriding it
        """
        if chunksize is not None and chunksize < 1:
            raise ValueError("chunksize must be >= 1.")
        if buffersize is not None and buffersize < 0:
            raise ValueError("buffersize must be >= 0")

        end_time = None if timeout is None else timeout + time.monotonic()
        iterator = zip(*iterables)

        def take(n):
            if n is None:
                return list(iterator)
            batch = []
            for _ in range(n):
                try:
                    batch.append(next(iterator))
                except StopIteration:
                    break
            return batch

        def submit_batch(items):
            if not items:
                return []
            with self._lock:
                self._check_running()
            lfs = self._inner.map(
                _call,
                [(fn, args, {}) for args in items],
                chunksize=chunksize,
                **self._job_kwargs()
            )
            return self._track(lfs)

        fs = collections.deque(
            submit_batch(take(buffersize if buffersize else None))
        )

        def result_iterator():
            try:
                while fs:
                    remaining = (
                        None if end_time is None
                        else end_time - time.monotonic()
                    )
                    yield _result_or_cancel(fs.popleft(), remaining)
                    if buffersize:
                        fs.extend(submit_batch(take(buffersize - len(fs))))
            finally:
                for future in fs:
                    future.cancel()

        return result_iterator()

    def shutdown(self, wait=True, *, cancel_futures=False):
        with self._lock:
            self._is_shutdown = True
            pending = list(self._pending)
        if cancel_futures:
            # Lithops cannot recall an activation it already dispatched, so
            # every future here is running and declines. Kept so that callers
            # passing the standard argument still work
            for fut in pending:
                fut.cancel()
        self._wake.set()

        if wait:
            self._drain(pending)
        elif pending:
            self._start_reaper(pending)
        else:
            self._release()

    def _drain(self, pending):
        still = [fut for fut in pending if not _CfFuture.done(fut)]
        if still:
            _cf_wait(still)
        self._release()

    def _start_reaper(self, pending):
        """
        shutdown(wait=False) returns right away, but the Lithops executor
        still has to be given back once the calls in flight are done, or its
        monitor and invoker threads outlive it
        """
        with self._lock:
            if self._reaper is not None or self._torn_down:
                return
            self._reaper = threading.Thread(
                target=self._drain,
                args=(pending,),
                name='lithops-cf-reaper',
                daemon=True,
            )
            self._reaper.start()

    def _release(self):
        with self._lock:
            if self._torn_down:
                return
            self._torn_down = True
        self._stop_watcher()
        self._stop_resolver()
        self._clean_job_data()
        self._teardown_inner()

    def _stop_watcher(self):
        self._stop_event.set()
        self._wake.set()
        watcher = self._watcher
        if watcher is not None and watcher is not threading.current_thread():
            watcher.join(timeout=5)
        self._watcher = None

    def _stop_resolver(self):
        with self._lock:
            pool, self._resolver = self._resolver, None
        if pool is not None:
            # Not waited on: every future handed to it is already resolved by
            # the time we get here, and waiting from inside one of its own
            # threads would deadlock
            pool.shutdown(wait=False)

    def _clean_job_data(self):
        """
        Drops the temporary objects the jobs left in storage, which the
        native executor does from wait(). Without it they sit there until the
        atexit hook runs, which in a long-lived process can be a long while
        """
        inner = self._lithops_inner()
        if not self._owns_executor or not getattr(inner, 'data_cleaner', False):
            return
        try:
            inner.clean(clean_cloudobjects=False)
        except Exception:
            logger.debug('Error cleaning temporary job data', exc_info=True)

    def _teardown_inner(self):
        if not self._owns_executor:
            return
        try:
            self._inner.__exit__(None, None, None)
        except Exception:
            logger.debug(
                'Error shutting down the Lithops executor', exc_info=True
            )


class LocalhostExecutor(FunctionExecutor):
    """FunctionExecutor pinned to the Lithops localhost backend."""

    _executor_cls = _LithopsLocalhostExecutor


class ServerlessExecutor(FunctionExecutor):
    """FunctionExecutor pinned to a Lithops serverless backend."""

    _executor_cls = _LithopsServerlessExecutor


class StandaloneExecutor(FunctionExecutor):
    """FunctionExecutor pinned to a Lithops standalone backend."""

    _executor_cls = _LithopsStandaloneExecutor


class ProcessPoolExecutor(FunctionExecutor):
    """
    Drop-in replacement for ``concurrent.futures.ProcessPoolExecutor``.

    Tasks run on Lithops workers (localhost, serverless, or standalone)
    instead of a local ``multiprocessing`` pool. Constructor arguments
    that only apply to the standard library (``mp_context``,
    ``max_tasks_per_child``) are ignored.
    """


class ThreadPoolExecutor(FunctionExecutor):
    """
    Drop-in replacement for ``concurrent.futures.ThreadPoolExecutor``.

    Tasks still run on Lithops workers, not in local threads. Use this
    name when swapping ``from concurrent.futures import ThreadPoolExecutor``.
    ``thread_name_prefix`` is ignored.
    """


def _sync_all(fs):
    """
    Starts resolving any future Lithops already has a status for, before
    handing off to the standard library, so wait() / as_completed() do not
    sit through a watcher interval for work that is already done
    """
    for fut in fs:
        sync = getattr(fut, '_sync', None)
        if sync is not None:
            sync()


def wait(fs, timeout=None, return_when=ALL_COMPLETED):
    """Wait for futures to complete. Same contract as concurrent.futures.wait."""
    _sync_all(fs)
    return _cf_wait(fs, timeout=timeout, return_when=return_when)


def as_completed(fs, timeout=None):
    """Yield futures as they complete. Same contract as concurrent.futures.as_completed."""
    _sync_all(fs)
    return _cf_as_completed(fs, timeout=timeout)
