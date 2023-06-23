Functions and Parameters
========================

This document describes how to invoke functions based on the *iterdata* variable. In this sense, Lithops allows to send either *args* or *kwargs* in the function invocation. Take into account that there are some reserved parameter names that activate internal logic, and they cannot be used as regular parameters.

Reserved parameters
-------------------
Reserved parameters are only accessible when using the [Futures API](api_futures.rst).


- **id**: To get the call id. For instance, if you spawn 10 activations of a function, you will get here a number from 0 to 9, for example: [map.py](https://github.com/lithops-cloud/lithops/blob/master/examples/map.py)

- **obj**: This parameter is used to activate the internal logic that allows to process data objects stored in the object store or public URLs in a transparent way. See [data processing](data_processing.rst) documentation for more details and instructions on how to use this built-in data-processing logic.

- **storage**: To get a ready-to use lithops.storage.Storage() instance. This allows you to access your storage backend defined in configuration from any function in an easy way, for example: [storage_arg.py](https://github.com/lithops-cloud/lithops/blob/master/examples/storage_arg.py)

- **rabbitmq**: To get a ready-to use [pika.BlockingConnection()](https://pika.readthedocs.io/en/latest/modules/adapters/blocking.html) instance (AMQP URL must be set in the configuration to make it working). This allows you to access the RabbitMQ service from any function in an easy way, for example: [rabbitmq_arg.py](https://github.com/lithops-cloud/lithops/blob/master/examples/rabbitmq_arg.py)



Parameters in the call_async() method 
-------------------------------------

You can send multiple parameters to a single call function writing them into a list. The parameters will be mapped in
the order you wrote them. In the following example the x  parameter will take the value 3 and the y parameter will 
take the value 6.

```python
import lithops

args = (3, 6)

def my_function(x, y):
    return x + y

fexec = lithops.FunctionExecutor()
fexec.call_async(my_function, args)
print (fexec.get_result())
```

The parameters can also be sent into a dictionary. In this case you have to map them to the correct parameter of the
function as in the next example.

```python
import lithops

kwargs = {'x': 2, 'y': 8}

def my_function(x, y):
    return x + y

fexec = lithops.FunctionExecutor()
fexec.call_async(my_function, kwargs)
print (fexec.get_result())
```

If you want to send a list or a dict as a parameter of the function, you must enclose them with [] as in the next 
example.

```python
import lithops

args = ([1, 2, 3, 4, 5],)

def sum_list(list_of_numbers):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total

fexec = lithops.FunctionExecutor()
fexec.call_async(sum_list, args)
print (fexec.get_result())
```

You can also send multiple parameters which include a list.

```python
import lithops

args = ([1, 2, 3, 4, 5], 5)

def sum_list_mult(list_of_numbers, x):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total*x

fexec = lithops.FunctionExecutor()
fexec.call_async(sum_list_mult, args)
print (fexec.get_result())
```

Or alternatively using a dict.

```python
import lithops

kwargs = {'list_of_numbers': [1, 2, 3, 4, 5], 'x': 3}

fexec = lithops.FunctionExecutor()
fexec.call_async(sum_list_mult, kwargs)
print (fexec.get_result())
```

To test all of the previous examples run the [multiple_args_call_async.py](https://github.com/lithops-cloud/lithops/blob/master/examples/multiple_args_call_async.py).


Parameters in the map() and map_reduce() methods 
------------------------------------------------

The 'iterdata' variable must be always a list []. In this case to send multiple parameters to the function, the parameters of
each function must be enclosed within a tuple () as in the next example. The parameters will be mapped in the order you wrote
them.

```python
import lithops

args = [  # Init list of parameters for Lithops
        (1, 2),  # Args for function1
        (3, 4),  # Args for function2
        (5, 6),  # Args for function3
       ]  # End list of parameters for Lithops

def my_function(x, y):
    return x + y

fexec = lithops.FunctionExecutor()
fexec.map(my_function, args)
print (fexec.get_result())
```

The parameters can also be sent into a dictionary. In this case you have to map them to the correct parameter of the
function as in the next example.

```python
import lithops

kwargs = [  # Init list of parameters for Lithops
          {'x': 1, 'y': 2},  # Kwargs for function1
          {'x': 3, 'y': 4},  # Kwargs for function2
          {'x': 5, 'y': 6},  # Kwargs for function3
         ]  # End list of parameters for Lithops

def my_function(x, y):
    return x + y

fexec = lithops.FunctionExecutor()
fexec.map(my_function, kwargs)
print (fexec.get_result())
```

If you want to send a list, a tuple or a dict as a parameter of the function, you must enclose them with () as in the next 
example.

```python
import lithops

args = [  # Init list of parameters for Lithops
         ([1, 2],),  # Args for function1
         ([3, 4],),  # Args for function2
         ([5, 6],),  # Args for function3
       ]  # End list of parameters for Lithops

def sum_list(list_of_numbers):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total

fexec = lithops.FunctionExecutor()
fexec.map(sum_list, args)
print (fexec.get_result())
```

You can also send multiple parameters which include a list.

```python
import lithops

args = [  # Init list of parameters for Lithops
        ([1, 2, 3, 4, 5], 2),  # Args for function1
        ([6, 7, 8, 9, 10], 3),  # Args for function2
        ([11, 12, 13, 14, 15], 4),  # Args for function3
       ]  # End list of parameters for Lithops

def sum_list_mult(list_of_numbers, x):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total*x

fexec = lithops.FunctionExecutor()
fexec.map(sum_list_mult, args)
print (fexec.get_result())
```

Or alternatively using a dict.

```python
import lithops

kwargs = [  # Init list of parameters for Lithops
           {'list_of_numbers': [1, 2, 3, 4, 5], 'x': 2},  # Kwargs for function1
           {'list_of_numbers': [6, 7, 8, 9, 10], 'x': 3},  # Kwargs for function2
           {'list_of_numbers': [11, 12, 13, 14, 15], 'x': 4},  # Kwargs for function3
         ]  # End list of parameters for Lithops

fexec = lithops.FunctionExecutor()
fexec.map(sum_list_mult, kwargs)
print(fexec.get_result())
```


Common parameters across functions invocations
----------------------------------------------

Sometimes, functions have common parameters for all the invocations. In this case you have two options to proceed:

- Setting variables in the global scope: You can define the desired variables in the global scope before defining the function. All of these variables can be catched within the function, for example:

    ```python
    import lithops
    
    y = 10
    
    def sum_x_y(x):
        return x+y
    
    iterdata = [0, 1, 2]
    fexec = lithops.FunctionExecutor()
    fexec.map(sum_x_y, iterdata)
    print(fexec.get_result())
    ```

- Using `extra_args` parameter in the `map()` or `map_reduce()` calls. `extra_args` must be a **set* or a **dict**, depending on whether `iteradata` contains *args* or *kwargs*. 

    If `iterdata` is a list of individual values or a list of sets:

    ```python
    import lithops
    
    def sum_x_y(x, y):
        return x+y
    
    args = [0, 1, 2]
    fexec = lithops.FunctionExecutor()
    fexec.map(sum_x_y, args, extra_args=(10,))
    print(fexec.get_result())
    ```
    
    The previous example is equivalent to the next:
    
    ```python
    import lithops
    
    def sum_x_y(x, y):
        return x+y

    args = [  # Init list of parameters for Lithops
            (0, 10),  # Args for function1
            (1, 10),  # Args for function2
            (2, 10),  # Args for function3
           ]  # End list of parameters for Lithops
    fexec = lithops.FunctionExecutor()
    fexec.map(sum_x_y, args)
    print(fexec.get_result())
    ```
    
    If `iterdata` is a list of dicts:

    ```python
    import lithops
    
    kwargs = [  # Init list of parameters for Lithops
              {'x': 1},  # Kwargs for function1
              {'x': 3},  # Kwargs for function2
              {'x': 5},  # Kwargs for function3
             ]  # End list of parameters for Lithops
    
    def my_function(x, y):
        return x + y
    
    fexec = lithops.FunctionExecutor()
    fexec.map(my_function, kwargs, extra_args={'y': 3})
    print(fexec.get_result())
    ```
    
    The previous example is equivalent to the next:
    
    ```python
    import lithops
    
    kwargs = [  # Init list of parameters for Lithops
              {'x': 1, 'y': 3},  # Kwargs for function1
              {'x': 3, 'y': 3},  # Kwargs for function2
              {'x': 5, 'y': 3},  # Kwargs for function3
             ]  # End list of parameters for Lithops
    
    def my_function(x, y):
        return x + y
    
    fexec = lithops.FunctionExecutor()
    fexec.map(my_function, kwargs)
    print(fexec.get_result())
    ```

To test all of the previous examples run the [multiple_args_map.py](https://github.com/lithops-cloud/lithops/blob/master/examples/multiple_args_map.py).
