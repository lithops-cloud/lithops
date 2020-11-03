#
# A higher level module for using sockets (or Windows named pipes)
#
# multiprocessing/connection.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV

__all__ = [ 'Client', 'Listener', 'Pipe', 'wait' ]

import io
import os
import sys
import socket
import struct
import time
import tempfile
import itertools
from random import randint

import _multiprocessing

from . import util
from . import get_context
from . import AuthenticationError, BufferTooShort
from .context import reduction
_ForkingPickler = reduction.ForkingPickler

try:
    import _winapi
    from _winapi import WAIT_OBJECT_0, WAIT_ABANDONED_0, WAIT_TIMEOUT, INFINITE
except ImportError:
    if sys.platform == 'win32':
        raise
    _winapi = None

#
# Constants
#

#           Handle prefixes
# Separated keys/channels so that a given
# connection cannot read its own messages
REDIS_LIST_CONN = 'listconn'    # uses lists
REDIS_LIST_CONN_A = REDIS_LIST_CONN + '-a-'
REDIS_LIST_CONN_B = REDIS_LIST_CONN + '-b-'
REDIS_PUBSUB_CONN = 'pubsubconn'    # uses channels (pub/sub)
REDIS_PUBSUB_CONN_A = REDIS_PUBSUB_CONN + '-a-'
REDIS_PUBSUB_CONN_B = REDIS_PUBSUB_CONN + '-b-'


BUFSIZE = 8192
# A very generous timeout when it comes to local connections...
CONNECTION_TIMEOUT = 20.

_mmap_counter = itertools.count()

default_family = 'AF_INET'
families = ['AF_INET']

if hasattr(socket, 'AF_UNIX'):
    default_family = 'AF_UNIX'
    families += ['AF_UNIX']

if sys.platform == 'win32':
    default_family = 'AF_PIPE'
    families += ['AF_PIPE']


def _init_timeout(timeout=CONNECTION_TIMEOUT):
    return time.monotonic() + timeout

def _check_timeout(t):
    return time.monotonic() > t


#
#
#

def get_handle_pair(conn_type=REDIS_LIST_CONN, from_id=None):
    if from_id is None:
        id = util.get_uuid()
    else:
        id = from_id
    if conn_type == REDIS_LIST_CONN:
        return (REDIS_LIST_CONN_A + id,
                REDIS_LIST_CONN_B + id)
    elif conn_type == REDIS_PUBSUB_CONN:
        return (REDIS_PUBSUB_CONN_A + id,
                REDIS_PUBSUB_CONN_B + id)

def get_subhandle(handle):
    if handle.startswith(REDIS_LIST_CONN_A):
        return REDIS_LIST_CONN_B + handle[len(REDIS_LIST_CONN_A):]

    elif handle.startswith(REDIS_LIST_CONN_B):
        return REDIS_LIST_CONN_A + handle[len(REDIS_LIST_CONN_B):]

    elif handle.startswith(REDIS_PUBSUB_CONN_A):
        return REDIS_PUBSUB_CONN_B + handle[len(REDIS_PUBSUB_CONN_A):]

    elif handle.startswith(REDIS_PUBSUB_CONN_B):
        return REDIS_PUBSUB_CONN_A + handle[len(REDIS_PUBSUB_CONN_B):]

    raise ValueError("bad handle prefix '{}' - see "
        "cloudbutton.multiprocessing.connection handle prefixes".format(handle))

def _validate_address(address):
    if not isinstance(address, str):
        raise ValueError("address must be a str, got {}"\
            .format(type(address)))
    if not address.startswith((REDIS_LIST_CONN, REDIS_PUBSUB_CONN)):
        raise ValueError("address '{}' is not of any known type ({}, {})"\
            .format(address, REDIS_LIST_CONN, REDIS_PUBSUB_CONN))

def arbitrary_address(family):
    '''
    Return an arbitrary free address for the given family
    '''
    if family == 'AF_INET':
        return ('localhost', 0)
    elif family == 'AF_UNIX':
        return tempfile.mktemp(prefix='listener-', dir=util.get_temp_dir())
    elif family == 'AF_PIPE':
        return tempfile.mktemp(prefix=r'\\.\pipe\pyc-%d-%d-' %
                               (os.getpid(), next(_mmap_counter)), dir="")
    elif family == 'AF_REDIS':
        return 'listener-' + util.get_uuid()
    else:
        raise ValueError('unrecognized family')

def _validate_family(family):
    '''
    Checks if the family is valid for the current environment.
    '''
    if sys.platform != 'win32' and family == 'AF_PIPE':
        raise ValueError('Family %s is not recognized.' % family)

    if sys.platform == 'win32' and family == 'AF_UNIX':
        # double check
        if not hasattr(socket, family):
            raise ValueError('Family %s is not recognized.' % family)

