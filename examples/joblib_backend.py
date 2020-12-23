import joblib
from joblib import Parallel, delayed
from lithops.util.joblib import register_lithops
from lithops.utils import setup_logger

register_lithops()


def my_function(x):
    print(x)


setup_logger('INFO')

with joblib.parallel_backend('lithops'):
    Parallel()(delayed(my_function)(i) for i in range(10))
