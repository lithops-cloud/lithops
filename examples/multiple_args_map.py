"""
Simple Lithops example using the map() or the map_reduce() methods
with multiple parameters in the map function.

In this example the map() method will launch one map function
for each entry in 'iterdata'. Finally it will print the results
for each invocation with fexec.get_result()

The 'iterdata' variable must be always a list []. In this case
to send multiple parameters to the function, the parameters of
each function must be enclosed within another list [] as in the
next example. The parameters will be mapped in the order you wrote
them.
"""
import lithops


def my_map_function(x, y):
    return x + y


def sum_list(list_of_numbers):
    total = 0
    for num in list_of_numbers:
        total = total + num
    return total


def sum_list_mult(list_of_numbers, x):
    total = 0
    for num in list_of_numbers:
        total = total + num
    return total * x


if __name__ == "__main__":
    args = [  # Init list of parameters for Lithops
            (1, 2),  # Args for function1
            (3, 4),  # Args for function2
            (5, 6),  # Args for function3
           ]  # End list of parameters for Lithops

    fexec = lithops.FunctionExecutor()
    fexec.map(my_map_function, args)
    print(fexec.get_result())

    """
    The parameters can also be sent into a dictionary. In this
    case you have to map them to the correct parameter of the
    function as in the next example.
    """
    kwargs = [  # Init list of parameters for Lithops
              {'x': 1, 'y': 2},  # Kwargs for function1
              {'x': 3, 'y': 4},  # Kwargs for function2
              {'x': 5, 'y': 6},  # Kwargs for function3
             ]  # End list of parameters for Lithops

    fexec = lithops.FunctionExecutor()
    fexec.map(my_map_function, kwargs)
    print(fexec.get_result())

    """
    If you want to send a list or a dict as a parameter of the
    function, you must enclose them with [] as in the next
    example.
    """
    args = [  # Init list of parameters for Lithops
            ([1, 2],),  # Args for function1
            ([3, 4],),  # Args for function2
            ([5, 6],),  # Args for function3
           ]  # End list of parameters for Lithops

    fexec = lithops.FunctionExecutor()
    fexec.map(sum_list, args)
    print(fexec.get_result())

    """
    You can also send multiple parameters which include a list
    """
    args = [  # Init list of args for Lithops
            ([1, 2, 3, 4, 5], 2),  # Args for function1
            ([6, 7, 8, 9, 10], 3),  # Args for function2
            ([11, 12, 13, 14, 15], 4)  # Args for function3
           ]  # End list of parameters for Lithops

    fexec = lithops.FunctionExecutor()
    fexec.map(sum_list_mult, args)
    print(fexec.get_result())

    """
    Or alternatively
    """
    kwargs = [  # Init list of parameters for Lithops
               {'list_of_numbers': [1, 2, 3, 4, 5], 'x': 2},  # Kwargs for function1
               {'list_of_numbers': [6, 7, 8, 9, 10], 'x': 3},  # Kwargs for function2
               {'list_of_numbers': [11, 12, 13, 14, 15], 'x': 4},  # Kwargs for function3
             ]  # End list of parameters for Lithops

    fexec = lithops.FunctionExecutor()
    fexec.map(sum_list_mult, kwargs)
    print(fexec.get_result())

    """
    extra_args
    """
    args = [0, 1, 2]
    fexec = lithops.FunctionExecutor()
    fexec.map(my_map_function, args, extra_args=(10,))
    print(fexec.get_result())

    kwargs = [  # Init list of parameters for Lithops
              {'x': 1},  # Kwargs for function1
              {'x': 3},  # Kwargs for function2
              {'x': 5},  # Kwargs for function3
             ]  # End list of parameters for Lithops

    fexec = lithops.FunctionExecutor()
    fexec.map(my_map_function, kwargs, extra_args={'y': 3})
    print(fexec.get_result())
