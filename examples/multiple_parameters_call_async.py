"""
Simple PyWren examples using one single function invocation
with multiple parameters.

You can send multiple parameters to a single call function
writing them into a list. The parameters will be mapped in
the order you wrote them. In the following example the x
parameter will take the value 3 and the y parameter will
take the value 6.
"""
import pywren_ibm_cloud as pywren


params = [3, 6]


def my_function(x, y):
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
    pw = pywren.ibm_cf_executor()
    pw.call_async(my_function, params)
    print(pw.get_result())

    """
    The parameters can also be sent into a dictionary. In this
    case you have to map them to the correct parameter of the
    function as in the next example.
    """
    params = {'x': 2, 'y': 8}

    pw = pywren.ibm_cf_executor()
    pw.call_async(my_function, params)
    print(pw.get_result())

    """
    If you want to send a list or a dict as a parameter of the
    function, you must enclose them with [] as in the next
    example.
    """
    params = [[1, 2, 3, 4, 5]]

    pw = pywren.ibm_cf_executor()
    pw.call_async(sum_list, params)
    print(pw.get_result())

    """
    You can also send multiple parameters which include a list
    """
    params = [[1, 2, 3, 4, 5], 5]

    pw = pywren.ibm_cf_executor()
    pw.call_async(sum_list_mult, params)
    print(pw.get_result())

    """
    Or alternatively
    """
    params = {'list_of_numbers': [1, 2, 3, 4, 5], 'x': 3}

    pw = pywren.ibm_cf_executor()
    pw.call_async(sum_list_mult, params)
    print(pw.get_result())
