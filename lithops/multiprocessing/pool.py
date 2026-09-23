#
# Module providing the `Pool` class for managing a process pool
#
# multiprocessing/pool.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

#
# Imports
#
import itertools
import logging
import threading
import time

from lithops import FunctionExecutor

from . import util
from . import config as mp_config
# Aliased so that the builtin TimeoutError, which is what Lithops raises
# when a wait runs out, stays reachable in this module
from .errors import TimeoutError as ProcessTimeoutError
from .process import cloud_process_wrapper, CloudProcess

logger = logging.getLogger(__name__)

#
# Constants representing the state of a pool
#

RUN = 0
CLOSE = 1
TERMINATE = 2

#
# Miscellaneous
#

job_counter = itertools.count()

#: How often the thread that runs the callbacks of a result looks at calls
#: still running: it starts here and doubles up to the cap
HANDLER_MIN_SLEEP = 0.05
HANDLER_MAX_SLEEP = 1.0
#: How often that thread reads the status of a call from storage itself
HANDLER_STORAGE_CHECK = 10.0


#
# Class representing a process pool
#

class Pool(object):
    """
    Class which supports an async version of applying functions to arguments.
    """
    Process = CloudProcess

    def __init__(self, processes=None, initializer=None, initargs=None, maxtasksperchild=None, context=None):
        if initargs is None:
            initargs = ()

        if processes is not None and processes < 1:
            raise ValueError("Number of processes must be at least 1")
        if initializer is not None and not callable(initializer):
            raise TypeError('initializer must be a callable')

        self._state = RUN
        self._maxtasksperchild = maxtasksperchild
        self._initializer = initializer
        self._initargs = initargs

        lithops_conf = mp_config.get_parameter(mp_config.LITHOPS_CONFIG)

        if processes is not None:
            self._processes = processes
            self._executor = FunctionExecutor(max_workers=processes, **lithops_conf)
        else:
            self._executor = FunctionExecutor(**lithops_conf)
            self._processes = self._executor.invoker.max_workers

        self._remote_logger, self._logger_stream = util.setup_log_streaming(self._executor)
        self._terminated = threading.Event()
        self._handlers = []

    def _track(self, result):
        """Keeps the callback thread of a result for join() to wait on"""
        if result._handler is not None:
            self._handlers = [t for t in self._handlers if t.is_alive()]
            self._handlers.append(result._handler)
        return result

    def apply(self, func, args=(), kwds={}):
        """
        Equivalent of `func(*args, **kwds)`.
        """
        if self._state != RUN:
            raise ValueError("Pool not running")
        return self.apply_async(func, args, kwds).get()

    def map(self, func, iterable, chunksize=None):
        """
        Apply `func` to each element in `iterable`, collecting the results
        in a list that is returned.

        ``chunksize`` is how many items one worker takes, which is what it
        means for the standard library too. Left unset, the chunksize of the
        Lithops configuration applies.
        """
        return self._map_async(func, iterable, chunksize).get()

    def starmap(self, func, iterable, chunksize=None):
        """
        Like `map()` method but the elements of the `iterable` are expected to
        be iterables as well and will be unpacked as arguments. Hence
        `func` and (a, b) becomes func(a, b).
        """
        return self._map_async(func, iterable, chunksize=chunksize, starmap=True).get()

    def starmap_async(self, func, iterable, chunksize=None, callback=None, error_callback=None):
        """
        Asynchronous version of `starmap()` method.
        """
        return self._map_async(func, iterable, chunksize=chunksize,
                               callback=callback, error_callback=error_callback, starmap=True)

    def imap(self, func, iterable, chunksize=None):
        """
        Equivalent of `map()`.

        Unlike the standard library, this is not lazy: every call is
        submitted and every result collected before the first one is
        yielded. An iterator that never ends will not work here.
        """
        res = self.map(func, iterable, chunksize=chunksize)
        return IMapIterator(res)

    def imap_unordered(self, func, iterable, chunksize=None):
        """
        Like `imap()`, and like it not lazy. The results come back in the
        order of the input, which the standard library does not promise.
        """
        res = self.map(func, iterable, chunksize=chunksize)
        return IMapIterator(res)

    def apply_async(self, func, args=(), kwds={}, callback=None, error_callback=None):
        """
        Asynchronous version of `apply()` method.
        """
        if self._state != RUN:
            raise ValueError("Pool not running")

        extra_env = mp_config.get_parameter(mp_config.ENV_VARS)
        stream = self._logger_stream

        process_name = '-'.join([self._executor.executor_id, func.__name__])
        futures = self._executor.call_async(cloud_process_wrapper,
                                            data={'func': func,
                                                  'data': {
                                                      'args': args,
                                                      'kwargs': kwds
                                                  },
                                                  'initializer': self._initializer,
                                                  'initargs': self._initargs,
                                                  'name': process_name,
                                                  'log_stream': stream,
                                                  'op': 'apply'},
                                            extra_env=extra_env)

        result = ApplyResult(self._executor, [futures], callback, error_callback,
                             cancelled=self._terminated)

        return self._track(result)

    def map_async(self, func, iterable, chunksize=None, callback=None, error_callback=None):
        """
        Asynchronous version of `map()` method.
        """
        return self._map_async(func, iterable, chunksize, callback, error_callback)

    def _map_async(self, func, iterable, chunksize=None, callback=None, error_callback=None, starmap=False):
        """
        Helper function to implement map, starmap and their async counterparts.
        """
        if self._state != RUN:
            raise ValueError("Pool not running")
        if chunksize is not None and chunksize < 1:
            raise ValueError("chunksize must be >= 1")
        if not hasattr(iterable, '__len__'):
            iterable = list(iterable)

        extra_env = mp_config.get_parameter(mp_config.ENV_VARS)
        extra_args = (
            func,
            self._initializer,
            self._initargs,
            '-'.join([self._executor.executor_id, func.__name__]),
            self._logger_stream,
            'starmap' if starmap else 'map'
        )

        fmt_args = [(arg,) for arg in iterable]

        futures = self._executor.map(cloud_process_wrapper,
                                     fmt_args,
                                     chunksize=chunksize,
                                     extra_args=extra_args,
                                     extra_env=extra_env)

        result = MapResult(self._executor, futures, callback, error_callback,
                           cancelled=self._terminated)

        return self._track(result)

    def __reduce__(self):
        raise NotImplementedError('pool objects cannot be passed between processes or pickled')

    def close(self):
        logger.debug('closing pool')
        if self._state == RUN:
            self._state = CLOSE

    def terminate(self):
        logger.debug('terminating pool')
        self._state = TERMINATE
        self._terminated.set()
        self._release()

    def join(self):
        logger.debug('joining pool')
        if self._state not in (CLOSE, TERMINATE):
            raise ValueError('Pool is still running')
        if self._state == CLOSE:
            # The callbacks read the results through the executor, which
            # _release() gives back, and the standard library's join() does
            # not return before they have run either
            for handler in self._handlers:
                handler.join()
            self._handlers = []
            self._wait_for_calls()
        self._release()

    def _wait_for_calls(self):
        """
        Waits for the calls still in flight, as join() does in the standard
        library.

        Releasing the executor stops whatever is still running, so a pool
        that was closed rather than terminated has to let its calls finish
        first: their results are read from the AsyncResult afterwards, and a
        call killed here would never produce one. terminate() is the one that
        does not wait, which is what it means there too
        """
        executor = self._executor
        if executor is None:
            return
        try:
            # Nothing to wait for only when the executor says so; one that
            # does not keep a list of its futures is waited on anyway
            if not getattr(executor, 'futures', True):
                return
            # throw_except=False: a call that failed is reported by get(),
            # and raising here would force-clean the results of the ones that
            # did not, which get() still has to read
            executor.wait(
                download_results=False,
                throw_except=False,
                show_progressbar=False,
                clean_jobs=False,
            )
        except Exception:
            logger.debug('Error waiting for the pool calls', exc_info=True)

    def _release(self):
        """
        Stops the log feed and gives the Lithops executor back. Without it
        the monitor and invoker threads of the executor outlive the pool
        """
        if self._remote_logger is not None:
            self._remote_logger.stop()
            self._remote_logger = None
        executor, self._executor = self._executor, None
        if executor is not None:
            try:
                executor.__exit__(None, None, None)
            except Exception:
                logger.debug('Error shutting down the Lithops executor', exc_info=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.terminate()


class ThreadPool(Pool):
    """
    The name ``multiprocessing.pool`` uses for its thread-backed pool.

    Provided so that ``from multiprocessing.pool import ThreadPool`` keeps
    working after the import is swapped; the tasks still run on Lithops
    workers rather than in local threads.
    """


#
# Class whose instances are returned by `Pool.apply_async()`
#

class ApplyResult(object):

    def __init__(self, executor, futures, callback, error_callback, cancelled=None):
        self._job = next(job_counter)
        self._futures = futures
        self._executor = executor
        self._callback = callback
        self._error_callback = error_callback
        self._value = None
        self._exception = None
        self._collected = False
        self._cancelled = cancelled if cancelled is not None else threading.Event()
        # As in the standard library, the callbacks run once, as soon as the
        # calls finish, whether or not anybody ever calls get()
        self._event = None
        self._handler = None
        if callback is not None or error_callback is not None:
            self._event = threading.Event()
            self._handler = threading.Thread(target=self._handle, daemon=True)
            self._handler.start()

    def ready(self):
        if self._handler is not None:
            return self._event.is_set()
        # A call whose status has arrived is finished as far as the caller is
        # concerned; `done` only turns true once its result was downloaded
        return all(
            fut.ready or fut.success or fut.done or fut.error
            for fut in self._futures
        )

    def successful(self):
        if not self.ready():
            raise ValueError('{} not ready'.format(repr(self)))
        return not any(fut.error for fut in self._futures)

    def wait(self, timeout=None):
        """
        Waits for the calls, reporting nothing, as in the standard library.
        A wait that timed out leaves the result there to be fetched later
        """
        if self._handler is not None:
            self._event.wait(timeout)
            return
        try:
            self._wait(timeout, download_results=False)
        except Exception:
            logger.debug('Timed out waiting for the pool results', exc_info=True)

    def _wait(self, timeout, download_results):
        try:
            util.wait_futures(self._executor, self._futures,
                              download_results=download_results, timeout=timeout)
        except TimeoutError as exc:
            if timeout is None:
                raise
            # Lithops reports it as the builtin, which is an OSError and so
            # not what `except multiprocessing.TimeoutError` catches
            raise ProcessTimeoutError(str(exc)) from exc

    def _collect(self):
        """
        Reads the value of every call, or the exception of the first one that
        failed, from calls that have finished.

        Read from the futures rather than through get_result(), which unwraps
        a lone result depending on what the executor was last asked to do. A
        map in between would otherwise change the shape of this result, and a
        call that returns a list of its own is indistinguishable either way
        """
        storage = self._executor.internal_storage
        try:
            values = [fut.result(internal_storage=storage) for fut in self._futures]
        except Exception as exc:
            self._exception = exc
        else:
            self._value = self._unwrap(values)
            util.export_execution_details(self._futures, self._executor)
        self._collected = True

    def _unwrap(self, values):
        """The value of the single call this result stands for"""
        return values[0]

    def _handle(self):
        """
        Collects the result once the calls finish and runs the callback or
        the error_callback, which is what the result handler thread of the
        standard library does.

        The calls are polled one at a time rather than through lithops.wait,
        which cancels the process-wide SIGALRM as it returns: that alarm is
        what bounds a get(timeout) the main thread may be running meanwhile
        """
        try:
            if self._wait_in_thread():
                self._collect()
        except Exception as exc:
            self._exception = exc
        try:
            # terminate() drops the callbacks of what had not finished
            if self._cancelled.is_set():
                return
            if self._exception is None:
                if self._callback is not None:
                    self._callback(self._value)
            elif self._error_callback is not None:
                self._error_callback(self._exception)
        except Exception:
            logger.exception('Error in the callback of a pool result')
        finally:
            self._event.set()

    def _wait_in_thread(self):
        """
        Waits for every call to finish. False if the pool was terminated.

        The job monitor of the executor marks a call ready as soon as its
        status arrives, and applying that status reads nothing from storage.
        Storage itself is only asked every HANDLER_STORAGE_CHECK seconds, in
        case the monitor is not watching the call: one request per result
        and poll would add up to hundreds a second for a pool with that many
        results pending
        """
        storage = self._executor.internal_storage
        delay = HANDLER_MIN_SLEEP
        last_check = time.monotonic()
        for fut in self._futures:
            while not (fut.success or fut.done):
                if self._cancelled.is_set():
                    return False
                now = time.monotonic()
                if fut.ready or now - last_check >= HANDLER_STORAGE_CHECK:
                    if not fut.ready:
                        last_check = now
                    found = fut.status(throw_except=False,
                                       internal_storage=storage,
                                       check_only=True)
                    # A status read from storage is only recorded by that
                    # call; the next one applies it
                    if found is not None and not (fut.success or fut.done):
                        fut.status(throw_except=False,
                                   internal_storage=storage, check_only=True)
                if not (fut.success or fut.done):
                    time.sleep(delay)
                    delay = min(delay * 2, HANDLER_MAX_SLEEP)
        return True

    def get(self, timeout=None):
        if self._handler is not None:
            if not self._event.wait(timeout):
                raise ProcessTimeoutError(
                    'Timeout of {} seconds exceeded waiting for the result'.format(timeout)
                )
        elif not self._collected:
            # Download in _collect, which reraises. wait() with
            # download_results=True and throw_except=False would mark a
            # missing result as Error and hand None back
            self._wait(timeout, download_results=False)
            self._collect()
        if self._exception is not None:
            raise self._exception
        if self._cancelled.is_set() and not self._collected:
            raise ProcessTimeoutError('the pool was terminated')
        return self._value


AsyncResult = ApplyResult  # create alias


#
# Class whose instances are returned by `Pool.map_async()`
#

class MapResult(ApplyResult):

    def _unwrap(self, values):
        """The list of values, one per item of the iterable"""
        return values


#
# Class whose instances are returned by `Pool.imap()` and `Pool.imap_unordered()`
#

class IMapIterator:
    def __init__(self, result):
        self._iter_result = iter(result)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iter_result)

    def next(self):
        return self.__next__()
