from lithops.multiprocessing import Pool, TimeoutError
from lithops.utils import setup_logger
import time
import logging
import os

setup_logger(logging.CRITICAL)


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

        res = pool.apply(hello, 'World')  # Synchronously execute function square remotely
        print(res)  # print "Hello World!"

        res = pool.map(square, [1, 2, 3, 4, 5])  # Synchronously apply function square to every element of list
        print(res)  # print "[0, 1, 4,..., 81]"

        res = pool.apply_async(square, (20,))  # Asynchronously execute function square remotely
        print(res.ready())  # prints "False"
        res.wait()
        print(res.ready())  # prints "True"
        print(res.get(timeout=5))  # prints "400"

        multiple_results = [pool.apply_async(os.getpid, ()) for i in
                            range(4)]  # Launching multiple evaluations asynchronously
        print([res.get() for res in multiple_results])

        res = pool.starmap(divide, [(1, 2), (2, 3), (3, 4)])
        print(res)  # prints "[0.5, 0.6666666666666666, 0.75]"

        res = pool.apply_async(divide, (1, 0))
        res.wait()
        print(res.successful())  # prints "False"
        try:
            res.get()  # Will raise ZeroDivisionError
        except Exception as e:
            print(e)

        res = pool.apply_async(sleep_seconds, (10,))  # make a single worker sleep for 10 secs
        try:
            print(res.get(timeout=3))
        except TimeoutError:
            print("Timed out!")

        print("For the moment, the pool remains available for more work")

    # exiting the 'with'-block has stopped the pool
    print("Now the pool is closed and no longer available")
