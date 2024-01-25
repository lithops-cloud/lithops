"""
Simple Lithops example using one single function invocation with a
cythonized function located in function.cpython-39-x86_64-linux-gnu.so

Commands to compile the function.py into function.so (Ubuntu):
cython3 -3 --embed -X always_allow_keywords=true -o function.c function.py
gcc -shared -o function.so -fPIC -I /usr/include/python3.9 function.c

To make this example working, you have to delete funtion.py and rename
function.cpython-39-x86_64-linux-gnu.so -> function.so
"""
import lithops
from function import my_c_function


if __name__ == '__main__':
    fexec = lithops.FunctionExecutor(log_level='DEBUG')
    fexec.call_async(my_c_function, 3)
    print(fexec.get_result())
