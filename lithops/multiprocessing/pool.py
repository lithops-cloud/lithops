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

        result = ApplyResult(self._executor, [futures], callback, error_callback)

        return result

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

        result = MapResult(self._executor, futures, callback, error_callback)

        return result

    def __reduce__(self):
        raise NotImplementedError('pool objects cannot be passed between processes or pickled')

    def close(self):
        logger.debug('closing pool')
        if self._state == RUN:
            self._state = CLOSE

    def terminate(self):
        logger.debug('terminating pool')
        self._state = TERMINATE
        self._release()

    def join(self):
        logger.debug('joining pool')
        if self._state not in (CLOSE, TERMINATE):
            raise ValueError('Pool is still running')
        self._release()

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

    def __init__(self, executor, futures, callback, error_callback):
        self._job = next(job_counter)
        self._futures = futures
        self._executor = executor
        self._callback = callback
        self._error_callback = error_callback
        self._value = None
        self._exception = None

    def ready(self):
        # A call whose status has arrived is finished as far as the caller is
        # concerned; `done` only turns true once its result was downloaded
        return all(
            fut.success or fut.done or fut.error for fut in self._futures
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
        try:
            self._executor.wait(self._futures, download_results=False, timeout=timeout)
        except Exception:
            logger.debug('Timed out waiting for the pool results', exc_info=True)

    def _get_values(self, timeout=None):
        """
        The value of every call, in order.

        Read from the futures rather than through get_result(), which unwraps
        a lone result depending on what the executor was last asked to do. A
        map in between would otherwise change the shape of this result, and a
        call that returns a list of its own is indistinguishable either way
        """
        try:
            self._executor.wait(
                self._futures, download_results=True, timeout=timeout
            )
        except TimeoutError as exc:
            # Lithops reports it as the builtin, which is an OSError and so
            # not what `except multiprocessing.TimeoutError` catches
            raise ProcessTimeoutError(str(exc)) from exc
        values = [fut.result() for fut in self._futures]
        util.export_execution_details(self._futures, self._executor)
        return values

    def get(self, timeout=None):
        """The value of the single call this result stands for"""
        self._value = self._get_values(timeout)[0]
        if self._callback is not None:
            self._callback(self._value)
        return self._value


AsyncResult = ApplyResult  # create alias


#
# Class whose instances are returned by `Pool.map_async()`
#

class MapResult(ApplyResult):

    def get(self, timeout=None):
        """The list of values, one per item of the iterable"""
        self._value = self._get_values(timeout)
        if self._callback is not None:
            self._callback(self._value)
        return self._value


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
