# from multiprocessing import Pool
from lithops.multiprocessing import Pool
from lithops.utils import setup_lithops_logger

import time
import logging
import os

# setup_lithops_logger(logging.CRITICAL)


def hello(name):
    return 'Hello {}!'.format(name)


def square(x):
    return x * x


def divide(x, y):
    return x / y


def sleep_seconds(s):
    time.sleep(s)


if __name__ == '__main__':
    with Pool() as pool:

        # Synchronously execute function hello remotely
        res = pool.apply(hello, ('World', ))
        print(res)  # print "Hello World!"

        # Synchronously apply function square to every element of list
        res = pool.map(square, [1, 2, 3, 4, 5])
        print(res)  # print "[1, 4, 9, 16, 25]"

        # Asynchronously execute function square remotely
        res = pool.apply_async(square, (20,))
        print(res.ready())  # prints "False"
        res.wait()
        print(res.ready())  # prints "True"
        print(res.get(timeout=5))  # prints "400"

        # Launching multiple evaluations asynchronously
        multiple_results = [pool.apply_async(os.getpid, ()) for i in range(4)]
        print([res.get() for res in multiple_results])

        # Map with multiple args per function
        res = pool.starmap(divide, [(1, 2), (2, 3), (3, 4)])
        print(res)  # prints "[0.5, 0.6666666666666666, 0.75]"

        # Apply async with that raises an exception
        res = pool.apply_async(divide, (1, 0))
        res.wait()
        print(res.successful())  # prints "False"
        try:
            res.get()  # Will raise ZeroDivisionError
        except Exception as e:
            print(e)

        # Apply async that times out
        res = pool.apply_async(sleep_seconds, (10,))
        try:
            print('Waiting for the result...')
            print(res.get(timeout=3))
        except TimeoutError:
            print("Timed out!")

        print("For the moment, the pool remains available for more work")

    # Exiting the 'with'-block has stopped the pool
    print("Now the pool is closed and no longer available")
