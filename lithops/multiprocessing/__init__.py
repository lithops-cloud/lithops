#
# Package analogous to 'threading.py' but using processes
#
# multiprocessing/__init__.py
#
# This package is intended to duplicate the functionality (and much of
# the API) of threading.py but uses processes instead of threads.  A
# subpackage 'multiprocessing.dummy' has the same API but is a simple
# wrapper for 'threading'.
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

from .context import BaseContext
from .connection import RedisPipe as Pipe
from .managers import SyncManager as Manager
from .pool import Pool
from .process import CloudProcess as Process
from .queues import Queue, SimpleQueue, JoinableQueue
from .sharedctypes import RawValue, RawArray, Value, Array
from .synchronize import (Semaphore, BoundedSemaphore,
                          Lock, RLock,
                          Condition, Event, Barrier)

context = BaseContext()
getpid = context.getpid
