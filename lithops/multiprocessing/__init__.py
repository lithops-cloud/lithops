#
# Package analogous to 'threading.py' but using processes
#
# multiprocessing/__init__.py
#
# This package is intended to duplicate the functionality (and much of
# the API) of threading.py but uses processes instead of threads.  A
# subpackage 'multiprocessing.dummy' has the same API but is a simple
# wrapper for 'threading'.
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV

import sys
from . import context

#
# Copy stuff from default context
#

_names = [x for x in dir(context._default_context) if x[0] != "_"]
globals().update((name, getattr(context._default_context, name))
                 for name in _names)
__all__ = _names + []
