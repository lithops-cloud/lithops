"""
Simple PyWren example using the map() or the map_reduce() methods
with multiple parameters in the map function.

In this example the map() method will launch one map function
for each entry in 'iterdata'. Finally it will print the results
for each invocation with pw.get_result()

The 'iterdata' variable must be always a list []. In this case
to send multiple parameters to the function, the parameters of
each function must be enclosed within another list [] as in the
next example. The parameters will be mapped in the order you wrote
them.
"""
import pywren_ibm_cloud as pywren


def my_map_function(x, y):
    return x + y


def sum_list(list_of_numbers):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total


def sum_list_mult(list_of_numbers, x):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total*x


if __name__ == "__main__":
    iterdata = [  # Init list of parameters for PyWren
               [1, 2],  # Parameters for function1
               [3, 4],  # Parameters for function2
               [5, 6],  # Parameters for function3
               ]  # End list of parameters for PyWren

    pw = pywren.ibm_cf_executor()
    pw.map(my_map_function, iterdata)
    print(pw.get_result())

    """
    The parameters can also be sent into a dictionary. In this
    case you have to map them to the correct parameter of the
    function as in the next example.
    """
    iterdata = [  # Init list of parameters for PyWren
               {'x': 1, 'y': 2},  # Parameters for function1
               {'x': 3, 'y': 4},  # Parameters for function2
               {'x': 5, 'y': 6},  # Parameters for function3
               ]  # End list of parameters for PyWren

    pw = pywren.ibm_cf_executor()
    pw.map(my_map_function, iterdata)
    print(pw.get_result())

    """
    If you want to send a list or a dict as a parameter of the
    function, you must enclose them with [] as in the next
    example.
    """
    iterdata = [  # Init list of parameters for PyWren
               [[1, 2]],  # Parameters for function1
               [[3, 4]],  # Parameters for function2
               [[5, 6]],  # Parameters for function3
               ]  # End list of parameters for PyWren

    pw = pywren.ibm_cf_executor()
    pw.map(sum_list, iterdata)
    print(pw.get_result())

    """
    You can also send multiple parameters which include a list
    """
    iterdata = [  # Init list of parameters for PyWren
               [[1, 2, 3, 4, 5], 2],  # Parameters for function1
               [[6, 7, 8, 9, 10], 3],  # Parameters for function2
               [[11, 12, 13, 14, 15], 4],  # Parameters for function3
               ]  # End list of parameters for PyWren

    pw = pywren.ibm_cf_executor()
    pw.map(sum_list_mult, iterdata)
    print(pw.get_result())

    """
    Or alternatively
    """
    iterdata = [  # Init list of parameters for PyWren
               {'list_of_numbers': [1, 2, 3, 4, 5], 'x': 2},  # Parameters for function1
               {'list_of_numbers': [6, 7, 8, 9, 10], 'x': 3},  # Parameters for function2
               {'list_of_numbers': [11, 12, 13, 14, 15], 'x': 4},  # Parameters for function3
               ]  # End list of parameters for PyWren

    pw = pywren.ibm_cf_executor()
    pw.map(sum_list_mult, iterdata)
    print(pw.get_result())

    """
    extra_params
    """
    iterdata = [0, 1, 2]
    pw = pywren.ibm_cf_executor()
    pw.map(my_map_function, iterdata, extra_params=[10])
    print(pw.get_result())
