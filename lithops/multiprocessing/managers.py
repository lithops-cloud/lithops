#
# Module providing the `SyncManager` class for dealing
# with shared objects
#
# multiprocessing/managers.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

#
# Imports
#

import redis
import inspect
import types
import cloudpickle
import logging

from . import pool
from . import synchronize
from . import queues
from . import util
from . import config as mp_config

logger = logging.getLogger(__name__)

_builtin_types = {
    'list',
    'dict',
    'Namespace',
    'Lock',
    'RLock',
    'Semaphore',
    'BoundedSemaphore',
    'Condition',
    'Event',
    'Barrier',
    'Queue',
    'Value',
    'Array',
    'JoinableQueue',
    'SimpleQueue',
    'Pool'
}


#
# Helper functions
#

def deslice(slic: slice):
    start = slic.start
    end = slic.stop
    step = slic.step

    if start is None:
        start = 0
    if end is None:
        end = -1
    elif start == end or end == 0:
        return None, None, None
    else:
        end -= 1

    return start, end, step


#
# Definition of BaseManager
#

class BaseManager:
    """
    Base class for managers
    """
    _registry = {}

    def __init__(self, address=None, authkey=None, serializer='pickle', ctx=None):
        self._client = util.get_redis_client()
        self._managing = False
        self._mrefs = []

    @property
    def address(self):
        """
        Where the shared objects live. There is no manager process here, so
        this is the Redis the proxies talk to rather than a socket
        """
        config = (util.LITHOPS_CONFIG or {}).get('redis') or {}
        return (config.get('host'), config.get('port'))

    def get_server(self):
        pass

    def connect(self):
        pass

    def start(self, initializer=None, initargs=()):
        self._managing = True

    def _create(self, typeid, *args, **kwds):
        """
        Create a new shared object; return the token and exposed tuple
        """
        pass

    def join(self, timeout=None):
        pass

    def _number_of_objects(self):
        """
        Return the number of shared objects
        """
        return len(self._mrefs)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()

    def shutdown(self):
        if self._managing:
            for ref in self._mrefs:
                ref.collect()
            self._mrefs = []
            self._managing = False

    @classmethod
    def register(cls, typeid, callable=None, proxytype=None, exposed=None,
                 method_to_typeid=None, create_method=True, can_manage=True):
        """
        Register a typeid with the manager type.

        The standard library's signature is
        ``register(typeid, callable=None, proxytype=None, ...)``, and its
        documented idiom passes the class as ``callable``. The two were the
        other way round here and ``callable`` was accepted and then ignored,
        so the documented form built a proxy of None and blew up on first
        use. Both names now mean the same thing -- the class to stand in
        for -- and ``proxytype`` wins when both are given
        """
        klass = proxytype if proxytype is not None else callable

        def temp(self, *args, **kwargs):
            logger.debug('requesting creation of a shared %r object', typeid)

            if typeid in _builtin_types:
                proxy = klass(*args, **kwargs)
            else:
                proxy = GenericProxy(typeid, klass, *args, **kwargs)

            if self._managing and can_manage and hasattr(proxy, '_ref'):
                proxy._ref.managed = True
                self._mrefs.append(proxy._ref)
            return proxy

        temp.__name__ = typeid
        setattr(cls, typeid, temp)


#
# Definition of BaseProxy
#

