#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

import logging
import lithops

from . import process
from . import pool

logger = logging.getLogger(__name__)


#
# Exceptions
#

from .errors import (  # noqa: E402  (re-exported where the stdlib keeps them)
    ProcessError,
    BufferTooShort,
    TimeoutError,
    AuthenticationError,
)


#
# Module-level helpers of the standard library that a cloud backend has
# nothing to do. They are here so that code ported from multiprocessing
# imports and calls them without an AttributeError
#

def freeze_support():
    """
    No-op. The standard library re-executes the parent script in a spawned
    child and needs this to stop it recursing; Lithops workers never do
    """


def allow_connection_pickling():
    """No-op. Lithops connections are picklable to begin with"""


def set_executable(executable):
    """No-op. There is no local interpreter to point at"""


def set_forkserver_preload(module_names):
    """No-op. There is no fork server"""


def get_logger():
    """The logger of this package, as multiprocessing.get_logger() is"""
    return logging.getLogger(__package__)


_log_to_stderr = False


def log_to_stderr(level=None):
    """
    Sends the log of this package to stderr, and returns it. Idempotent, as
    in the standard library: calling it twice does not print every line twice
    """
    global _log_to_stderr
    package_logger = get_logger()
    if not _log_to_stderr:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter('[%(levelname)s/%(processName)s] %(message)s')
        )
        package_logger.addHandler(handler)
        _log_to_stderr = True
    if level is not None:
        package_logger.setLevel(level)
    return package_logger


#
# Base type for contexts
#

class CloudContext:
    ProcessError = ProcessError
    BufferTooShort = BufferTooShort
    TimeoutError = TimeoutError
    AuthenticationError = AuthenticationError

    current_process = staticmethod(process.current_process)
    active_children = staticmethod(process.active_children)

    Process = process.CloudProcess
    Pool = pool.Pool

    def Manager(self):
        """
        Returns a manager associated with a running server process
        The managers methods such as `Lock()`, `Condition()` and `Queue()`
        can be used to create shared objects.
        """
        from .managers import SyncManager
        return SyncManager()

    def Pipe(self, duplex=True):
        """Returns two connection object connected by a pipe"""
        from .connection import Pipe
        return Pipe(duplex)

    def Lock(self):
        """Returns a non-recursive lock object"""
        from .synchronize import Lock
        return Lock()

    def RLock(self):
        """Returns a recursive lock object"""
        from .synchronize import RLock
        return RLock()

    def Condition(self, lock=None):
        """Returns a condition object"""
        from .synchronize import Condition
        return Condition(lock)

    def Semaphore(self, value=1):
        """Returns a semaphore object"""
        from .synchronize import Semaphore
        return Semaphore(value)

    def BoundedSemaphore(self, value=1):
        """Returns a bounded semaphore object"""
        from .synchronize import BoundedSemaphore
        return BoundedSemaphore(value)

    def Event(self):
        """Returns an event object"""
        from .synchronize import Event
        return Event()

    def Barrier(self, parties, action=None, timeout=None):
        """Returns a barrier object"""
        from .synchronize import Barrier
        return Barrier(parties, action, timeout)

    def Queue(self, maxsize=0):
        """Returns a queue object"""
        from .queues import Queue
        return Queue(maxsize)

    def JoinableQueue(self, maxsize=0):
        """Returns a queue object"""
        from .queues import JoinableQueue
        return JoinableQueue(maxsize)

    def SimpleQueue(self):
        """Returns a queue object"""
        from .queues import SimpleQueue
        return SimpleQueue()

    def RawValue(self, typecode_or_type, *args):
        """Returns a shared ctype"""
        from .sharedctypes import RawValue
        return RawValue(typecode_or_type, *args)

    def RawArray(self, typecode_or_type, size_or_initializer):
        """Returns a shared array"""
        from .sharedctypes import RawArray
        return RawArray(typecode_or_type, size_or_initializer)

    def Value(self, typecode_or_type, *args, lock=True):
        """Returns a synchronized shared object"""
        from .sharedctypes import Value
        return Value(typecode_or_type, *args, lock=lock,
                     ctx=self.get_context())

    def Array(self, typecode_or_type, size_or_initializer, *, lock=True):
        """Returns a synchronized shared array"""
        from .sharedctypes import Array
        return Array(typecode_or_type, size_or_initializer, lock=lock,
                     ctx=self.get_context())

    def cpu_count(self):
        """
        How many function calls can run at once: the workers of the backend
        times the processes each of them runs.

        Resolved against the configuration lithops.multiprocessing was given,
        not the one this machine happens to have, or a Pool sized from this
        is sized against the wrong backend
        """
        from . import config as mp_config
        config_data = mp_config.get_parameter(mp_config.LITHOPS_CONFIG) or None
        lithops_config = lithops.config.default_config(config_data=config_data)
        backend = lithops_config['lithops']['backend']
        max_workers = lithops_config[backend]['max_workers']
        worker_processes = lithops_config[backend]['worker_processes']
        return max_workers * worker_processes

    def get_context(self, method='cloud'):
        if method not in ['spawn', 'fork', 'forkserver', 'cloud']:
            raise ValueError('cannot find context for {}'.format(method))
        return _default_context  # For Lithops we only have CloudContext named as all contexts

    def get_all_start_methods(self):
        return ['fork', 'spawn', 'forkserver', 'cloud']

    def get_start_method(self, allow_none=False):
        return 'cloud'

    def set_start_method(self, method, force=False):
        pass

    @property
    def reducer(self):
        """Controls how objects will be reduced to a form that can be
        shared with other processes."""
        return globals().get('reduction')

    @reducer.setter
    def reducer(self, reduction):
        globals()['reduction'] = reduction

    def _check_available(self):
        pass


_default_context = CloudContext()

# multiprocessing.reducer is the reduction module of the default context.
# Nothing here reduces objects that way, so it stands at None
reducer = _default_context.reducer

cpu_count = _default_context.cpu_count
get_context = _default_context.get_context
get_all_start_methods = _default_context.get_all_start_methods
set_start_method = _default_context.set_start_method
get_start_method = _default_context.get_start_method
