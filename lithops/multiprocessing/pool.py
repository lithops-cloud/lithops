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
import queue
import itertools

from lithops import FunctionExecutor

from . import util
from .context import get_context
from . import config as mp_config
from .process import CloudWorker


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
    _wrap_exception = True

    def Process(self, *args, **kwds):
        return self._ctx.Process(*args, **kwds)

    def __init__(self, processes=None, initializer=None, initargs=None, maxtasksperchild=None, context=None):
        if initargs is None:
            initargs = ()

        self._ctx = context or get_context()
        self._taskqueue = queue.Queue()
        self._cache = {}
        self._state = RUN
        self._maxtasksperchild = maxtasksperchild
        self._initializer = initializer
        self._initargs = initargs

        if processes is not None and processes < 1:
            raise ValueError("Number of processes must be at least 1")

        lithops_conf = mp_config.get_parameter(mp_config.LITHOPS_CONFIG)

        if processes is not None:
            self._processes = processes
            self._executor = FunctionExecutor(workers=processes, **lithops_conf)
        else:
            self._executor = FunctionExecutor(**lithops_conf)
            self._processes = self._executor.invoker.workers

        if initializer is not None and not callable(initializer):
            raise TypeError('initializer must be a callable')

    def apply(self, func, args=(), kwds={}):
        """
        Equivalent of `func(*args, **kwds)`.
        """
        assert self._state == RUN
        if kwds and not args:
            args = {}
        return self.apply_async(func, args, kwds).get()

    def map(self, func, iterable, chunksize=None):
        """
        Apply `func` to each element in `iterable`, collecting the results
        in a list that is returned.
        """
        return self._map_async(func, iterable, chunksize).get()

    def starmap(self, func, iterable, chunksize=None):
        """
        Like `map()` method but the elements of the `iterable` are expected to
        be iterables as well and will be unpacked as arguments. Hence
        `func` and (a, b) becomes func(a, b).
        """
        return self._map_async(func, iterable, chunksize=chunksize).get()

    def starmap_async(self, func, iterable, chunksize=None, callback=None, error_callback=None):
        """
        Asynchronous version of `starmap()` method.
        """
        return self._map_async(func, iterable, chunksize=chunksize, callback=callback, error_callback=error_callback)

    def imap(self, func, iterable, chunksize=1):
        """
        Equivalent of `map()` -- can be MUCH slower than `Pool.map()`.
        """
        res = self.map(func, iterable, chunksize=chunksize)
        return IMapIterator(res)

    def imap_unordered(self, func, iterable, chunksize=1):
        """
        Like `imap()` method but ordering of results is arbitrary.
        """
        res = self.map(func, iterable, chunksize=chunksize)
        return IMapIterator(res)

    def apply_async(self, func, args=(), kwds={}, callback=None, error_callback=None):
        """
        Asynchronous version of `apply()` method.
        """
        if self._state != RUN:
            raise ValueError("Pool not running")

        cloud_worker = CloudWorker(func=func, initializer=self._initializer, initargs=self._initargs)

        futures = self._executor.call_async(cloud_worker, data={'args': args, 'kwargs': kwds})

        result = ApplyResult(self._executor, [futures], callback, error_callback)

        return result

    def map_async(self, func, iterable, chunksize=None, callback=None, error_callback=None):
        """
        Asynchronous version of `map()` method.
        """
        return self._map_async(func, iterable, chunksize, callback, error_callback)

    def _map_async(self, func, iterable, chunksize=None, callback=None, error_callback=None):
        """
        Helper function to implement map, starmap and their async counterparts.
        """
        if self._state != RUN:
            raise ValueError("Pool not running")
        if not hasattr(iterable, '__len__'):
            iterable = list(iterable)

        cloud_worker = CloudWorker(func=func, initializer=self._initializer, initargs=self._initargs)

        if isinstance(iterable[0], dict):
            fmt_args = [{'args': (), 'kwargs': kwargs} for kwargs in iterable]
        elif isinstance(iterable[0], tuple):
            fmt_args = [{'args': args, 'kwargs': {}} for args in iterable]
        else:
            fmt_args = [{'args': (args, ), 'kwargs': {}} for args in iterable]

        futures = self._executor.map(cloud_worker, fmt_args)

        result = MapResult(self._executor, futures, callback, error_callback)

        return result

    def __reduce__(self):
        raise NotImplementedError('pool objects cannot be passed between processes or pickled')

    def close(self):
        util.debug('closing pool')
        if self._state == RUN:
            self._state = CLOSE

    def terminate(self):
        util.debug('terminating pool')
        self._state = TERMINATE
        self._executor.clean()

    def join(self):
        util.debug('joining pool')
        assert self._state in (CLOSE, TERMINATE)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.terminate()


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

    def ready(self):
        return all(fut.ready for fut in self._futures)

    def successful(self):
        if not self.ready():
            raise ValueError('{} not ready'.format(repr(self)))
        return not any(fut.error for fut in self._futures)

    def wait(self, timeout=None):
        self._executor.wait(self._futures, download_results=False, timeout=timeout, throw_except=False)

    def get(self, timeout=None):
        self.wait(timeout)
        self._value = self._executor.get_result(self._futures)

        if self._callback is not None:
            self._callback(self._value)

        return self._value

    def _set(self, i, success_result):
        self._success, self._value = success_result
        if self._callback and self._success:
            self._callback(self._value)
            self._callback = None
        if self._error_callback and not self._success:
            self._error_callback(self._value)
            self._callback = None
        # self._event.set()
        # del self._cache[self._job]


AsyncResult = ApplyResult  # create alias


#
# Class whose instances are returned by `Pool.map_async()`
#

class MapResult(ApplyResult):

    def __init__(self, executor, futures, callback, error_callback):
        ApplyResult.__init__(self, executor, futures, callback, error_callback)

        self._value = [None] * len(futures)


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
