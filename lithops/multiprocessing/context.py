#
# Copyright 2020 Cloudlab URV
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

import sys
import os

from . import process
from . import reduction

__all__ = []  # things are copied from here to __init__.py


#
# Exceptions
#

class ProcessError(Exception):
    pass


class BufferTooShort(ProcessError):
    pass


class TimeoutError(ProcessError):
    pass


class AuthenticationError(ProcessError):
    pass


#
# Base type for contexts
#

class BaseContext:
    ProcessError = ProcessError
    BufferTooShort = BufferTooShort
    TimeoutError = TimeoutError
    AuthenticationError = AuthenticationError

    current_process = staticmethod(process.current_process)
    active_children = staticmethod(process.active_children)

    def cpu_count(self):
        raise NotImplementedError()

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
        from .connection import RedisPipe
        return RedisPipe(duplex)

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
        return Queue()

    def JoinableQueue(self, maxsize=0):
        """Returns a queue object"""
        from .queues import JoinableQueue
        return JoinableQueue()

    def SimpleQueue(self):
        """Returns a queue object"""
        from .queues import SimpleQueue
        return SimpleQueue()

    def Pool(self, processes=None, initializer=None, initargs={}, maxtasksperchild=None):
        """Returns a process pool object"""
        from .pool import Pool
        return Pool(processes, initializer, initargs, maxtasksperchild,
                    context=self.get_context())

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

    def get_context(self, method=None):
        if method is None:
            return self
        try:
            ctx = _concrete_contexts[method]
        except KeyError:
            raise ValueError('cannot find context for %r' % method)
        ctx._check_available()
        return ctx

    def get_start_method(self, allow_none=False):
        return self._name

    def set_start_method(self, method, force=False):
        raise ValueError('cannot set start method of concrete context')

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

    def getpid(self):
        execution_id = os.environ.get('LITHOPS_EXECUTION_ID', None)
        if execution_id is not None:
            executor_id, job_id, call_id = execution_id.rsplit('/', 2)
        else:
            call_id = -1
        return call_id


#
# Type of default context -- underlying context can be set at most once
#

class Process(process.BaseProcess):
    _start_method = None

    @staticmethod
    def _Popen(process_obj):
        return _default_context.get_context().Process._Popen(process_obj)


class DefaultContext(BaseContext):
    Process = Process

    def __init__(self, context):
        self._default_context = context
        self._actual_context = None

    def get_context(self, method=None):
        if method is None:
            if self._actual_context is None:
                self._actual_context = self._default_context
            return self._actual_context
        else:
            return super().get_context(method)

    def set_start_method(self, method, force=False):
        if self._actual_context is not None and not force:
            raise RuntimeError('context has already been set')
        if method is None and force:
            self._actual_context = None
            return
        self._actual_context = self.get_context(method)

    def get_start_method(self, allow_none=False):
        if self._actual_context is None:
            if allow_none:
                return None
            self._actual_context = self._default_context
        return self._actual_context._name

    def get_all_start_methods(self):
        if sys.platform == 'win32':
            return ['spawn']
        else:
            if reduction.HAVE_SEND_HANDLE:
                return ['fork', 'spawn', 'forkserver']
            else:
                return ['fork', 'spawn']


DefaultContext.__all__ = list(x for x in dir(DefaultContext) if x[0] != '_')


#
# Context types for fixed start method
#


class SpawnCloudProcess(process.BaseProcess):
    _start_method = 'cloud'

    @staticmethod
    def _Popen(process_obj):
        from .popen_cloud import PopenCloud
        return PopenCloud(process_obj)


class SpawnCloudContext(BaseContext):
    _name = 'cloud'
    Process = SpawnCloudProcess


_concrete_contexts = {
    'fork': SpawnCloudContext(),
    'spawn': SpawnCloudContext(),
    'forkserver': SpawnCloudContext(),
    'cloud': SpawnCloudContext()
}

_default_context = DefaultContext(_concrete_contexts['cloud'])


def get_context():
    return _default_context


#
# Force the start method
#

def _force_start_method(method):
    _default_context._actual_context = _concrete_contexts[method]