class BaseProxy:
    """
    A base for proxies of shared objects
    """

    #: A class attribute, not an instance one. Held on the instance it went
    #: into __dict__, and a module cannot be pickled: every proxy needed
    #: cloudpickle to travel, where the standard library's pickle plainly
    _pickler = cloudpickle

    def __init__(self, typeid, serializer=None):
        self._typeid = typeid
        # object id
        self._oid = '{}-{}'.format(typeid, util.get_uuid())

        self._client = util.get_redis_client()
        self._ref = util.RemoteReference(self._oid, client=self._client)

    def _getvalue(self):
        """
        A copy of the referent, which is what the standard library's
        BaseProxy._getvalue() hands back
        """
        referent = getattr(self, '_referent', None)
        if referent is None:
            raise NotImplementedError(
                '{} has no referent to copy'.format(type(self).__name__)
            )
        return referent()

    def _callmethod(self, methodname, args=(), kwds=None):
        """
        Calls a method of the referent by name.

        The standard library's proxies reach the manager process through
        this; here the proxy already implements the methods, so it forwards
        to itself. Provided because code written against the standard
        library calls it directly
        """
        method = getattr(self, methodname, None)
        if method is None:
            raise AttributeError(
                '{!r} object has no method {!r}'.format(
                    type(self).__name__, methodname)
            )
        return method(*args, **(kwds or {}))

    def __deepcopy__(self, memo):
        """
        A plain copy of the referent. Without it, copy.deepcopy() walks the
        proxy's own attributes and duplicates the Redis client
        """
        import copy as _copy

        selfcopy = _copy.deepcopy(self._getvalue(), memo)
        memo[id(self)] = selfcopy
        return selfcopy

    def _expiry(self):
        return mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME)

    def _field(self, k):
        """
        The hash field a key is stored under.

        Keys used to be handed to redis-py as they were, which accepts only
        bytes, str, int and float: a tuple key raised DataError, and an int
        or float key came back out of keys() as a str, so d[1] = x then
        d.items() gave ('1', x). Pickling the key keeps whatever the caller
        put in. Lives here rather than on DictProxy because NamespaceProxy
        borrows those methods unbound
        """
        return self._pickler.dumps(k)

    def __repr__(self):
        return '<{} object, typeid={}, key={}>'.format(type(self).__name__, self._typeid, self._oid)

    def __str__(self):
        """
        The referent's repr, which is what the standard library's proxies
        print. Falling back to the proxy's own repr made print(shared_list)
        show <ListProxy object, ...> instead of the list
        """
        referent = getattr(self, '_referent', None)
        if referent is None:
            return repr(self)
        try:
            return repr(referent())
        except Exception:
            return repr(self)


#
# Types/callables which we will register with SyncManager
#

class GenericProxy(BaseProxy):
    def __init__(self, typeid, klass, *args, **kwargs):
        super().__init__(typeid)
        self._klass = klass
        self._init_args = (args, kwargs)

        obj = self._after_fork()
        self._init_obj(obj)

    def _after_fork(self):
        args, kwargs = self._init_args
        obj = self._klass(*args, **kwargs)

        for attr_name in (attr for attr in dir(obj) if inspect.ismethod(getattr(obj, attr))):
            wrap = MethodWrapper(self, attr_name, obj)
            setattr(self, attr_name, wrap)

        return obj

    def _init_obj(self, obj):

        if not hasattr(obj, '__shared__'):
            shared = list(vars(obj).keys())
        else:
            shared = obj.__shared__

        pipeline = self._client.pipeline()
        for attr_name in shared:
            attr = getattr(obj, attr_name)
            attr_bin = self._pickler.dumps(attr)
            pipeline.hset(self._oid, attr_name, attr_bin)
        pipeline.expire(self._oid, mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))
        pipeline.execute()

    def __getstate__(self):
        return {
            '_typeid': self._typeid,
            '_oid': self._oid,
            '_client': self._client,
            '_ref': self._ref,
            '_klass': self._klass,
            '_init_args': self._init_args,
        }

    def __setstate__(self, state):
        self._typeid = state['_typeid']
        self._oid = state['_oid']
        self._client = state['_client']
        self._ref = state['_ref']
        self._klass = state['_klass']
        self._init_args = state['_init_args']
        self._after_fork()


