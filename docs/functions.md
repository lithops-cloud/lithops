# PyWren Functions and Parameters

PyWren for IBM Cloud allows to send multiple parameters in the function invocation.

## Single function invocation using the call_async() method.
You can send multiple parameters to a single call function writing them into a list. The parameters will be mapped in
the order you wrote them. In the following example the x  parameter will take the value 3 and the y parameter will 
take the value 6.

```python
import pywren_ibm_cloud as pywren

params = [3, 6]

def my_function(x, y):
    return x + y

pw = pywren.ibm_cf_executor()
pw.call_async(my_function, params)
print (pw.get_result())
```

The parameters can also be sent into a dictionary. In this case you have to map them to the correct parameter of the
function as in the next example.

```python
import pywren_ibm_cloud as pywren

params = {'x': 2, 'y': 8}

def my_function(x, y):
    return x + y

pw = pywren.ibm_cf_executor()
pw.call_async(my_function, params)
print (pw.get_result())
```

If you want to send a list or a dict as a parameter of the function, you must enclose them with [] as in the next 
example.

```python
import pywren_ibm_cloud as pywren

params = [[1, 2, 3, 4, 5]]

def sum_list(list_of_numbers):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total

pw = pywren.ibm_cf_executor()
pw.call_async(sum_list, params)
print (pw.get_result())
```

You can also send multiple parameters which include a list.

```python
import pywren_ibm_cloud as pywren

params = [[1, 2, 3, 4, 5], 5]

def sum_list_mult(list_of_numbers, x):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total*x

pw = pywren.ibm_cf_executor()
pw.call_async(sum_list_mult, params)
print (pw.get_result())
```

Or alternatively using a dict.

```python
import pywren_ibm_cloud as pywren

params = {'list_of_numbers': [1, 2, 3, 4, 5], 'x': 3}

pw = pywren.ibm_cf_executor()
pw.call_async(sum_list_mult, params)
print (pw.get_result())
```

To test all of the previous examples run the [multiple_parameters_call_async.py](../examples/multiple_parameters_call_async.py) located in the `examples` folder.

## Multiple function invocation using the map() and map_reduce() methods.
The 'iterdata' variable must be always a list []. In this case to send multiple parameters to the function, the parameters of
each function must be enclosed within another list [] as in the next example. The parameters will be mapped in the order you wrote
them.

```python
import pywren_ibm_cloud as pywren

iterdata = [  # Init list of parameters for PyWren
           [1, 2],  # Parameters for function1
           [3, 4],  # Parameters for function2
           [5, 6],  # Parameters for function3
           ]  # End list of parameters for PyWren

def my_function(x, y):
    return x + y

pw = pywren.ibm_cf_executor()
pw.map(my_function, iterdata)
print (pw.get_result())
```

The parameters can also be sent into a dictionary. In this case you have to map them to the correct parameter of the
function as in the next example.

```python
import pywren_ibm_cloud as pywren

iterdata = [  # Init list of parameters for PyWren
           {'x': 1, 'y': 2},  # Parameters for function1
           {'x': 3, 'y': 4},  # Parameters for function2
           {'x': 5, 'y': 6},  # Parameters for function3
           ]  # End list of parameters for PyWren

def my_function(x, y):
    return x + y

pw = pywren.ibm_cf_executor()
pw.map(my_function, iterdata)
print (pw.get_result())
```

If you want to send a list or a dict as a parameter of the function, you must enclose them with [] as in the next 
example.

```python
import pywren_ibm_cloud as pywren

iterdata = [  # Init list of parameters for PyWren
           [[1, 2]],  # Parameters for function1
           [[3, 4]],  # Parameters for function2
           [[5, 6]],  # Parameters for function3
           ]  # End list of parameters for PyWren

def sum_list(list_of_numbers):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total

pw = pywren.ibm_cf_executor()
pw.map(sum_list, iterdata)
print (pw.get_result())
```

You can also send multiple parameters which include a list.

