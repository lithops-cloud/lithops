# Multiple parameters in IBM-PyWren functions

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

## Multiple function invocation using the map() method.
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
pw.call_async(my_function, params)
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
pw.call_async(my_function, params)
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
pw.call_async(sum_list, params)
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
pw.call_async(sum_list_mult, params)
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
pw.call_async(sum_list_mult, params)
print (pw.get_result())
```

To test all of the previous examples run the [multiple_parameters_map.py](../examples/multiple_parameters_map.py) located in the `examples` folder.

## Multiple function invocation using the map_reduce() method.

With the map_reduce() method, the previous examples showed in the map() method are also valid. 
However, in this case you have to take into account that there are some reserved parameter names. They are **bucket**, **key** and **url**.
These parameters should be used when you want to process objcts from COS or a public url with the map_reduce() method.

* **bucket** : If you put the parameter **bucket** in the map function parameters, you are telling to PyWren that you want to process the objects
  located in your COS bucket. In this case you must write also the parameters **key** and **data_stream** to the map function parameters
  as in the next example. The **key** parameter will contain the full object key in the format 'bucketname/objectname'. The data_stream
  parameter will contain the data object from COS ready to be read.
 
  	```python
	bucketname = 'sample-data'
	
	def my_map_function(bucket, key, data_stream):
       print('I am processing the object {}'.format(key))
       counter = {}
        
       data = data_stream.read()
        
       for line in data.splitlines():
           for word in line.decode('utf-8').split():
               if word not in counter:
                   counter[word] = 1
               else:
                   counter[word] += 1
        
       return counter
   ```
    
    More parameters are allowed in the map function. However, if you want to process a bucket/s, you must also put: **bucket**, **key** and **data_stream** as parameters of the map function.
    
    The full example is in [map_reduce_cos_bucket](../examples/map_reduce_cos_bucket.py) located in the `examples` folder

* **key** : If you put only the parameter **key** in the map function parameters, you are telling to PyWren that you want to process the objects listed in the `iterdata` variable and
  located in your COS account. In this case you must write also the parameter **data_stream** to the map function parameters. The data_stream
  parameter will contain the data object from COS ready to be read.
  	
  	```python
   iterdata = ['sample-data/obj1.txt',
               'sample-data/obj2.txt',
               'sample-data/obj3.txt'] 

	def my_map_function(key, data_stream):
	    print('I am processing the object {}'.format(key))
	    counter = {}
	    
	    data = data_stream.read()
	    
	    for line in data.splitlines():
	        for word in line.decode('utf-8').split():
	            if word not in counter:
	                counter[word] = 1
	            else:
	                counter[word] += 1
	
	    return counter
	```
	
	The full example is in [map_reduce_cos_key](../examples/map_reduce_cos_key.py) located in the `examples` folder
	
	In this case more parameters are allowed. They must be put enclosed with [] as in the map() method example explained above.
	The parameters will be mapped in the order you wrote them. Just make sure you always put the **data_stream** parameter at the end, and the
	parameter **key** points to the object key, in the next example located in the second position of the parameters of the map function.
	
  	```python
   iterdata = [  # Init list of parameters for PyWren
               ['cat', 'sample-data/obj1.txt'],  # Parameters for function1
               ['dog', 'sample-data/obj2.txt'],  # Parameters for function2
               ['canary', 'sample-data/obj3.txt']  # Parameters for function3
              ]  # End list of parameters for PyWren

   def my_map_function(name, key, data_stream):
       print('I am a {}'.format(name))
       print('I am processing the object {}'.format(key))
       counter = {}
        
       data = data_stream.read()
        
       for line in data.splitlines():
           for word in line.decode('utf-8').split():
               if word not in counter:
                   counter[word] = 1
               else:
                   counter[word] += 1
        
       return counter
	```	

* **url** : If you put the parameter **url** in the map function parameters, you are telling to PyWren that you want to process the objects listed in the `iterdata` variable and
  located in a public URL. In this case you must write also the parameter **data_stream** to the map function parameters. The data_stream
  parameter will contain the data object from the public URL ready to be read.

  	```python
   iterdata = ['https://dataplatform.ibm.com/exchange-api/v1/entries/107ab470f90be9a4815791d8ec829133/data?accessKey=2bae90b7a0ecacef062954f94e98e0d3',
               'https://dataplatform.ibm.com/exchange-api/v1/entries/9fc8543fabfc26f908cf0c592c89d137/data?accessKey=4b4cf6ce8ad2338fd042e30513693eb0'] 

   def my_map_function(url, data_stream):
       print('I am processing the object {}'.format(key))
       counter = {}
    
       data = data_stream.read()
    
       for line in data.splitlines():
           for word in line.decode('utf-8').split():
               if word not in counter:
                   counter[word] = 1
               else:
                   counter[word] += 1
    
       return counter
	```
	
	The full example is in [map_reduce_url](../examples/map_reduce_url.py) located in the `examples` folder.

	In this case more parameters are also allowed, just like if you use the **key** parameter explained above.