class MethodWrapper:
    def __init__(self, proxy, attr_name, shared_object):
        self._attr_name = attr_name
        self._shared_object = shared_object
        self._proxy = proxy

    #: How long a method call may hold the object, and how long another
    #: one waits for it. Bounded so a worker that dies mid-call cannot lock
    #: the object up for the rest of the job
    LOCK_TIMEOUT = 60

    def __call__(self, *args, **kwargs):
        # Read state, run the method, write back what changed -- with
        # nothing to stop two workers doing that at once, both read the same
        # state and the second overwrote the first: counter.increment()
        # called twice concurrently left the counter at one. The standard
        # library runs every call in the manager's own process, one at a
        # time, and this is what stands in for that
        client = self._proxy._client
        with client.lock(self._proxy._oid + '-call',
                         timeout=self.LOCK_TIMEOUT,
                         blocking_timeout=self.LOCK_TIMEOUT):
            return self._call(*args, **kwargs)

    def _call(self, *args, **kwargs):
        attrs = self._proxy._client.hgetall(self._proxy._oid)

        hashes = {}

        for attr_name, attr_bin in attrs.items():
            attr_name = attr_name.decode('utf-8')
            attr = self._proxy._pickler.loads(attr_bin)
            hashes[attr_name] = hash(attr_bin)
            setattr(self._shared_object, attr_name, attr)

        attr = getattr(self._shared_object, self._attr_name)
        if callable(attr):
            result = attr.__call__(*args, **kwargs)
        else:
            result = attr

        if not hasattr(self._shared_object, '__shared__'):
            shared = list(vars(self._shared_object).keys())
        else:
            shared = self._shared_object.__shared__

        pipeline = self._proxy._client.pipeline()
        for attr_name in shared:
            attr = getattr(self._shared_object, attr_name)
            attr_bin = self._proxy._pickler.dumps(attr)
            # A method that sets an attribute for the first time leaves a
            # name the pre-call HGETALL never saw, and looking it up used to
            # raise KeyError from inside the call
            if hash(attr_bin) != hashes.get(attr_name):
                pipeline.hset(self._proxy._oid, attr_name, attr_bin)
        pipeline.expire(self._proxy._oid, mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))
        pipeline.execute()

        return result


