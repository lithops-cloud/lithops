"""
Simple Lithops examples using one single function invocation
with multiple parameters.

You can send multiple parameters to a single call function
writing them into a list. The parameters will be mapped in
the order you wrote them. In the following example the x
parameter will take the value 3 and the y parameter will
take the value 6.
"""
import lithops


def my_function(x, y):
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
    args = (3, 6)
    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function, args)
    print(fexec.get_result())

    """
    The parameters can also be sent into a dictionary. In this
    case you have to map them to the correct parameter of the
    function as in the next example.
    """
    kwargs = {'x': 2, 'y': 8}

    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function, kwargs)
    print(fexec.get_result())

    """
    If you want to send a list or a dict as a parameter of the
    function, you must enclose them with [] as in the next
    example.
    """
    args = ([1, 2, 3, 4, 5], )

    fexec = lithops.FunctionExecutor()
    fexec.call_async(sum_list, args)
    print(fexec.get_result())

    """
    You can also send multiple parameters which include a list
    """
    args = ([1, 2, 3, 4, 5], 5)

    fexec = lithops.FunctionExecutor()
    fexec.call_async(sum_list_mult, args)
    print(fexec.get_result())

    """
    Or alternatively
    """
    kwargs = {'list_of_numbers': [1, 2, 3, 4, 5], 'x': 3}

    fexec = lithops.FunctionExecutor()
    fexec.call_async(sum_list_mult, kwargs)
    print(fexec.get_result())
