import sys

if sys.version_info < (3, 8):
    from .cloudpickle import CloudPickler
    __version__ = '1.2.2'

else:
    from .cloudpickle_160_fast import CloudPickler
    __version__ = '1.6.0'