class ListProxy(BaseProxy):
    # NOTE: list slices should return an instance of a ListProxy
    #       or a native python list?
    #
    #          A = ListProxy([1, 2, 3])
    #          B = A[:2]
    #          C = A + [4, 5]
    #          D = A * 3
    #
    #        Following the multiprocessing implementation, lists (B,
    #        C, D) are plain python lists while A is the only ListProxy.
    #        This could cause problems like these:
    #
    #          A = A[2:]
    #
    #        with A being a python list after executing that line.
    #
    #        Current implementation is the same as multiprocessing

    # KEYS[1] - key to extend
    # KEYS[2] - key to extend with
    # ARGV[1] - number of repetitions
    # A = A + B * C
    LUA_EXTEND_LIST_SCRIPT = """
        local values = redis.call('LRANGE', KEYS[2], 0, -1)
        if #values == 0 then
            return
        else
            for i=1,tonumber(ARGV[1]) do
                redis.call('RPUSH', KEYS[1], unpack(values))
            end
        end
    """

    def __init__(self, iterable=None):
        super().__init__('list')
        self._lua_extend_list = self._client.register_script(ListProxy.LUA_EXTEND_LIST_SCRIPT)
        util.make_stateless_script(self._lua_extend_list)

        if iterable is not None:
            self.extend(iterable)

    def _mutate(self, change):
        """
        Reads the whole list, hands it to ``change`` and writes back what it
        returns, as one atomic step.

        Redis has no slice assignment, sort or insert, so these have to be
        done here. WATCH is what makes that safe: another client writing to
        the key between the read and the write aborts the transaction and it
        is retried, instead of that write being silently dropped. The old
        code did DELETE followed by RPUSH with no guard at all, so a
        concurrent append was lost and readers saw an empty list in between

        ``change`` returns ``(new_items, answer)`` and ``answer`` is handed
        back to the caller
        """
        answer = {}

        def apply(pipe):
            raw = pipe.lrange(self._oid, 0, -1)
            items = [self._pickler.loads(v) for v in raw]
            new_items, answer['value'] = change(items)
            pipe.multi()
            pipe.delete(self._oid)
            if new_items:
                pipe.rpush(
                    self._oid, *[self._pickler.dumps(v) for v in new_items]
                )
                pipe.expire(self._oid, self._expiry())

        self._client.transaction(apply, self._oid)
        return answer['value']

    def __setitem__(self, i, obj):
        if isinstance(i, int) or hasattr(i, '__index__'):
            idx = i.__index__()
            serialized = self._pickler.dumps(obj)
            try:
                pipeline = self._client.pipeline()
                pipeline.lset(self._oid, idx, serialized)
                pipeline.expire(self._oid, self._expiry())
                pipeline.execute()
            except redis.exceptions.ResponseError:
                # raised when index >= len(self)
                raise IndexError('list assignment index out of range')

        elif isinstance(i, slice):
            # Done through the whole list rather than element by element.
            # The old code walked range(start, end) over a bound LRANGE
            # reports inclusively, so it wrote one element too few, dropped
            # `l[:0] = x` and `l[len(l):] = x` entirely, ignored the step,
            # and could not grow or shrink the list at all
            def change(items):
                items[i] = obj
                return items, None

            self._mutate(change)
        else:
            raise TypeError('list indices must be integers '
                            'or slices, not {}'.format(type(i)))

    def __getitem__(self, i):
        if isinstance(i, int) or hasattr(i, '__index__'):
            idx = i.__index__()
            pipeline = self._client.pipeline()
            pipeline.lindex(self._oid, idx)
            pipeline.expire(self._oid, mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))
            serialized, _ = pipeline.execute()
            if serialized is not None:
                return self._pickler.loads(serialized)
            raise IndexError('list index out of range')

        elif isinstance(i, slice):
            start, end, step = deslice(i)
            if step is not None and step != 1:
                # LRANGE cannot step, and returning the contiguous range
                # regardless meant l[::2] gave back the whole list and
                # l[::-1] gave it back the right way round
                return self.tolist()[i]
            if start is None:
                return []
            pipeline = self._client.pipeline()
            pipeline.lrange(self._oid, start, end)
            pipeline.expire(self._oid, self._expiry())
            serialized, _ = pipeline.execute()
            unserialized = [self._pickler.loads(obj) for obj in serialized]
            return unserialized
            # return type(self)(unserialized)
        else:
            raise TypeError('list indices must be integers '
                            'or slices, not {}'.format(type(i)))

    def extend(self, iterable):
        if isinstance(iterable, type(self)):
            self._extend_same_type(iterable, 1)
            return
        # Drawn off before it is measured. `iterable != []` was true for
        # every empty thing that is not a list -- (), '', an empty set, a
        # generator, the reversed() in reverse() -- and RPUSH with no values
        # is an error from the server, not a no-op
        values = [self._pickler.dumps(obj) for obj in iterable]
        if not values:
            return
        pipeline = self._client.pipeline()
        pipeline.rpush(self._oid, *values)
        pipeline.expire(self._oid, self._expiry())
        pipeline.execute()

    def _extend_same_type(self, listproxy, repeat=1):
        self._lua_extend_list(keys=[self._oid, listproxy._oid],
                              args=[repeat],
                              client=self._client)
        # The script only RPUSHes. Without this a list built from another
        # proxy -- ListProxy(other), a deepcopy, an in-place multiply --
        # got a key that never expired, while one built from a plain list
        # got one that did
        self._client.expire(self._oid, self._expiry())

    def append(self, obj):
        serialized = self._pickler.dumps(obj)
        pipeline = self._client.pipeline()
        pipeline.rpush(self._oid, serialized)
        pipeline.expire(self._oid, mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))
        pipeline.execute()

    def pop(self, index=None):
        if index is None:
            pipeline = self._client.pipeline()
            pipeline.rpop(self._oid)
            pipeline.expire(self._oid, self._expiry())
            serialized, _ = pipeline.execute()
            if serialized is None:
                # RPOP on a missing key answers nil, and falling off the end
                # here handed the caller None as if it were an element
                raise IndexError('pop from empty list')
            return self._pickler.loads(serialized)

        # Read, remove and return in one step. Doing it as LINDEX, LSET of a
        # sentinel and LREM let another writer shift the list in between, so
        # the element that came back was not the one that was removed
        def change(items):
            item = items.pop(index)
            return items, item

        return self._mutate(change)

    def _referent(self):
        return self.tolist()

    def _new_empty(self):
        return type(self)()

    def copy_proxy(self):
        """
        A second shared list holding the same elements, copied server side.

        deepcopy() used to do this, but the standard library's proxies
        deepcopy to a plain value, and code written against it expects a
        list back rather than another handle on shared state
        """
        selfcopy = self._new_empty()
        selfcopy._extend_same_type(self)
        return selfcopy

    def __add__(self, x):
        # FIXME: list only allows concatenation to other list objects
        #        (altough it can now be extended by iterables)
        # newlist = deepcopy(self)
        # return newlist.__iadd__(x)
        return self[:] + x

    def __iadd__(self, x):
        # FIXME: list only allows concatenation to other list objects
        #        (altough it can now be extended by iterables)
        self.extend(x)
        return self

    def __mul__(self, n):
        if not isinstance(n, int):
            raise TypeError("can't multiply sequence"
                            " by non-int of type {}".format(type(n)))
        if n < 1:
            # return type(self)()
            return []
        else:
            # newlist = type(self)()
            # newlist._extend_same_type(self, repeat=n)
            # return newlist
            return self[:] * n

    def __rmul__(self, n):
        return self.__mul__(n)

    def __imul__(self, n):
        if not isinstance(n, int):
            raise TypeError("can't multiply sequence"
                            " by non-int of type {}".format(type(n)))
        if n > 1:
            self._extend_same_type(self, repeat=n - 1)
        elif n <= 0:
            # list *= 0 empties the list; the guard used to leave it alone
            self._client.delete(self._oid)
        return self

    def __len__(self):
        pipeline = self._client.pipeline()
        pipeline.llen(self._oid)
        pipeline.expire(self._oid, self._expiry())
        length, _ = pipeline.execute()
        return length

    def __contains__(self, obj):
        # One round trip. Without it `in` falls back to the old __getitem__
        # sequence protocol, which is a LINDEX per element
        return obj in self.tolist()

    def remove(self, obj):
        """
        Removes the first element equal to ``obj``, like list.remove.

        LREM matches the stored pickle byte for byte, which is not what ==
        means: remove(1) left a 1.0 in place, and so did removing a dict
        whose keys were built in a different order. A value that is not
        there raised nothing at all
        """
        def change(items):
            items.remove(obj)
            return items, None

        self._mutate(change)

    def __delitem__(self, i):
        def change(items):
            del items[i]
            return items, None

        self._mutate(change)

    def tolist(self):
        pipeline = self._client.pipeline()
        pipeline.lrange(self._oid, 0, -1)
        pipeline.expire(self._oid, self._expiry())
        serialized, _ = pipeline.execute()
        return [self._pickler.loads(obj) for obj in serialized]

    # The following methods can't be (properly) implemented on Redis
    # To still provide the functionality, the list is fetched
    # entirely, operated in-memory and then put back to Redis

    def reverse(self):
        self._mutate(lambda items: (items[::-1], None))

    def sort(self, key=None, reverse=False):
        self._mutate(
            lambda items: (sorted(items, key=key, reverse=reverse), None)
        )

    def index(self, obj, start=0, end=None):
        """
        The standard library looks to the end of the list by default. This
        took end=-1, a real stop that leaves the last element out, so
        looking for the last element raised ValueError
        """
        items = self.tolist()
        if end is None:
            return items.index(obj, start)
        return items.index(obj, start, end)

    def count(self, obj):
        return self.tolist().count(obj)

    def insert(self, index, obj):
        def change(items):
            items.insert(index, obj)
            return items, None

        self._mutate(change)


