"""
This function is used in call_async_cython.py

Commands to compile the function.py into function.so:
cython3 --embed -o function.c function.py
gcc -shared -o function.so -fPIC -I /usr/include/python3.9 function.c
"""
def my_c_function(x):
    return x + 7
