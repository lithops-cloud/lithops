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

"""
In-memory stand-in for the Redis client lithops.multiprocessing runs on.

Everything in that package -- pipes, queues, locks, shared values -- talks to
Redis, so without this there is nothing to test against short of a server.
Only the commands the package actually issues are implemented, and they store
bytes the way a real server does, since some of the code compares against
byte literals.
"""

import fnmatch
import threading
import time


def _to_bytes(value):
    """What the server stores: every value becomes bytes"""
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str):
        return value.encode()
    return str(value).encode()


def _key(name):
    """
    The server does not tell a str key from the same bytes key, and the
    package reads key names back out of lists, which returns them as bytes
    """
    if isinstance(name, (bytes, bytearray, memoryview)):
        return bytes(name).decode()
    return name


# Every client unpickled from the same server keeps talking to it, the way
# reconnecting to one server does
_SERVERS = {}


def _server(server_id):
    return _SERVERS[server_id]


class FakeRedis:
    """
    A single keyspace shared by every client built from the same instance,
    the way one server is shared by every process
    """

    def __init__(self):
        self.strings = {}
        self.lists = {}
        self.expiries = {}
        self.published = []
        self.closed = False
        self.commands = []
        self._cond = threading.Condition()
        self._id = len(_SERVERS)
        _SERVERS[self._id] = self

    def __reduce__(self):
        return _server, (self._id,)

    # -- helpers used by the tests ----------------------------------------

    def keys(self, pattern='*'):
        names = set(self.strings) | set(self.lists)
        return sorted(k for k in names if fnmatch.fnmatch(k, pattern))

    def _record(self, name, *args):
        self.commands.append((name,) + args)

    # -- strings -----------------------------------------------------------

    def set(self, key, value, ex=None):
        key = _key(key)
        self._record('set', key)
        with self._cond:
            self.strings[key] = _to_bytes(value)
            if ex is not None:
                self.expiries[key] = ex
        return True

    def get(self, key):
        key = _key(key)
        self._record('get', key)
        return self.strings.get(key)

    def incr(self, key, amount=1):
        key = _key(key)
        with self._cond:
            value = int(self.strings.get(key, b'0')) + amount
            self.strings[key] = _to_bytes(value)
            return value

    def decr(self, key, amount=1):
        return self.incr(key, -amount)

    def delete(self, *keys):
        removed = 0
        with self._cond:
            for key in map(_key, keys):
                removed += self.strings.pop(key, None) is not None
                removed += self.lists.pop(key, None) is not None
                self.expiries.pop(key, None)
        return removed

    def expire(self, key, seconds):
        key = _key(key)
        self._record('expire', key, seconds)
        if key in self.strings or key in self.lists:
            self.expiries[key] = seconds
            return True
        return False

    # -- lists -------------------------------------------------------------

    def rpush(self, key, *values):
        key = _key(key)
        with self._cond:
            items = self.lists.setdefault(key, [])
            items.extend(_to_bytes(value) for value in values)
            self._cond.notify_all()
            return len(items)

    def lpush(self, key, *values):
        key = _key(key)
        with self._cond:
            items = self.lists.setdefault(key, [])
            for value in values:
                items.insert(0, _to_bytes(value))
            self._cond.notify_all()
            return len(items)

    def lpop(self, key):
        key = _key(key)
        with self._cond:
            items = self.lists.get(key)
            if not items:
                return None
            return items.pop(0)

    def blpop(self, keys, timeout=0):
        """Blocks until one of the keys has an element, as the server does"""
        if isinstance(keys, (str, bytes)):
            keys = [keys]
        keys = [_key(key) for key in keys]
        end = None if not timeout else time.monotonic() + timeout
        with self._cond:
            while True:
                for key in keys:
                    items = self.lists.get(key)
                    if items:
                        return key, items.pop(0)
                remaining = None if end is None else end - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._cond.wait(remaining)

    def llen(self, key):
        key = _key(key)
        return len(self.lists.get(key, []))

    def lrange(self, key, start, end):
        key = _key(key)
        items = self.lists.get(key, [])
        if end == -1:
            return items[start:]
        return items[start:end + 1]

    def lindex(self, key, index):
        key = _key(key)
        items = self.lists.get(key, [])
        try:
            return items[index]
        except IndexError:
            return None

    def lset(self, key, index, value):
        key = _key(key)
        items = self.lists.setdefault(key, [])
        while len(items) <= index:
            items.append(b'')
        items[index] = _to_bytes(value)
        return True

    # -- pub/sub -----------------------------------------------------------

    def publish(self, channel, message):
        self.published.append((channel, _to_bytes(message)))
        return 1

    def pubsub(self):
        return FakePubSub(self)

    # -- scripting ---------------------------------------------------------

    def register_script(self, script):
        """
        The only script the package registers is the capped release of
        SemLock, reimplemented here rather than running Lua
        """
        return FakeScript(self)

    # -- pipelines ---------------------------------------------------------

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    # -- connection --------------------------------------------------------

    def ping(self):
        if self.closed:
            raise ConnectionError('client is closed')
        return True

    def close(self):
        self.closed = True


class FakeScript:
    """What register_script() returns: a callable with a client to detach"""

    registered_client = None

    def __init__(self, server):
        self._server = server

    def __call__(self, keys, args, client=None):
        server = client if client is not None else self._server
        name = _key(keys[0])
        max_value = int(args[0])
        with server._cond:
            current = len(server.lists.get(name, []))
            if current >= max_value:
                return current
            server.lists.setdefault(name, []).append(b'')
            server._cond.notify_all()
            return current + 1


class FakePubSub:
    def __init__(self, server):
        self._server = server
        self.channels = []
        self.closed = False
        self._pending = []

    def subscribe(self, channel):
        self.channels.append(channel)
        self._pending.append({'type': 'subscribe', 'channel': channel, 'data': 1})

    def unsubscribe(self, channel=None):
        self.channels = []

    def get_message(self, ignore_subscribe_messages=False, timeout=0):
        while self._pending:
            message = self._pending.pop(0)
            if ignore_subscribe_messages and message['type'] == 'subscribe':
                continue
            return message
        return None

    def listen(self):
        while self._pending:
            yield self._pending.pop(0)

    def feed(self, channel, data):
        self._pending.append(
            {'type': 'message', 'channel': channel, 'data': _to_bytes(data)}
        )

    def close(self):
        self.closed = True


class FakePipeline:
    def __init__(self, server):
        self._server = server
        self._queued = []

    def __getattr__(self, name):
        command = getattr(self._server, name)

        def queue(*args, **kwargs):
            self._queued.append((command, args, kwargs))
            return self

        return queue

    def execute(self):
        results = [command(*args, **kwargs) for command, args, kwargs in self._queued]
        self._queued = []
        return results
