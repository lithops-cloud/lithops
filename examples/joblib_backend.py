"""
Simple Lithops example using the joblib backend.

Registering Lithops with joblib makes Parallel() run its jobs as cloud
functions, so code already written against joblib needs no changes
beyond the parallel_backend() line.
"""
import joblib
from joblib import Parallel, delayed
from lithops.util.joblib import register_lithops
from lithops.utils import setup_lithops_logger

register_lithops()


def my_function(x):
    print(x)


setup_lithops_logger('INFO')

with joblib.parallel_backend('lithops'):
    Parallel()(delayed(my_function)(i) for i in range(10))
