"""
Simple Lithops example using one single function invocation
"""
import lithops


def my_function(x):
    return x + 7


if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function, 3)
    print(fexec.get_result())
