#
# Module providing various facilities to other parts of the package
#
# multiprocessing/util.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

import weakref
import redis
import uuid
import logging
import lithops
import sys
import threading
import io
from lithops.config import load_config

#
# Logging
#

NOTSET = 0
SUBDEBUG = 5
DEBUG = 10
INFO = 20
SUBWARNING = 25

_logger = logging.getLogger(lithops.__name__)
_log_to_stderr = False


def sub_debug(msg, *args):
    if _logger:
        _logger.log(SUBDEBUG, msg, *args)


def debug(msg, *args):
    if _logger:
        _logger.log(DEBUG, msg, *args)


def info(msg, *args):
    if _logger:
        _logger.log(INFO, msg, *args)


def sub_warning(msg, *args):
    if _logger:
        _logger.log(SUBWARNING, msg, *args)


def get_logger():
    return _logger


def log_to_stderr():
    raise NotImplementedError()


#
# Process function wrapper
#

def func_wrapper(func):
    pass


#
# Picklable redis client
#

class PicklableRedis(redis.StrictRedis):
    def __init__(self, *args, **kwargs):
        self._args = args
        self._kwargs = kwargs
        super().__init__(*self._args, **self._kwargs)

    def __getstate__(self):
        return self._args, self._kwargs

    def __setstate__(self, state):
        self.__init__(*state[0], **state[1])


def get_redis_client(**overwrites):
    try:
        conn_params = load_config()['redis']
    except KeyError:
        raise Exception('Redis section not found in you config')
    conn_params.update(overwrites)
    return PicklableRedis(**conn_params)


#
# Unique id for redis keys/hashes
#

def get_uuid(length=12):
    return uuid.uuid1().hex[:length]


#
# Make stateless redis Lua script (redis.client.Script)
# Just to ensure no redis client is cache'd and avoid 
# creating another connection when unpickling this object.
#

def make_stateless_script(script):
    script.registered_client = None
    return script


#
# object for counting remote references (redis keys)
# and garbage collect them automatically when nothing
# is pointing at them
#

class RemoteReference:
    def __init__(self, referenced, managed=False, client=None):
        if isinstance(referenced, str):
            referenced = [referenced]
        if not isinstance(referenced, list):
            raise TypeError("referenced must be a key (str) or"
                            "a list of keys")
        self._referenced = referenced

        # reference counter key
        self._rck = '{}-{}'.format('ref', self._referenced[0])
        self._referenced.append(self._rck)
        self._client = client or get_redis_client()

        self._callback = None
        self.managed = managed

    @property
    def managed(self):
        return self._callback is None

    @managed.setter
    def managed(self, value):
        managed = value

        if self._callback is not None:
            self._callback.atexit = False
            self._callback.detach()

        if managed:
            self._callback = None
        else:
            self._callback = weakref.finalize(self, type(self)._finalize,
                                              self._client, self._rck, self._referenced)

    def __getstate__(self):
        return (self._rck, self._referenced,
                self._client, self.managed)

    def __setstate__(self, state):
        (self._rck, self._referenced,
         self._client) = state[:-1]
        self._callback = None
        self.managed = state[-1]
        self.incref()

    def incref(self):
        if not self.managed:
            return int(self._client.incr(self._rck, 1))

    def decref(self):
        if not self.managed:
            return int(self._client.decr(self._rck, 1))

    def refcount(self):
        count = self._client.get(self._rck)
        return 1 if count is None else int(count) + 1

    def collect(self):
        if len(self._referenced) > 0:
            self._client.delete(*self._referenced)
            self._referenced = []

    @staticmethod
    def _finalize(client, rck, referenced):
        count = int(client.decr(rck, 1))
        if count < 0 and len(referenced) > 0:
            client.delete(*referenced)


class RemoteLogStream:
    def __init__(self, stream):
        self._old_stdout = sys.stdout
        self._feeder_thread = threading
        self._buff = io.StringIO()
        self._redis = get_redis_client()
        self._stream = stream
        self._offset = 0

    def write(self, log):
        self._buff.write(log)
        # self.flush()
        self._old_stdout.write(log)

    def flush(self):
        self._buff.seek(self._offset)
        log = self._buff.read()
        self._redis.publish(self._stream, log)
        self._offset = self._buff.tell()
        # self._buff = io.StringIO()
        # FIXME flush() does not empty the buffer?
        self._buff.flush()
