"""
Simple Lithops example using the function chaining pattern
in the Futures API.
"""
import lithops


def my_func1(x):
    return x + 2, 5


def my_func2(x, y):
    return x + y, 5, 2


def my_func3(x, y, z):
    return x + y + z


if __name__ == '__main__':
    iterdata = [1, 2, 3]
    fexec = lithops.FunctionExecutor(log_level='INFO')
    res = fexec.map(my_func1, iterdata).map(my_func2).map(my_func3).get_result()
    print(res)