class DictProxy(BaseProxy):

    def __init__(self, *args, **kwargs):
        super().__init__('dict')
        self.update(*args, **kwargs)

    def _referent(self):
        return self.todict()

    def __setitem__(self, k, v):
        serialized = self._pickler.dumps(v)
        pipeline = self._client.pipeline()
        pipeline.hset(self._oid, self._field(k), serialized)
        pipeline.expire(self._oid, self._expiry())
        pipeline.execute()

    def __getitem__(self, k):
        pipeline = self._client.pipeline()
        pipeline.hget(self._oid, self._field(k))
        pipeline.expire(self._oid, self._expiry())
        serialized, _ = pipeline.execute()
        if serialized is None:
            raise KeyError(k)

        return self._pickler.loads(serialized)

    def __delitem__(self, k):
        pipeline = self._client.pipeline()
        pipeline.hdel(self._oid, self._field(k))
        pipeline.expire(self._oid, self._expiry())
        res, _ = pipeline.execute()

        if res == 0:
            raise KeyError(k)

    def __contains__(self, k):
        pipeline = self._client.pipeline()
        pipeline.hexists(self._oid, self._field(k))
        pipeline.expire(self._oid, self._expiry())
        exists, _ = pipeline.execute()
        return bool(exists)

    def __len__(self):
        pipeline = self._client.pipeline()
        pipeline.hlen(self._oid)
        pipeline.expire(self._oid, self._expiry())
        length, _ = pipeline.execute()
        return length

    def __iter__(self):
        return iter(self.keys())

    def get(self, k, default=None):
        try:
            v = self.__getitem__(k)
        except KeyError:
            return default
        else:
            return v

    def pop(self, k, *args):
        """
        dict.pop(k) raises KeyError when the key is not there; only
        pop(k, default) answers with the default. The default used to be
        baked into the signature, so a missing key quietly gave back None
        """
        if len(args) > 1:
            raise TypeError(
                'pop expected at most 2 arguments, got {}'.format(1 + len(args))
            )
        field = self._field(k)
        pipeline = self._client.pipeline()
        pipeline.hget(self._oid, field)
        pipeline.hdel(self._oid, field)
        pipeline.expire(self._oid, self._expiry())
        serialized, _removed, _ = pipeline.execute()
        if serialized is None:
            if args:
                return args[0]
            raise KeyError(k)
        return self._pickler.loads(serialized)

    def popitem(self):
        """
        Taken in one step. Reading a key, then fetching it, then deleting it
        let another caller take the same pair, or delete it in between and
        turn this into a KeyError naming that key rather than a
        'dictionary is empty'
        """
        answer = {}

        def apply(pipe):
            fields = pipe.hkeys(self._oid)
            if not fields:
                raise KeyError('popitem(): dictionary is empty')
            field = fields[0]
            serialized = pipe.hget(self._oid, field)
            if serialized is None:
                raise redis.WatchError()
            answer['value'] = (
                self._pickler.loads(field), self._pickler.loads(serialized)
            )
            pipe.multi()
            pipe.hdel(self._oid, field)
            pipe.expire(self._oid, self._expiry())

        self._client.transaction(apply, self._oid)
        return answer['value']

    def setdefault(self, k, default=None):
        serialized = self._pickler.dumps(default)
        pipeline = self._client.pipeline()
        pipeline.hsetnx(self._oid, self._field(k), serialized)
        # Every other writer refreshes the expiry. A dict only ever written
        # through setdefault used to get a key that outlived the job
        pipeline.expire(self._oid, self._expiry())
        res, _ = pipeline.execute()
        if res == 1:
            return default
        return self.__getitem__(k)

    def update(self, *args, **kwargs):
        items = {}
        if args != ():
            if len(args) > 1:
                raise TypeError('update expected at most'
                                ' 1 arguments, got {}'.format(len(args)))
            try:
                for k in args[0].keys():
                    items[self._field(k)] = self._pickler.dumps(args[0][k])
            except AttributeError:
                try:
                    items = {}  # just in case
                    for k, v in args[0]:
                        items[self._field(k)] = self._pickler.dumps(v)
                except Exception:
                    raise TypeError(type(args[0]))

        for k in kwargs.keys():
            items[self._field(k)] = self._pickler.dumps(kwargs[k])

        if items:
            # One pipelined HSET rather than the deprecated HMSET and a
            # separate round trip for the expiry
            pipeline = self._client.pipeline()
            pipeline.hset(self._oid, mapping=items)
            pipeline.expire(self._oid, self._expiry())
            pipeline.execute()

    def keys(self):
        pipeline = self._client.pipeline()
        pipeline.hkeys(self._oid)
        pipeline.expire(self._oid, self._expiry())
        fields, _ = pipeline.execute()
        return [self._pickler.loads(k) for k in fields]

    def values(self):
        pipeline = self._client.pipeline()
        pipeline.hvals(self._oid)
        pipeline.expire(self._oid, self._expiry())
        values, _ = pipeline.execute()
        return [self._pickler.loads(v) for v in values]

    def items(self):
        return list(self.todict().items())

    def clear(self):
        self._client.delete(self._oid)

    def copy(self):
        """
        A plain dict, like the standard library. Handing back another proxy
        made what looks like a local copy allocate a second Redis key
        """
        return self.todict()

    def todict(self):
        pipeline = self._client.pipeline()
        pipeline.hgetall(self._oid)
        pipeline.expire(self._oid, self._expiry())
        raw_dict, _ = pipeline.execute()
        return {
            self._pickler.loads(k): self._pickler.loads(v)
            for k, v in raw_dict.items()
        }


