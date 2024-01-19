"""
Simple Lithops example using the map_reduce method.

In this example the map_reduce() method will launch one
map function for each entry in 'iterdata', and then it will
wait locally for the reduce result.
"""
import lithops
import time

iterdata = [1, 2, 3, 4, 5]


def my_map_function(x):
    time.sleep(x * 2)
    return x + 7


def my_reduce_function(results):
    total = 0
    for map_result in results:
        total = total + map_result
    return total


if __name__ == "__main__":
    """
    By default the reducer is spawned when 20% of the map functions
    are completed.
    """
    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function)
    print(fexec.get_result())

    """
    Set 'spawn_reducer=0' to immediately spawn the reducer, without
    waiting any map activation to be completed.
    """
    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function, spawn_reducer=0)
    print(fexec.get_result())

    """
    Set 'spawn_reducer=80' to spawn the reducer after 80% of completed map
    activations.
    """
    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function, spawn_reducer=80)
    print(fexec.get_result())
