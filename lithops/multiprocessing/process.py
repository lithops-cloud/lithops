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
import traceback
import os
import logging
import multiprocessing as _mp

from lithops import FunctionExecutor
from lithops.utils import is_lithops_worker
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
logger = logging.getLogger(__name__)


#
# Public functions
#

class _CurrentProcess:
    """
    What current_process() reports from inside a worker. Only the identity
    of the running call: building a CloudProcess here would create a Lithops
    executor and a Redis client just to read a name back
    """

    def __init__(self, name, pid):
        self.name = name
        self._pid = pid
        self.daemon = False
        self.exitcode = None

    @property
    def ident(self):
        return self._pid

    pid = ident

    def is_alive(self):
        return True

    def __repr__(self):
        return '<{}(name={}, pid={})>'.format(
            type(self).__name__, self.name, self._pid
        )


def current_process():
    """
    Return process object representing the current process
    """
    if is_lithops_worker():
        return _CurrentProcess(
            name=os.environ.get('LITHOPS_MP_WORKER_NAME'),
            pid=os.environ.get('__LITHOPS_SESSION_ID', '-1'),
        )
    else:
        return _mp.current_process()


def active_children():
    """
    Return list of process objects corresponding to live child processes
    """
    raise NotImplementedError()


def parent_process():
    """
    Return process object representing the parent process
    """
    raise NotImplementedError()


#
# Cloud worker
#

def cloud_process_wrapper(data, func, initializer=None, initargs=(), name=None, log_stream=None, op=None):
    # Put the worker name in the environment, which is where current_process()
    # reads it back from
    os.environ['LITHOPS_MP_WORKER_NAME'] = name or 'CloudProcess'

    # Setup remote logger
    if log_stream is not None:
        remote_log_buff = util.RemoteLogIOBuffer(log_stream)
        remote_log_buff.start()
    else:
        remote_log_buff = None

    # Execute worker initializer function
    if initializer is not None:
        initializer(*initargs)

    try:
        if op == 'apply':
            return func(*data['args'], **data['kwargs'])
        elif op == 'map':
            return func(data,)
        elif op == 'starmap':
            return func(*data)
        else:
            raise ValueError('Unknown operation {}'.format(op))
    except Exception as e:
        # Print exception stack trace to remote logging buffer
        header = "---------- {} at {} ({}) ----------".format(e.__class__.__name__,
                                                              os.environ.get('LITHOPS_MP_WORKER_NAME'),
                                                              os.environ.get('__LITHOPS_SESSION_ID'))
        exception_body = traceback.format_exc()
        footer = '-' * len(header)
        if remote_log_buff:
            remote_log_buff.write('\n'.join([header, exception_body, footer, '']))
        raise
    finally:
        if remote_log_buff:
            remote_log_buff.flush()
            remote_log_buff.stop()


#
# CloudProcess Class
#

class CloudProcess:
    def __init__(self, group=None, target=None, name=None, args=None, kwargs=None, *, daemon=None):
        assert group is None, 'process grouping is not implemented'

        if args is None:
            args = ()
        if kwargs is None:
            kwargs = {}

        self._config = {}
        self._parent_pid = os.getpid()
        self._target = target
        self._args = tuple(args)
        self._kwargs = dict(kwargs)
        self._name = name or (type(self).__name__ + '-' + str(next(_process_counter)))
        self._pid = None
        if daemon is not None:
            self.daemon = daemon
        # The executor is built by start(): a process that is never started
        # should not leave a monitor and an invoker thread behind, and a
        # process talks to Lithops rather than to Redis
        self._executor = None
        self._future = None
        self._sentinel = object()
        self._remote_logger = None

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
        assert not self._pid, 'cannot start a process twice'
        assert self._parent_pid == os.getpid(), 'can only start a process object created by current process'

        lithops_config = mp_config.get_parameter(mp_config.LITHOPS_CONFIG)
        self._executor = FunctionExecutor(**lithops_config)
        self._remote_logger, stream = util.setup_log_streaming(self._executor)

        extra_env = mp_config.get_parameter(mp_config.ENV_VARS)

        process_name = '-'.join([self._name, self._target.__name__])
        self._future = self._executor.call_async(cloud_process_wrapper,
                                                 {'func': self._target,
                                                  'data': {
                                                      'args': self._args,
                                                      'kwargs': self._kwargs
                                                  },
                                                  'initializer': None,
                                                  'initargs': None,
                                                  'name': process_name,
                                                  'log_stream': stream,
                                                  'op': 'apply'},
                                                 extra_env=extra_env)
        self._pid = '/'.join([self._future.executor_id, self._future.job_id, self._future.call_id])
        del self._target, self._args, self._kwargs

    def terminate(self):
        """
        Terminate process; sends SIGTERM signal or uses TerminateProcess()
        """
        raise NotImplementedError()

    def kill(self):
        """
        Terminate process; sends SIGKILL signal or uses TerminateProcess()
        """
        raise NotImplementedError()

    def close(self):
        """
        Releases the resources of the process, which cannot be used again.

        Unlike the standard library this does not refuse to close a process
        still running: Lithops cannot tell whether the activation is over
        without asking storage, and the call outlives this object either way
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

    def join(self, timeout=None):
        """
        Wait until child process terminates
        """
        assert self._parent_pid == os.getpid(), 'can only join a child process'
        assert self._pid, 'can only join a started process'

        exception = None
        try:
            self._executor.wait(fs=[self._future], timeout=timeout)
        except Exception as e:
            exception = e
        finally:
            if self._remote_logger:
                self._remote_logger.stop()
                self._remote_logger = None

            util.export_execution_details([self._future], self._executor)

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
        assert not self._pid, 'process has already started'
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
        return self._pid

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
