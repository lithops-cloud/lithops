#
# Module providing the `Process` class which emulates `threading.Thread`
#
# multiprocessing/process.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

#
# Imports
#

import os
import itertools
import inspect
import sys
import threading

from lithops import FunctionExecutor
from .config import get_config
from .util import get_redis_client

#
#
#

try:
    ORIGINAL_DIR = os.path.abspath(os.getcwd())
except OSError:
    ORIGINAL_DIR = None

_process_counter = itertools.count(1)
_children = set()


#
# Public functions
#

def current_process():
    """
    Return process object representing the current process
    """
    raise NotImplementedError()


def active_children():
    """
    Return list of process objects corresponding to live child processes
    """
    raise NotImplementedError()


#
# CloudProcess Class
#

class CloudProcess:
    def __init__(self, group=None, target=None, name=None, args=None, kwargs=None, *, daemon=None):
        assert group is None, 'process grouping is not implemented'
        count = next(_process_counter)

        if args is None:
            args = ()
        if kwargs is None:
            kwargs = {}

        self._config = {}
        self._identity = count
        self._parent_pid = os.getpid()
        self._target = target
        self._args = tuple(args)
        self._kwargs = dict(kwargs)
        self._name = name or (type(self).__name__ + '-' + str(self._identity))
        if daemon is not None:
            self.daemon = daemon
        lithops_config = get_config().get('lithops', {})
        self._executor = FunctionExecutor(**lithops_config)
        self._forked = False
        self._sentinel = object()
        self._logger_thread = None

    def _stdout_monitor(self, stream):
        redis = get_redis_client()
        redis_pubsub = redis.pubsub()
        redis_pubsub.subscribe(stream)

        while True:
            msg = redis_pubsub.get_message(ignore_subscribe_messages=True, timeout=10)
            if msg is None:
                continue
            sys.stdout.write(msg['data'].decode('utf-8'))

    def run(self):
        """
        Method to be run in sub-process; can be overridden in sub-class
        """
        if self._target:
            self._target(*self._args, **self._kwargs)

    def start(self):
        """
        Start child process
        """
        assert not self._forked, 'cannot start a process twice'
        assert self._parent_pid == os.getpid(), 'can only start a process object created by current process'

        sig = inspect.signature(self._target)
        pos_args = [param.name for _, param in sig.parameters.items() if param.default is inspect.Parameter.empty]
        fmt_args = dict(zip(pos_args, self._args))
        fmt_args.update(self._kwargs)

        extra_env = {}
        mp_config = get_config()
        if mp_config.get('stream_stdout'):
            extra_env['STREAM_STDOUT'] = self._executor.executor_id

        self._logger_thread = threading.Thread(target=self._stdout_monitor, args=(self._executor.executor_id,))
        self._logger_thread.daemon = True
        self._logger_thread.start()

        self._executor.call_async(self._target, fmt_args, extra_env=extra_env)
        del self._target, self._args, self._kwargs

        self._forked = True

    def terminate(self):
        """
        Terminate process; sends SIGTERM signal or uses TerminateProcess()
        """
        raise NotImplementedError()

    def join(self, timeout=None):
        """
        Wait until child process terminates
        """
        assert self._parent_pid == os.getpid(), 'can only join a child process'
        assert self._forked, 'can only join a started process'

        self._executor.wait()

    def is_alive(self):
        """
        Return whether process is alive
        """
        raise NotImplementedError()

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        assert isinstance(name, str), 'name must be a string'
        self._name = name

    @property
    def daemon(self):
        """
        Return whether process is a daemon
        """
        return self._config.get('daemon', False)

    @daemon.setter
    def daemon(self, daemonic):
        """
        Set whether process is a daemon
        """
        assert not self._forked, 'process has already started'
        self._config['daemon'] = daemonic

    @property
    def authkey(self):
        return self._config['authkey']

    @authkey.setter
    def authkey(self, authkey):
        """
        Set authorization key of process
        """
        self._config['authkey'] = authkey

    @property
    def exitcode(self):
        """
        Return exit code of process or `None` if it has yet to stop
        """
        raise NotImplementedError()

    @property
    def ident(self):
        """
        Return identifier (PID) of process or `None` if it has yet to start
        """
        raise NotImplementedError()

    pid = ident

    @property
    def sentinel(self):
        """
        Return a file descriptor (Unix) or handle (Windows) suitable for
        waiting for process termination.
        """
        try:
            return self._sentinel
        except AttributeError:
            raise ValueError("process not started")
