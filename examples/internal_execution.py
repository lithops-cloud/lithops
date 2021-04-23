"""
Simple Lithops example using one single function invocation
which internally invokes a map.
"""
import lithops


def my_map_function(id, x):
    print("I'm activation number {}".format(id))
    return x + 7


def my_function(x):
    iterdata = range(x)
    fexec = lithops.FunctionExecutor()
    return fexec.map(my_map_function, iterdata)


if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function, 3)
    fexec.wait()
    print(fexec.get_result())
