#
# Module which supports allocation of ctypes objects from shared memory
#
# multiprocessing/sharedctypes.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

import ctypes
import weakref

from . import util
from .context import get_context, reduction

_ForkingPickler = reduction.DefaultPickler

__all__ = ['RawValue', 'RawArray', 'Value', 'Array']

#
#
#

typecode_to_type = {
    'c': ctypes.c_char, 'u': ctypes.c_wchar,
    'b': ctypes.c_byte, 'B': ctypes.c_ubyte,
    'h': ctypes.c_short, 'H': ctypes.c_ushort,
    'i': ctypes.c_int, 'I': ctypes.c_uint,
    'l': ctypes.c_long, 'L': ctypes.c_ulong,
    'q': ctypes.c_longlong, 'Q': ctypes.c_ulonglong,
    'f': ctypes.c_float, 'd': ctypes.c_double
}


#
#
#

def int_to_bytes(x: int) -> bytes:
    return x.to_bytes((x.bit_length() + 7) // 8, 'big')


def int_from_bytes(xbytes: bytes) -> int:
    return int.from_bytes(xbytes, 'big')


class SharedCtypesProxy:
    def __init__(self, ctype):
        self._typeid = ctype.__name__
        self._oid = '{}-{}'.format(self._typeid, util.get_uuid())
        self._pickler = _ForkingPickler()
        self._client = util.get_redis_client()
        self._ref = util.RemoteReference(self._oid, client=self._client)


class ValueProxy(SharedCtypesProxy):
    def __init__(self, ctype, len):
        self._len = len
        super().__init__(ctype)

    def __setattr__(self, key, value):
        if key == 'value':
            obj = int_to_bytes(value)
            self._client.set(self._oid, obj)
        else:
            super().__setattr__(key, value)

    def __getattr__(self, item):
        if item == 'value':
            obj = self._client.get(self._oid)
            if not obj:
                value = 0
            else:
                value = int_from_bytes(obj)
            return value
        else:
            super().__getattribute__(item)


class SynchronizedValueProxy(ValueProxy):
    def __init__(self, ctype, len, lock=None, ctx=None):
        super().__init__(ctype, len)
        if lock:
            self._lock = lock
        else:
            ctx = ctx or get_context()
            self._lock = ctx.RLock()
        self.acquire = self._lock.acquire
        self.release = self._lock.release

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, *args):
        return self._lock.__exit__(*args)

    def get_obj(self):
        return self._obj

    def get_lock(self):
        return self._lock


def RawValue(typecode_or_type, initial_value=None):
    """
    Returns a ctypes object allocated from shared memory
    """
    type_ = typecode_to_type.get(typecode_or_type, typecode_or_type)
    obj = ValueProxy(type_, 1)
    if initial_value:
        obj.value = initial_value
    return obj


def RawArray(typecode_or_type, size_or_initializer):
    """
    Returns a ctypes array allocated from shared memory
    """
    raise NotImplementedError()


def Value(typecode_or_type, initial_value=None, lock=True, ctx=None):
    """
    Return a synchronization wrapper for a Value
    """
    type_ = typecode_to_type.get(typecode_or_type, typecode_or_type)
    obj = SynchronizedValueProxy(type_, 1)
    if initial_value:
        obj.value = initial_value
    return obj


def Array(typecode_or_type, size_or_initializer, *, lock=True, ctx=None):
    """
    Return a synchronization wrapper for a RawArray
    """
    raise NotImplementedError()


# def copy(obj):
#     new_obj = _new_value(type(obj))
#     ctypes.pointer(new_obj)[0] = obj
#     return new_obj


# def synchronized(obj, lock=None, ctx=None):
#     assert not isinstance(obj, SynchronizedBase), 'object already synchronized'
#     ctx = ctx or get_context()
#
#     if isinstance(obj, ctypes._SimpleCData):
#         return Synchronized(obj, lock, ctx)
#     elif isinstance(obj, ctypes.Array):
#         if obj._type_ is ctypes.c_char:
#             return SynchronizedString(obj, lock, ctx)
#         return SynchronizedArray(obj, lock, ctx)
#     else:
#         cls = type(obj)
#         try:
#             scls = class_cache[cls]
#         except KeyError:
#             names = [field[0] for field in cls._fields_]
#             d = {name: make_property(name) for name in names}
#             classname = 'Synchronized' + cls.__name__
#             scls = class_cache[cls] = type(classname, (SynchronizedBase,), d)
#         return scls(obj, lock, ctx)


#
# Functions for pickling/unpickling
#

# def reduce_ctype(obj):
#     assert_spawning(obj)
#     if isinstance(obj, ctypes.Array):
#         return rebuild_ctype, (obj._type_, obj._wrapper, obj._length_)
#     else:
#         return rebuild_ctype, (type(obj), obj._wrapper, None)
#
#
# def rebuild_ctype(type_, wrapper, length):
#     if length is not None:
#         type_ = type_ * length
#     _ForkingPickler.register(type_, reduce_ctype)
#     buf = wrapper.create_memoryview()
#     obj = type_.from_buffer(buf)
#     obj._wrapper = wrapper
#     return obj


#
# Function to create properties
#

# def make_property(name):
#     try:
#         return prop_cache[name]
#     except KeyError:
#         d = {}
#         exec(template % ((name,) * 7), d)
#         prop_cache[name] = d[name]
#         return d[name]


# template = '''
# def get%s(self):
#     self.acquire()
#     try:
#         return self._obj.%s
#     finally:
#         self.release()
# def set%s(self, value):
#     self.acquire()
#     try:
#         self._obj.%s = value
#     finally:
#         self.release()
# %s = property(get%s, set%s)
# '''
#
# prop_cache = {}
# class_cache = weakref.WeakKeyDictionary()


#
# Synchronized wrappers
#

# class SynchronizedBase(object):
#
#     def __init__(self, obj, lock=None, ctx=None):
#         self._obj = obj
#         self._typeid = typeid
#         # object id
#         self._oid = '{}-{}'.format(typeid, util.get_uuid())
#
#         self._pickler = DefaultPickler() if serializer is None else serializer
#         self._client = util.get_redis_client()
#         self._ref = util.RemoteReference(self._oid, client=self._client)
#
#
#     def __repr__(self):
#         return '<%s wrapper for %s>' % (type(self).__name__, self._obj)
#
#
# class Synchronized(SynchronizedBase):
#     value = make_property('value')
#
#
# class SynchronizedArray(SynchronizedBase):
#
#     def __len__(self):
#         return len(self._obj)
#
#     def __getitem__(self, i):
#         with self:
#             return self._obj[i]
#
#     def __setitem__(self, i, value):
#         with self:
#             self._obj[i] = value
#
#     def __getslice__(self, start, stop):
#         with self:
#             return self._obj[start:stop]
#
#     def __setslice__(self, start, stop, values):
#         with self:
#             self._obj[start:stop] = values
#
#
# class SynchronizedString(SynchronizedArray):
#     value = make_property('value')
#     raw = make_property('raw')
