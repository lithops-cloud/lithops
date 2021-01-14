#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

from .context import BaseContext, get_context
from .connection import RedisPipe as Pipe
from .managers import SyncManager as Manager
from .pool import Pool
from .process import CloudProcess as Process
from .queues import Queue, SimpleQueue, JoinableQueue
from .sharedctypes import RawValue, RawArray, Value, Array
from .synchronize import (Semaphore, BoundedSemaphore,
                          Lock, RLock,
                          Condition, Event, Barrier)


from . import config

context = BaseContext()
getpid = context.getpid
