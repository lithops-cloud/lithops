#
# Module which deals with pickling of objects.
#
# multiprocessing/reduction.py
#
# Copyright (c) 2006-2008, R Oudkerk
# Licensed to PSF under a Contributor Agreement.
#
# Modifications Copyright (c) 2020 Cloudlab URV
#

import copyreg
import io
import pickle


#
# Pickler subclass
#

class ForkingPickler(pickle.Pickler):
    """
    Pickler subclass used by multiprocessing
    """
    _extra_reducers = {}
    _copyreg_dispatch_table = copyreg.dispatch_table

    def __init__(self, *args):
        super().__init__(*args)
        self.dispatch_table = self._copyreg_dispatch_table.copy()
        self.dispatch_table.update(self._extra_reducers)

    @classmethod
    def register(cls, type, reduce):
        """
        Register a reduce function for a type
        """
        cls._extra_reducers[type] = reduce

    @classmethod
    def dumps(cls, obj, protocol=None):
        buf = io.BytesIO()
        cls(buf, protocol).dump(obj)
        return buf.getbuffer()

    loads = pickle.loads


register = ForkingPickler.register


class DefaultPickler:
    load = pickle.load
    loads = pickle.loads
    dump = pickle.dump
    dumps = pickle.dumps
