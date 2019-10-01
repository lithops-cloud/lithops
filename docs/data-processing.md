# Using PyWren to process data from IBM Cloud Object Storage and public URLs

PyWren for IBM Cloud functions has built-in logic for processing data objects from public URLs and IBM Cloud Object Storage. When you write in the parameters of a function the parameter name: **obj**, you are telling to PyWren that you want to process objects located in IBM Cloud Object Storage service. In contrast, when you write in the parameters of a function the parameter name: **url**, you are telling to PyWren that you want to process data from publicly accessible URLs. 

Additionally, the built-in data-processing logic integrates a **data partitioner** system that allows to automatically split the dataset in smallest chunks. Splitting a file into smaller chunks permit to leverage the parallelism provided by IBM Cloud Functions or Knative to process the data. We designed the partitioner within the `map()` and `map_reduce()` API calls, an it is configurable by specifying the *size of the chunk*, or the *number of chunks* to split each file. The current implementation of the data partitioner supports to split files that contain multiple lines (or rows) ended by '\n', for example, a .txt book or a common .csv file among others. More data-types will be supported in future releases.


## Processing data from IBM Cloud Object Storage
The input to the partitioner may be either a list of data objects, a list of URLs or the entire bucket itself. The partitioner is activated inside PyWren and it responsible to split the objects into smaller chunks. It executes one *`my_map_function`* for each object chunk and when all executions are completed, the partitioner executes the *`my_reduce_function`*. The reduce function will wait for all the partial results before processing them. 


#### Partitioner get a list of objects

```python
import pywren_ibm_cloud as pywren

iterdata = ['cos://bucket1/object1', 'cos://bucket1/object2', 'cos://bucket1/object3'] 

def my_map_function(obj):
    for line in obj.data_stream:
        # Do some process
    return partial_intersting_data

def my_reduce_function(results):
    for partial_intersting_data in results:
        # Do some process
    return final_result

chunk_size = 4*1024**2  # 4MB

pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, iterdata, my_reduce_function, chunk_size=chunk_size)
result = pw.get_result()
```

| method | method signature |
|---| ---| 
| `pw.map_reduce`(`my_map_function`, `iterdata`, `my_reduce_function`, `chunk_size`)| `iterdata` contains list of objects in the format of `bucket_name/object_name` |
| `my_map_function`(`obj`) | `obj` is a Python class that contains the *bucket*, *key* and *data_stream* of the object assigned to the activation|

#### Partitioner gets entire bucket

Commonly, a dataset may contains hundreds or thousands of files, so the previous approach where you have to specify each object one by one is not well suited in this case. With this new `map_reduce()` method you can specify, instead, the bucket name which contains all the object of the dataset.
    
```python
import pywren_ibm_cloud as pywren

bucket_name = 'cos://my_data_bucket'

def my_map_function(obj, ibm_cos):
    for line in obj.data_stream:
        # Do some process
    return partial_intersting_data

def my_reduce_function(results):
    for partial_intersting_data in results:
        # Do some process
    return final_result

chunk_size = 4*1024**2  # 4MB

pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, bucket_name, my_reduce_function, chunk_size=chunk_size)
result = pw.get_result()
```

* If `chunk_size=None` then partitioner's granularity is a single object. 
    
| method | method signature |
|---| ---| 
| `pw.map_reduce`(`my_map_function`, `bucket_name`, `my_reduce_function`, `chunk_size`)| `bucket_name` contains the name of the bucket |
| `my_map_function`(`obj`, `ibm_cos`) | `obj` is a Python class that contains the *bucket*, *key* and *data_stream* of the object assigned to the activation. `ibm_cos` is an optional parameter which provides a `ibm_boto3.Client()`|


## Processing data from public URLs

```python
import pywren_ibm_cloud as pywren

iterdata = ['http://myurl/myobject1', 'http://myurl/myobject1'] 

def my_map_function(url):
    for line in url.data_stream:
        # Do some process
    return partial_intersting_data

def my_reduce_function(results):
    for partial_intersting_data in results:
        # Do some process
    return final_result

chunk_size = 4*1024**2  # 4MB

pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, iterdata, my_reduce_function, chunk_size=chunk_size)
result = pw.get_result()
```

| method | method signature |
|---| ---| 
| `pw.map_reduce`(`my_map_function`, `iterdata`, `my_reduce_function`, `chunk_size`)| `iterdata` contains list of objects in the format of `http://myurl/myobject.data` |
| `my_map_function`(`url`) | `url` is an object Pytnon class that contains the url *path* assigned to the activation (an entry of iterdata) and the *data_stream*|

## Reducer granularity            
By default there will be one reducer for all the objects. If you need one reducer for each object, you must set the parameter
`reducer_one_per_object=True` into the **map_reduce()** method.

```python
pw.map_reduce(my_map_function, bucket_name, my_reduce_function, 
              chunk_size=chunk_size, reducer_one_per_object=True)
```

