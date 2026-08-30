#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

from .context import (
    ProcessError,
    BufferTooShort,
    TimeoutError,
    AuthenticationError,
    cpu_count,
    get_context,
    get_all_start_methods,
    set_start_method,
    get_start_method,
    freeze_support,
    allow_connection_pickling,
    set_executable,
    set_forkserver_preload,
    get_logger,
    log_to_stderr,
    reducer
)
from .context import CloudContext as DefaultContext
from .connection import Pipe
from .managers import SyncManager as Manager
from .pool import Pool
from .process import CloudProcess as Process
from .queues import Queue, SimpleQueue, JoinableQueue
from .sharedctypes import RawValue, RawArray, Value, Array
from .synchronize import (
    Semaphore,
    BoundedSemaphore,
    Lock,
    RLock,
    Condition,
    Event,
    Barrier
)
from .process import current_process, active_children, parent_process


from . import config


__all__ = [
    'ProcessError',
    'BufferTooShort',
    'TimeoutError',
    'AuthenticationError',
    'allow_connection_pickling',
    'freeze_support',
    'get_logger',
    'log_to_stderr',
    'reducer',
    'set_executable',
    'set_forkserver_preload',
    'cpu_count',
    'get_context',
    'get_all_start_methods',
    'set_start_method',
    'get_start_method',
    'DefaultContext',
    'Pipe',
    'Manager',
    'Pool',
    'Process',
    'Queue',
    'SimpleQueue',
    'JoinableQueue',
    'RawValue',
    'RawArray',
    'Value',
    'Array',
    'Semaphore',
    'BoundedSemaphore',
    'Lock',
    'RLock',
    'Condition',
    'Event',
    'Barrier',
    'current_process',
    'active_children',
    'parent_process',
    'config'
]

# `lithops.multiprocessing.context` is left as the module it is, the way
# `multiprocessing.context` is. Binding an instance over it here made every
# `mp.context.<name>` of ported code fail. The class is `DefaultContext`
