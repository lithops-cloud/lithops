#
# The exception types of the multiprocessing API
#
# multiprocessing/context.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

# In a module of their own, rather than in context.py where the standard
# library keeps them, because context.py imports pool.py and pool.py needs
# TimeoutError

__all__ = [
    'ProcessError',
    'BufferTooShort',
    'TimeoutError',
    'AuthenticationError',
]


class ProcessError(Exception):
    pass


class BufferTooShort(ProcessError):
    pass


class TimeoutError(ProcessError):
    """
    Raised when a wait ran out of time.

    Not the builtin of the same name, which is an OSError: this is the one
    the standard library raises, so `except multiprocessing.TimeoutError`
    behaves as it does there
    """


class AuthenticationError(ProcessError):
    pass