class NamespaceProxy(BaseProxy):
    def __init__(self, **kwargs):
        super().__init__('Namespace')
        DictProxy.update(self, **kwargs)

    def __getattr__(self, k):
        if k[0] == '_':
            return object.__getattribute__(self, k)
        try:
            return DictProxy.__getitem__(self, k)
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        if k[0] == '_':
            return object.__setattr__(self, k, v)
        DictProxy.__setitem__(self, k, v)

    def __delattr__(self, k):
        if k[0] == '_':
            return object.__delattr__(self, k)
        try:
            return DictProxy.__delitem__(self, k)
        except KeyError:
            raise AttributeError(k)

    def _referent(self):
        return types.SimpleNamespace(**DictProxy.todict(self))

    def _todict(self):
        return DictProxy.todict(self)


class ValueProxy(BaseProxy):
    def __init__(self, typecode='Any', value=None, lock=True):
        super().__init__('Value({})'.format(typecode))
        self._typecode = typecode
        # Written whatever it is. Skipping a None left the key missing, and
        # get() then handed None to loads() and raised TypeError instead of
        # answering None
        self.set(value)

    def _referent(self):
        return self.get()

    def get(self):
        pipeline = self._client.pipeline()
        pipeline.get(self._oid)
        # Read without refreshing, a value that is polled and never written
        # disappears once REDIS_EXPIRY_TIME is up, mid-job
        pipeline.expire(self._oid, mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))
        serialized, _ = pipeline.execute()
        if serialized is None:
            return None
        return self._pickler.loads(serialized)

    def set(self, value):
        serialized = self._pickler.dumps(value)
        self._client.set(self._oid, serialized, ex=mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME))

    value = property(get, set)


