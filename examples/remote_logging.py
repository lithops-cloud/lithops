import sys

import lithops
from lithops import Storage
from lithops.multiprocessing import util
import time

iterdata = [1, 2, 3, 4, 5]


def my_map_function(x, id):
    map_log = util.RemoteLogIOBuffer(stream_id)
    map_log.start()
    print(f'Hello from map function {id}', flush=True)

    t1 = time.perf_counter_ns()
    time.sleep(x)
    t2 = time.perf_counter_ns()

    print(f'Execution time for map function {id}: {t2 - t1}: ns', flush=True)

    map_log.stop()
    return x + 7


def my_reduce_function(results, id):
    red_log = util.RemoteLogIOBuffer(stream_id)
    red_log.start()
    print(f'Hello from reduce function {id}', flush=True)

    total = 0
    t1 = time.perf_counter_ns()
    for map_result in results:
        total = total + map_result
    t2 = time.perf_counter_ns()


    print(f'Execution time for reduce function {id}: {t2 - t1}: ns', flush=True)
    red_log.stop()
    return total


if __name__ == "__main__":
    fexec = lithops.FunctionExecutor()

    stream_id = fexec.executor_id
    local_log = util.RemoteLoggingFeed(stream_id)
    local_log.start()

    fexec.map_reduce(my_map_function, iterdata, my_reduce_function)
    print(fexec.get_result())

    local_log.stop()
