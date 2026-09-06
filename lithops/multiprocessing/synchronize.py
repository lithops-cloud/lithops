#
# Module implementing synchronization primitives
#
# multiprocessing/synchronize.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

import threading
import math
import time
import logging

import redis

from . import util
from . import config as mp_config

logger = logging.getLogger(__name__)

#: Redis takes a fractional BLPOP timeout from 6.0 on
_BLPOP_TAKES_FLOAT = True


def _blpop(client, name, timeout):
    """
    BLPOP with a timeout the server will accept.

    A fractional one needs Redis 6.0; an older server answers with an error,
    and the wait is rounded up to the next whole second rather than cut
    short of what the caller asked for. Only a fractional timeout can
    provoke that, so a whole-second one never goes near the fallback.

    The retry is narrowed to the server rejecting the argument: a socket
    read that timed out also says "timeout", and swallowing one would both
    hide it and leave every later wait rounded to the second
    """
    if timeout is None:
        # redis-py reads None as zero, which BLPOP reads as "block for ever"
        return client.blpop([name], timeout=0)

    global _BLPOP_TAKES_FLOAT
    if _BLPOP_TAKES_FLOAT and timeout != int(timeout):
        try:
            return client.blpop([name], timeout=timeout)
        except redis.exceptions.ResponseError as exc:
            if 'timeout' not in str(exc).lower():
                raise
            _BLPOP_TAKES_FLOAT = False
            logger.debug(
                'This Redis does not take a fractional BLPOP timeout '
                '(%s); rounding waits up to the second', exc
            )
    return client.blpop([name], timeout=math.ceil(timeout))


#
# Constants
#

SEM_VALUE_MAX = 2 ** 30


#
# Base class for semaphores and mutexes
#

class SemLock:
    # KEYS[1] - semlock name
    # ARGV[1] - max value
    # return new semlock value
    # only increments its value if
    # it is not above the max value
    # Returns the new value, or -1 when the lock or semaphore was already
    # at its maximum, which is a release of something that was never held
    LUA_RELEASE_SCRIPT = """
        local current_value = tonumber(redis.call('llen', KEYS[1]))
        if current_value >= tonumber(ARGV[1]) then
            return -1
        end
        redis.call('rpush', KEYS[1], '')
        return current_value + 1
    """

    def __init__(self, value=1, max_value=1):
        self._name = 'semlock-' + util.get_uuid()
        self._max_value = max_value
        self._client = util.get_redis_client()
        logger.debug('Requested creation of resource Lock %s', self._name)
        if value != 0:
            self._client.rpush(self._name, *([''] * value))
        self._client.expire(self._name, mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))

        self._lua_release = self._client.register_script(Semaphore.LUA_RELEASE_SCRIPT)
        util.make_stateless_script(self._lua_release)

        self._ref = util.RemoteReference(self._name, client=self._client)

    def __getstate__(self):
        return (self._name, self._max_value, self._client,
                self._lua_release, self._ref)

    def __setstate__(self, state):
        (self._name, self._max_value, self._client,
         self._lua_release, self._ref) = state

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

    def get_value(self):
        value = self._client.llen(self._name)
        return int(value)

    def acquire(self, block=True, timeout=None):
        """
        Takes the lock, waiting at most ``timeout`` seconds for it.

        ``timeout`` is what the standard library takes and this used to
        reject outright. A zero or negative one is a single attempt, since
        BLPOP reads a zero timeout as "block for ever"
        """
        if not block or (timeout is not None and timeout <= 0):
            logger.debug('Requested non-blocking acquire for lock %s', self._name)
            return self._client.lpop(self._name) is not None

        if timeout is None:
            logger.debug('Requested blocking acquire for lock %s', self._name)
            self._client.blpop([self._name])
            return True

        logger.debug(
            'Requested acquire for lock %s within %s s', self._name, timeout
        )
        return _blpop(self._client, self._name, timeout) is not None

    def release(self):
        logger.debug('Requested release for lock %s', self._name)
        value = self._lua_release(keys=[self._name],
                                  args=[self._max_value],
                                  client=self._client)
        if value == -1:
            # What the standard library raises for a lock that was not held
            # and for a bounded semaphore released more often than acquired
            raise ValueError('semaphore or lock released too many times')

    def __repr__(self):
        try:
            value = self.get_value()
        except Exception:
            value = 'unknown'
        return '<%s(value=%s)>' % (self.__class__.__name__, value)


#
# Semaphore
#

class Semaphore(SemLock):
    def __init__(self, value=1):
        super().__init__(value, SEM_VALUE_MAX)


#
# Bounded semaphore
#

class BoundedSemaphore(SemLock):
    def __init__(self, value=1):
        super().__init__(value, value)


#
# Non-recursive lock
#

class Lock(SemLock):
    def __init__(self):
        super().__init__(1, 1)
        self.owned = False

    def __setstate__(self, state):
        super().__setstate__(state)
        self.owned = False

    def acquire(self, block=True, timeout=None):
        """
        Marks the lock as owned only when it was really taken.

        Setting it whatever the outcome left an RLock whose first acquire
        had failed reporting success on the next one, handing out mutual
        exclusion it did not hold
        """
        res = super().acquire(block, timeout)
        if res:
            self.owned = True
        return res

    def release(self):
        self.owned = False
        super().release()


#
# Recursive lock
#

