#
# Module implementing queues
#
# multiprocessing/queues.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV

__all__ = ['Queue', 'SimpleQueue', 'JoinableQueue']

import sys
import os
import threading
import collections
import time
import weakref
import errno

from queue import Empty, Full

import _multiprocessing

from . import connection
from . import util
from . import synchronize
from . import context
_ForkingPickler = context.reduction.ForkingPickler

from .util import debug, info, Finalize, register_after_fork, is_exiting

#
# Queue type using a pipe, buffer and thread
#

class Queue:

    def __init__(self):
        self._reader, self._writer = connection.Pipe(duplex=False)
        self._opid = os.getpid()
        
        # For use by concurrent.futures
        self._ignore_epipe = False

        self._after_fork()

    def __getstate__(self):
        return (self._ignore_epipe,  self._reader, 
                self._writer, self._opid, self._ref)

    def __setstate__(self, state):
        (self._ignore_epipe, self._reader,
         self._writer, self._opid, self._ref) = state
        self._after_fork()

    def _after_fork(self):
        debug('Queue._after_fork()')
        self._notempty = threading.Condition(threading.Lock())
        self._buffer = collections.deque()
        self._thread = None
        self._jointhread = None
        self._joincancelled = False
        self._closed = False
        self._close = None
        self._send_bytes = self._writer.send_bytes
        self._recv_bytes = self._reader.recv_bytes
        self._poll = self._reader.poll

    def put(self, obj, block=True, timeout=None):
        assert not self._closed

        with self._notempty:
            if self._thread is None:
                self._start_thread()
            self._buffer.append(obj)
            self._notempty.notify()

    def get(self, block=True, timeout=None):
        if block and timeout is None:
            res = self._recv_bytes()
        else:
            if block:
                if not self._poll(timeout):
                    raise Empty
            elif not self._poll():
                raise Empty
            res = self._recv_bytes()

        return _ForkingPickler.loads(res)

    def qsize(self):
        return len(self._reader)

    def empty(self):
        return not self._poll()

    def full(self):
        return False

    def get_nowait(self):
        return self.get(False)

    def put_nowait(self, obj):
        return self.put(obj, False)

    def close(self):
        self._closed = True
        try:
            self._reader.close()
        finally:
            close = self._close
            if close:
                self._close = None
                close()

    def join_thread(self):
        debug('Queue.join_thread()')
        assert self._closed
        if self._jointhread:
            self._jointhread()

    def cancel_join_thread(self):
        debug('Queue.cancel_join_thread()')
        self._joincancelled = True
        try:
            self._jointhread.cancel()
        except AttributeError:
            pass

    def _start_thread(self):
        debug('Queue._start_thread()')

        # Start thread which transfers data from buffer to pipe
        self._buffer.clear()
        self._thread = threading.Thread(
            target=type(self)._feed,
            args=(self._buffer, self._notempty, self._send_bytes,
                  self._writer.close, self._ignore_epipe),
            name='QueueFeederThread'
            )
        self._thread.daemon = True

        debug('doing self._thread.start()')
        self._thread.start()
        debug('... done self._thread.start()')

        if not self._joincancelled:
            self._jointhread = Finalize(
                self._thread, type(self)._finalize_join,
                [weakref.ref(self._thread)],
                exitpriority=-5
                )

        # Send sentinel to the thread queue object when garbage collected
        self._close = Finalize(
            self, type(self)._finalize_close,
            [self._buffer, self._notempty],
            exitpriority=10
            )

    @staticmethod
    def _finalize_join(twr):
        debug('joining queue thread')
        thread = twr()
        if thread is not None:
            thread.join()
            debug('... queue thread joined')
        else:
            debug('... queue thread already dead')

    @staticmethod
    def _finalize_close(buffer, notempty):
        debug('telling queue thread to quit')
        with notempty:
            buffer.append(_sentinel)
            notempty.notify()

    @staticmethod
    def _feed(buffer, notempty, send_bytes, close, ignore_epipe):
        debug('starting thread to feed data to pipe')
        nacquire = notempty.acquire
        nrelease = notempty.release
        nwait = notempty.wait
        bpopleft = buffer.popleft
        sentinel = _sentinel

        while 1:
            try:
                nacquire()
                try:
                    if not buffer:
                        nwait()
                finally:
                    nrelease()
                try:
                    while 1:
                        obj = bpopleft()
                        if obj is sentinel:
                            debug('feeder thread got sentinel -- exiting')
                            close()
                            return

                        obj = _ForkingPickler.dumps(obj)
                        send_bytes(obj)

                except IndexError:
                    pass
            except Exception as e:
                if ignore_epipe and getattr(e, 'errno', 0) == errno.EPIPE:
                    return
                # Since this runs in a daemon thread the resources it uses
                # may be become unusable while the process is cleaning up.
                # We ignore errors which happen after the process has
                # started to cleanup.
                if is_exiting():
                    info('error in queue thread: %s', e)
                    return
                else:
                    import traceback
                    traceback.print_exc()

_sentinel = object()


#
# Simplified Queue type
#

class SimpleQueue:

    def __init__(self):
        self._reader, self._writer = connection.Pipe(duplex=False)
        self._closed = False
        self._ref = util.RemoteReference(
            referenced=[self._reader._handle, self._reader._subhandle],
            client=self._reader._client)

    def _poll(self, timeout=0.0):
        return self._reader.poll(0.0)

    def put(self, obj):
        assert not self._closed
        obj = _ForkingPickler.dumps(obj)
        self._writer.send_bytes(obj)

    def get(self):
        res = self._reader.recv_bytes()
        return _ForkingPickler.loads(res)

    def qsize(self):
        return len(self._reader)

    def empty(self):
        return not self._poll()

    def full(self):
        return False

    def get_nowait(self):
        return self.get()

    def put_nowait(self, obj):
        return self.put(obj)

    def close(self):
        if not self._closed:
            self._reader.close()
            self._closed = True


Queue = SimpleQueue

#
# A queue type which also supports join() and task_done() methods
#

class JoinableQueue(SimpleQueue):

    def __init__(self):
        super().__init__()
        self._unfinished_tasks = synchronize.Semaphore(0)
        self._cond = synchronize.Condition()

    def put(self, obj):
        with self._cond:
            super().put(obj)
            self._unfinished_tasks.release()

    def task_done(self):
        with self._cond:
            if not self._unfinished_tasks.acquire(False):
                raise ValueError('task_done() called too many times')
            if self._unfinished_tasks.get_value() == 0:
                self._cond.notify_all()

    def join(self):
        with self._cond:
            if self._unfinished_tasks.get_value() != 0:
                self._cond.wait()