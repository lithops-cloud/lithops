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

import itertools
import sys
import traceback
import os

from lithops import FunctionExecutor
from . import config as mp_config
from . import util

#
#
#

try:
    ORIGINAL_DIR = os.path.abspath(os.getcwd())
except OSError:
    ORIGINAL_DIR = None

_process_counter = itertools.count(1)
_children = set()
logger = util.get_logger()


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
# Cloud worker
#

class CloudWorker:
    def __init__(self, func, initializer=None, initargs=(), log_stream=None):
        self._func = func
        self._initializer = initializer
        self._initargs = initargs
        self.log_stream = None

    def __call__(self, *args, **kwargs):
        if self.log_stream is not None:
            remote_log_buff = util.RemoteLogIOBuffer(self.log_stream)
        else:
            remote_log_buff = None

        if self._initializer is not None:
            self._initializer(*self._initargs)

        if remote_log_buff:
            remote_log_buff.start()

        try:
            res = self._func(*kwargs['args'], **kwargs['kwargs'])
            exception = None
            return res
        except Exception as e:
            exception = e
            header = "---------- {}: {} at {} ----------".format(e.__class__.__name__, e,
                                                                 os.environ.get('LITHOPS_EXECUTION_ID'))
            exception_body = traceback.format_exc()
            footer = '-' * len(header)
            if remote_log_buff:
                remote_log_buff.write('\n'.join([header, exception_body, footer, '']))
                remote_log_buff.flush()
        finally:
            if remote_log_buff:
                remote_log_buff.flush()
                remote_log_buff.stop()

        if exception:
            raise exception

    @property
    def __name__(self):
        return self._func.__name__


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
        lithops_config = mp_config.get_parameter(mp_config.LITHOPS_CONFIG)
        self._executor = FunctionExecutor(**lithops_config)
        self._forked = False
        self._sentinel = object()
        self._remote_logger = None
        self._redis = util.get_redis_client()

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

        cloud_worker = CloudWorker(self._target)

        if mp_config.get_parameter(mp_config.STREAM_STDOUT):
            stream = self._executor.executor_id
            logger.debug('Log streaming enabled, stream name: {}'.format(stream))
            self._remote_logger = util.RemoteLoggingFeed(stream)
            self._remote_logger.start()
            cloud_worker.log_stream = stream

        extra_env = mp_config.get_parameter(mp_config.ENV_VARS)

        self._executor.call_async(cloud_worker, {'args': self._args, 'kwargs': self._kwargs}, extra_env=extra_env)
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

        try:
            self._executor.wait()
            exception = None
        except Exception as e:
            exception = e
        finally:
            if self._remote_logger:
                self._remote_logger.stop()
            if exception:
                raise exception

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