def address_type(address):
    '''
    Return the types of the address

    This can be 'AF_INET', 'AF_UNIX', or 'AF_PIPE'
    '''
    if type(address) == tuple:
        return 'AF_INET'
    elif type(address) is str and address.startswith('\\\\'):
        return 'AF_PIPE'
    elif type(address) is str:
        return 'AF_UNIX'
    else:
        raise ValueError('address type of %r unrecognized' % address)

#
# Connection classes
#

class _ConnectionBase:
    _handle = None

    def __init__(self, handle, readable=True, writable=True):
        if not readable and not writable:
            raise ValueError(
                "at least one of `readable` and `writable` must be True")
        self._client = util.get_redis_client()
        self._handle = handle
        self._readable = readable
        self._writable = writable

    # XXX should we use util.Finalize instead of a __del__?

    def __del__(self):
        if self._handle is not None:
            self._close()

    def _check_closed(self):
        if self._handle is None:
            raise OSError("handle is closed")

    def _check_readable(self):
        if not self._readable:
            raise OSError("connection is write-only")

    def _check_writable(self):
        if not self._writable:
            raise OSError("connection is read-only")

    def _bad_message_length(self):
        if self._writable:
            self._readable = False
        else:
            self.close()
        raise OSError("bad message length")

    @property
    def closed(self):
        """True if the connection is closed"""
        return self._handle is None

    @property
    def readable(self):
        """True if the connection is readable"""
        return self._readable

    @property
    def writable(self):
        """True if the connection is writable"""
        return self._writable

    def fileno(self):
        """File descriptor or handle of the connection"""
        self._check_closed()
        return self._handle

    def close(self):
        """Close the connection"""
        if self._handle is not None:
            try:
                self._close()
            finally:
                self._handle = None

    def send_bytes(self, buf, offset=0, size=None):
        """Send the bytes data from a bytes-like object"""
        self._check_closed()
        self._check_writable()
        m = memoryview(buf)
        # HACK for byte-indexing of non-bytewise buffers (e.g. array.array)
        if m.itemsize > 1:
            m = memoryview(bytes(m))
        n = len(m)
        if offset < 0:
            raise ValueError("offset is negative")
        if n < offset:
            raise ValueError("buffer length < offset")
        if size is None:
            size = n - offset
        elif size < 0:
            raise ValueError("size is negative")
        elif offset + size > n:
            raise ValueError("buffer length < offset + size")
        self._send_bytes(m[offset:offset + size])

    def send(self, obj):
        """Send a (picklable) object"""
        self._check_closed()
        self._check_writable()
        self._send_bytes(_ForkingPickler.dumps(obj))

    def recv_bytes(self, maxlength=None):
        """
        Receive bytes data as a bytes object.
        """
        self._check_closed()
        self._check_readable()
        if maxlength is not None and maxlength < 0:
            raise ValueError("negative maxlength")
        buf = self._recv_bytes(maxlength)
        if buf is None:
            self._bad_message_length()
        return buf.getvalue()

    def recv_bytes_into(self, buf, offset=0):
        """
        Receive bytes data into a writeable bytes-like object.
        Return the number of bytes read.
        """
        self._check_closed()
        self._check_readable()
        with memoryview(buf) as m:
            # Get bytesize of arbitrary buffer
            itemsize = m.itemsize
            bytesize = itemsize * len(m)
            if offset < 0:
                raise ValueError("negative offset")
            elif offset > bytesize:
                raise ValueError("offset too large")
            result = self._recv_bytes()
            size = result.tell()
            if bytesize < offset + size:
                raise BufferTooShort(result.getvalue())
            # Message can fit in dest
            result.seek(0)
            result.readinto(m[offset // itemsize :
                              (offset + size) // itemsize])
            return size

    def recv(self):
        """Receive a (picklable) object"""
        self._check_closed()
        self._check_readable()
        buf = self._recv_bytes()
        return _ForkingPickler.loads(buf.getbuffer())

    def poll(self, timeout=0.0):
        """Whether there is any input available to be read"""
        self._check_closed()
        self._check_readable()
        return self._poll(timeout)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()


class Connection(_ConnectionBase):
    """
    Connection class for Redis.
    """
    _write = None
    _read = None

    def __init__(self, handle, readable=True, writable=True):
        super().__init__(handle, readable, writable)
        self._subhandle = get_subhandle(handle)
        self._connect()

    def _connect(self):
        if self._handle.startswith(REDIS_LIST_CONN):
            self._read = self._listread
            self._write = self._listwrite

        elif self._handle.startswith(REDIS_PUBSUB_CONN):
            self._read = self._channelread
            self._write = self._channelwrite
            self._pubsub = self._client.pubsub()
            self._pubsub.subscribe(self._subhandle)
            self._gen = self._pubsub.listen()
            # ignore first message (subscribe message)
            next(self._gen)

    def __getstate__(self):
        return (self._client, self._handle, self._subhandle,
            self._readable, self._writable)    

    def __setstate__(self, state):
        (self._client, self._handle, self._subhandle,
            self._readable, self._writable) = state
        self._connect()

    def __len__(self):
        return self._client.llen(self._handle)

    def _close(self, _close=None):
        # older versions of StrictRedis can't be closed
        if hasattr(self._client, 'close'):
            self._client.close()

    def _listwrite(self, handle, buf):
        return self._client.rpush(handle, buf)

    def _listread(self, handle):
        _, v = self._client.blpop([handle])
        return v

    def _channelwrite(self, handle, buf):
        return self._client.publish(handle, buf)

    def _channelread(self, handle):
        msg = next(self._gen)
        return msg['data']

    def _send(self, buf, write=None):
        raise NotImplementedError('Connection._send() on Redis')

    def _recv(self, size, read=None):
        raise NotImplementedError('Connection._recv() on Redis')

    def _send_bytes(self, buf):
        self._write(self._handle, buf.tobytes())

    def _recv_bytes(self, maxsize=None):
        buf = io.BytesIO()
        chunk = self._read(self._subhandle)
        buf.write(chunk)
        return buf

    def _poll(self, timeout):
        if hasattr(self, '_pubsub'):
            r = wait([(self._pubsub, self._subhandle)], timeout)
        else:
            r = wait([(self._client, self._subhandle)], timeout)
        return bool(r)


PipeConnection = Connection

#
# Public functions
#

class Listener(object):
    '''
    Returns a listener object.

    This is a wrapper for a bound socket which is 'listening' for
    connections, or for a Windows named pipe.
    '''
    def __init__(self, address=None, family=None, backlog=1, authkey=None):
        family = 'AF_REDIS'
        address = address or arbitrary_address(family)

        self._listener = SocketListener(address, family, backlog)

        if authkey is not None and not isinstance(authkey, bytes):
            raise TypeError('authkey should be a byte string')

        self._authkey = authkey

    def accept(self):
        '''
        Accept a connection on the bound socket or named pipe of `self`.

        Returns a `Connection` object.
        '''
        if self._listener is None:
            raise OSError('listener is closed')
        c = self._listener.accept()
        if self._authkey:
            deliver_challenge(c, self._authkey)
            answer_challenge(c, self._authkey)
        return c

    def close(self):
        '''
        Close the bound socket or named pipe of `self`.
        '''
        listener = self._listener
        if listener is not None:
            self._listener = None
            listener.close()

    address = property(lambda self: self._listener._address)
    last_accepted = property(lambda self: self._listener._last_accepted)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()


def Client(address, family=None, authkey=None):
    '''
    Returns a connection to the address of a `Listener`
    '''
    c = SocketClient(address)

    if authkey is not None and not isinstance(authkey, bytes):
        raise TypeError('authkey should be a byte string')

    if authkey is not None:
        answer_challenge(c, authkey)
        deliver_challenge(c, authkey)

    return c


def Pipe(duplex=True):
    '''
    Returns pair of connection objects at either end of a pipe
    '''
    h1, h2 = get_handle_pair(conn_type=REDIS_LIST_CONN)     

    if duplex:
        c1 = Connection(h1)
        c2 = Connection(h2)
    else:
        c1 = Connection(h1, writable=False)
        c2 = Connection(h2, readable=False)

    return c1, c2


#
# Definitions for connections based on sockets
#

class SocketListener(object):
    '''
    Representation of a socket which is bound to an address and listening
    '''
    def __init__(self, address, family=None, backlog=1):
        self._address = address
        self._family = 'AF_REDIS'
        self._client = util.get_redis_client()
        self._connect()

        self._last_accepted = None
        self._unlink = None

    def _connect(self):
        self._pubsub = self._client.pubsub()
        self._pubsub.subscribe(self._address)
        self._gen = self._pubsub.listen()
        # ignore first message (subscribe message)
        next(self._gen)

    def __getstate__(self):
        return (self._address, self._family, self._client,
            self._last_accepted, self._unlink)

    def __setstate__(self, state):
        (self._address, self._family, self._client,
            self._last_accepted, self._unlink) = state
        self._connect()

    def accept(self):
        msg = next(self._gen)
        client_subhandle = msg['data'].decode('utf-8')
        c = Connection(client_subhandle)
        c.send('OK')
        self._last_accepted = client_subhandle
        return c

    def close(self):
        try:
            self._pubsub.close()
            self._pubsub = None
            self._gen = None
            if hasattr(self._client, 'close'):
                self._client.close()
                self._client = None
        finally:
            unlink = self._unlink
            if unlink is not None:
                self._unlink = None
                unlink()


def SocketClient(address):
    '''
    Return a connection object connected to the socket given by `address`
    '''
    h1, _ = get_handle_pair(conn_type=REDIS_PUBSUB_CONN)
    c = Connection(h1)
    c._channelwrite(address, c._subhandle.encode('utf-8'))

    if c._poll(CONNECTION_TIMEOUT):
        c.recv()
        return c
    else:
        raise ConnectionRefusedError(address)


PipeListener = SocketListener
PipeClient = SocketClient


#
# Authentication stuff
#

MESSAGE_LENGTH = 20

CHALLENGE = b'#CHALLENGE#'
WELCOME = b'#WELCOME#'
FAILURE = b'#FAILURE#'

def deliver_challenge(connection, authkey):
    import hmac
    assert isinstance(authkey, bytes)
    message = os.urandom(MESSAGE_LENGTH)
    connection.send_bytes(CHALLENGE + message)
    digest = hmac.new(authkey, message, 'md5').digest()
    response = connection.recv_bytes(256)        # reject large message
    if response == digest:
        connection.send_bytes(WELCOME)
    else:
        connection.send_bytes(FAILURE)
        raise AuthenticationError('digest received was wrong')

def answer_challenge(connection, authkey):
    import hmac
    assert isinstance(authkey, bytes)
    message = connection.recv_bytes(256)         # reject large message
    assert message[:len(CHALLENGE)] == CHALLENGE, 'message = %r' % message
    message = message[len(CHALLENGE):]
    digest = hmac.new(authkey, message, 'md5').digest()
    connection.send_bytes(digest)
    response = connection.recv_bytes(256)        # reject large message
    if response != WELCOME:
        raise AuthenticationError('digest sent was rejected')

#
# Support for using xmlrpclib for serialization
#

class ConnectionWrapper(object):
    def __init__(self, conn, dumps, loads):
        self._conn = conn
        self._dumps = dumps
        self._loads = loads
        for attr in ('fileno', 'close', 'poll', 'recv_bytes', 'send_bytes'):
            obj = getattr(conn, attr)
            setattr(self, attr, obj)
    def send(self, obj):
        s = self._dumps(obj)
        self._conn.send_bytes(s)
    def recv(self):
        s = self._conn.recv_bytes()
        return self._loads(s)

def _xml_dumps(obj):
    return xmlrpclib.dumps((obj,), None, None, None, 1).encode('utf-8')

def _xml_loads(s):
    (obj,), method = xmlrpclib.loads(s.decode('utf-8'))
    return obj

class XmlListener(Listener):
    def accept(self):
        global xmlrpclib
        import xmlrpc.client as xmlrpclib
        obj = Listener.accept(self)
        return ConnectionWrapper(obj, _xml_dumps, _xml_loads)

def XmlClient(*args, **kwds):
    global xmlrpclib
    import xmlrpc.client as xmlrpclib
    return ConnectionWrapper(Client(*args, **kwds), _xml_dumps, _xml_loads)

#
# Wait
#

import selectors

# poll/select have the advantage of not requiring any extra file
# descriptor, contrarily to epoll/kqueue (also, they require a single
# syscall).
if hasattr(selectors, 'PollSelector'):
    _WaitSelector = selectors.PollSelector
else:
    _WaitSelector = selectors.SelectSelector


def wait(object_list, timeout=None):
    '''
    Wait till an object in object_list is ready/readable.

    Returns list of those objects in object_list which are ready/readable.
    '''
    if timeout is not None:
        deadline = time.monotonic() + timeout

    while True:
        ready = []
        for client, handle in object_list:
            if handle.startswith(REDIS_LIST_CONN):
                l = client.llen(handle)
                if l > 0:
                    ready.append((client, handle))
            elif handle.startswith(REDIS_PUBSUB_CONN)\
                 and client.connection.can_read():
                ready.append((client, handle))
                
        if any(ready):
            return ready

        if timeout is not None:
            timeout = deadline - time.monotonic()
            if timeout < 0:
                return ready
        time.sleep(0.1)

#
# Make connection and socket objects sharable if possible
#

def reduce_connection(conn):
    df = reduction.DupFd(conn.fileno())
    return rebuild_connection, (df, conn.readable, conn.writable)
def rebuild_connection(df, readable, writable):
    fd = df.detach()
    return Connection(fd, readable, writable)
reduction.register(Connection, reduce_connection)