```python
import pywren_ibm_cloud as pywren

iterdata = [  # Init list of parameters for PyWren
           [[1, 2, 3, 4, 5], 2],  # Parameters for function1
           [[6, 7, 8, 9, 10], 3],  # Parameters for function2
           [[11, 12, 13, 14, 15], 4],  # Parameters for function3
           ]  # End list of parameters for PyWren

def sum_list_mult(list_of_numbers, x):
    total = 0
    for num in list_of_numbers:
        total = total+num
    return total*x

pw = pywren.ibm_cf_executor()
pw.map(sum_list_mult, iterdata)
print (pw.get_result())
```

Or alternatively using a dict.

```python
import pywren_ibm_cloud as pywren

iterdata = [  # Init list of parameters for PyWren
           {'list_of_numbers': [1, 2, 3, 4, 5], 'x': 2},  # Parameters for function1
           {'list_of_numbers': [6, 7, 8, 9, 10], 'x': 3},  # Parameters for function2
           {'list_of_numbers': [11, 12, 13, 14, 15], 'x': 4},  # Parameters for function3
           ]  # End list of parameters for PyWren

pw = pywren.ibm_cf_executor()
pw.map(sum_list_mult, iterdata)
print(pw.get_result())
```


## Common parameters across functions invocations
Sometimes, functions have common parameters for all the invocations. In this case you have two options to proceed:

- Setting variables in the global scope: You can define the desired variables in the global scope before defining the function. All of these variables can be catched within the function, for example:

    ```python
    import pywren_ibm_cloud as pywren
    
    y = 10
    
    def sum_x_y(x):
        return x+y
    
    iterdata = [0, 1, 2]
    pw = pywren.ibm_cf_executor()
    pw.map(sum_list_mult, iterdata)
    print(pw.get_result())
    ```

- Using `extra_params` parameter in the `map()` or `map_reduce()` calls:

    ```python
    import pywren_ibm_cloud as pywren
    
    def sum_x_y(x, y):
        return x+y
    
    iterdata = [0, 1, 2]
    pw = pywren.ibm_cf_executor()
    pw.map(sum_x_y, iterdata, extra_params=[10])
    print(pw.get_result())
    ```
    
    `extra_params` must be always a list or a dict, depending of iterdata. The previous example is equivalent to this:
    
    ```python
    import pywren_ibm_cloud as pywren
    
    def sum_x_y(x, y):
        return x+y

    iterdata = [  # Init list of parameters for PyWren
                [0, 10],  # Parameters for function1
                [1, 10],  # Parameters for function2
                [2, 10],  # Parameters for function3
               ]  # End list of parameters for PyWren
    pw = pywren.ibm_cf_executor()
    pw.map(sum_x_y, iterdata)
    print(pw.get_result())
    ```

To test all of the previous examples run the [multiple_parameters_map.py](../examples/multiple_parameters_map.py) located in the `examples/` folder.


## Reserved parameters

Take into account that there are some reserved parameter names that activate internal logic. These reserved parameters are:

- **id**: To get the call id. For instance, if you spawn 10 activations of a function, you will get here a number from 0 to 9, for example: [map.py](../examples/map.py)

- **ibm_cos**: To get a ready-to use [ibm_boto3.Client()](https://ibm.github.io/ibm-cos-sdk-python/reference/services/s3.html#client) instance. This allows you to access your IBM COS account from any function in an easy way, for example: [ibmcos_arg.py](../examples/ibmcos_arg.py)

- **rabbitmq**: To get a ready-to use [pika.BlockingConnection()](https://pika.readthedocs.io/en/0.13.1/modules/adapters/blocking.html) instance (AMQP URL must be set in the [configuration](config/) to make it working). This allows you to access the RabbitMQ service from any function in an easy way, for example: [rabbitmq_arg.py](../examples/rabbitmq_arg.py)

- **obj** & **url**: These two parameter activate internal logic that allows to process data objects stored in the IBM Cloud Object Storage service or public URLs in transparent way. See [data-processing](../docs/data-processing.md) documentation for more details and instructions on how to use this built-in data-processing logic.
