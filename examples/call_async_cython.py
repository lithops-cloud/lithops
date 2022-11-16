"""
Simple Lithops example using one single function invocation
with a cythonized function located in function.so

Commands to convert function.py to function.so:
cython3 --embed -o function.c function.py
gcc -shared -o function.so -fPIC -I /usr/include/python3.9 function.c
"""
import lithops
from function import my_c_function


def my_function(x):
    return my_c_function(x)


if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function, 3)
    print(fexec.get_result())