class RLock(Lock):
    """
    A lock the same holder can take more than once.

    The recursion is counted here rather than in Redis: only the first
    acquire takes the token, and only the last release gives it back. It
    used to take one token and give back one per release, so a re-entrant
    acquire/release pair returned a token it never took
    """

    def __init__(self):
        super().__init__()
        self._count = 0

    def __setstate__(self, state):
        super().__setstate__(state)
        self._count = 0

    def acquire(self, block=True, timeout=None):
        if self.owned:
            self._count += 1
            return True
        res = super().acquire(block, timeout)
        if res:
            self._count = 1
        return res

    def release(self):
        if not self.owned:
            # The wording the standard library uses
            raise AssertionError(
                'attempt to release recursive lock not owned by thread'
            )
        self._count -= 1
        if self._count == 0:
            super().release()


#
# Condition variable
#

class Condition:
    def __init__(self, lock=None):
        if lock:
            self._lock = lock
            self._client = util.get_redis_client()
        else:
            self._lock = Lock()
            # help reducing the amount of open clients
            self._client = self._lock._client

        self._notify_handle = 'condition-notify-' + util.get_uuid()
        logger.debug('Requested creation of resource Condition %s', self._notify_handle)
        self._ref = util.RemoteReference(self._notify_handle,
                                         client=self._client)

    def acquire(self):
        return self._lock.acquire()

    def release(self):
        self._lock.release()

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, *args):
        return self._lock.__exit__(*args)

    def wait(self, timeout=None):
        assert self._lock.owned

        # Enqueue the key we will be waiting for until we are notified
        wait_handle = 'condition-wait-' + util.get_uuid()
        res = self._client.rpush(self._notify_handle, wait_handle)

        if not res:
            raise Exception('Condition ({}) could not enqueue waiting key'.format(self._notify_handle))

        # Release lock, wait to get notified, acquire lock
        self.release()
        logger.debug('Waiting for token %s on condition %s', wait_handle, self._notify_handle)
        if timeout is not None and timeout <= 0:
            # BLPOP reads a zero timeout as "block for ever"
            notified = self._client.lpop(wait_handle) is not None
        else:
            notified = _blpop(self._client, wait_handle, timeout) is not None
        self._client.expire(wait_handle, mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))
        self.acquire()
        # Whether a notify arrived, rather than the timeout expiring, which
        # is what the standard library returns and callers branch on
        return notified

    def notify(self):
        assert self._lock.owned

        logger.debug('Notify condition %s', self._notify_handle)
        wait_handle = self._client.lpop(self._notify_handle)
        if wait_handle is not None:
            res = self._client.rpush(wait_handle, '')

            if not res:
                raise Exception('Condition ({}) could not notify one waiting process'.format(self._notify_handle))

    def notify_all(self, msg=''):
        assert self._lock.owned

        logger.debug('Notify all for condition %s', self._notify_handle)
        pipeline = self._client.pipeline(transaction=False)
        pipeline.lrange(self._notify_handle, 0, -1)
        pipeline.delete(self._notify_handle)
        wait_handles, _ = pipeline.execute()

        if len(wait_handles) > 0:
            pipeline = self._client.pipeline(transaction=False)
            for handle in wait_handles:
                pipeline.rpush(handle, msg)
            results = pipeline.execute()

            if not all(results):
                raise Exception('Condition ({}) could not notify all waiting processes'.format(self._notify_handle))

    def wait_for(self, predicate, timeout=None):
        result = predicate()
        if result:
            return result
        if timeout is not None:
            endtime = time.monotonic() + timeout
        else:
            endtime = None
            waittime = None
        while not result:
            if endtime is not None:
                waittime = endtime - time.monotonic()
                if waittime <= 0:
                    break
            self.wait(waittime)
            result = predicate()
        return result


#
# Event
#

class Event:
    def __init__(self):
        self._cond = Condition()
        self._client = self._cond._client
        self._flag_handle = 'event-flag-' + util.get_uuid()
        logger.debug('Requested creation of resource Event %s', self._flag_handle)
        self._ref = util.RemoteReference(self._flag_handle,
                                         client=self._client)

    def is_set(self):
        logger.debug('Request event %s is set', self._flag_handle)
        return self._client.get(self._flag_handle) == b'1'

    def set(self):
        with self._cond:
            logger.debug('Request set event %s', self._flag_handle)
            self._client.set(self._flag_handle, '1')
            self._cond.notify_all()

    def clear(self):
        with self._cond:
            logger.debug('Request clear event %s', self._flag_handle)
            self._client.set(self._flag_handle, '0')

    def wait(self, timeout=None):
        """
        Waits for the flag and reports it, as in the standard library, where
        `if event.wait(timeout):` is how a timeout is told from a set flag
        """
        with self._cond:
            logger.debug('Request wait for event %s', self._flag_handle)
            return bool(self._cond.wait_for(self.is_set, timeout))


#
# Barrier
#

class Barrier(threading.Barrier):
    def __init__(self, parties, action=None, timeout=None):
        self._cond = Condition()
        self._client = self._cond._client
        uuid = util.get_uuid()
        self._state_handle = 'barrier-state-' + uuid
        self._count_handle = 'barrier-count-' + uuid
        self._ref = util.RemoteReference(referenced=[self._state_handle, self._count_handle],
                                         client=self._client)
        self._action = action
        self._timeout = timeout
        self._parties = parties
        self._state = 0  # 0 = filling, 1 = draining, -1 = resetting, -2 = broken
        self._count = 0

    @property
    def _state(self):
        return int(self._client.get(self._state_handle))

    @_state.setter
    def _state(self, value):
        self._client.set(self._state_handle, value, ex=mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))

    @property
    def _count(self):
        return int(self._client.get(self._count_handle))

    @_count.setter
    def _count(self, value):
        self._client.set(self._count_handle, value, ex=mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))
