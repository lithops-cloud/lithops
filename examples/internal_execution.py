"""
Simple PyWren example using one single function invocation
which internally invokes a map.
"""
import lithops


def my_map_function(id, x):
    print("I'm activation number {}".format(id))
    return x + 7


def my_function(x):
    iterdata = range(x)
    pw = lithops.ibm_cf_executor()
    return pw.map(my_map_function, iterdata)


if __name__ == '__main__':
    pw = lithops.ibm_cf_executor()
    pw.call_async(my_function, 3)
    pw.wait()
    print(pw.get_result())