class ArrayProxy(ListProxy):
    def __init__(self, typecode='Any', sequence=None, lock=True):
        """
        Takes a size as well as a sequence, like multiprocessing.Array.

        Array('i', 10) allocates ten zeroed slots there; here it reached
        extend(10) and raised TypeError: 'int' object is not iterable
        """
        self._typecode = typecode
        if isinstance(sequence, int):
            sequence = [0] * sequence
        super().__init__(sequence)

    def _new_empty(self):
        # ListProxy.__deepcopy__ builds an empty one of the same type, and
        # this one needs its typecode
        return type(self)(self._typecode)


#
# Definition of SyncManager
#

class SyncManager(BaseManager):
    """
    Subclass of `BaseManager` which supports a number of shared object types.

    The types registered are those intended for the synchronization
    of threads, plus `dict`, `list` and `Namespace`.

    The `multiprocessing.Manager()` function creates started instances of
    this class.
    """


def Manager():
    """
    A started SyncManager, which is what multiprocessing.Manager() returns.

    The class itself used to be exported under this name, so every manager
    came back unstarted: shutdown() was a no-op, _number_of_objects() always
    said zero, and nothing handed out was ever collected
    """
    manager = SyncManager()
    manager.start()
    return manager


SyncManager.register('list', proxytype=ListProxy)
SyncManager.register('dict', proxytype=DictProxy)
SyncManager.register('Namespace', proxytype=NamespaceProxy)
SyncManager.register('Lock', proxytype=synchronize.Lock)
SyncManager.register('RLock', proxytype=synchronize.RLock)
SyncManager.register('Semaphore', proxytype=synchronize.Semaphore)
SyncManager.register('BoundedSemaphore', proxytype=synchronize.BoundedSemaphore)
SyncManager.register('Condition', proxytype=synchronize.Condition)
SyncManager.register('Event', proxytype=synchronize.Event)
SyncManager.register('Barrier', proxytype=synchronize.Barrier)
SyncManager.register('Queue', proxytype=queues.Queue)
SyncManager.register('SimpleQueue', proxytype=queues.SimpleQueue)
SyncManager.register('JoinableQueue', proxytype=queues.JoinableQueue)
SyncManager.register('Value', proxytype=ValueProxy)
SyncManager.register('Array', proxytype=ArrayProxy)
SyncManager.register('Pool', proxytype=pool.Pool, can_manage=False)
