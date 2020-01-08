# Using PyWren to process data from IBM Cloud Object Storage and public URLs

PyWren for IBM Cloud functions has built-in logic for processing data objects from public URLs and IBM Cloud Object Storage. When you write in the parameters of a function the parameter name: **obj**, you are telling to PyWren that you want to process objects located in IBM Cloud Object Storage service. In contrast, when you write in the parameters of a function the parameter name: **url**, you are telling to PyWren that you want to process data from publicly accessible URLs. 

Additionally, the built-in data-processing logic integrates a **data partitioner** system that allows to automatically split the dataset in smallest chunks. Splitting a file into smaller chunks permit to leverage the parallelism provided by IBM Cloud Functions or Knative to process the data. We designed the partitioner within the `map()` and `map_reduce()` API calls, an it is configurable by specifying the *size of the chunk*, or the *number of chunks* to split each file. The current implementation of the data partitioner supports to split files that contain multiple lines (or rows) ended by '\n', for example, a .txt book or a common .csv file among others. More data-types will be supported in future releases.


## Processing data from IBM Cloud Object Storage
This mode is activated when you write the parameter **obj** into the function arguments. The input to the partitioner may be either a list of buckets, a list of buckets with object prefix, or a list of data objects. If you set the *size of the chunk* or the *number of chunks*, the partitioner is activated inside PyWren and it is responsible to split the objects into smaller chunks, eventually running one function activation for each generated chunk. If *size of the chunk* and *number of chunks* are not set, chunk is an entire object, so one function activation is executed for each individual object.

The *obj* parameter is a python class from where you can access all the information related to the object (or chunk) that the function is processing. For example, consider the following function that shows all the available attributes in *obj*:


```python
def my_map_function(obj):
    print(obj.bucket)
    print(obj.key)
    print(obj.data_stream.read())
    print(obj.part)
    print(obj.data_byte_range)
    print(obj.chunk_size)
```

As stated above, the allowed inputs of the function can be:

- Input data is a bucket or a list of buckets. See an example in [map_reduce_cos_bucket.py](../examples/map_reduce_cos_bucket.py):
    ```python
    iterdata = 'cos://bucket1'
    ```

-  Input data is a bucket(s) with object prefix. See an example in [map_cos_prefix.py](../examples/map_cos_prefix.py):
    ```python
    iterdata = ['cos://bucket1/images/', 'cos://bucket1/videos/']
    ```
    Notice that you must write the end slash (/) to inform partitioner you are providing an object prefix.

- Input data is a list of object keys. See an example in [map_reduce_cos_key.py](../examples/map_reduce_cos_key.py):
    ```python
    iterdata = ['cos://bucket1/object1', 'cos://bucket1/object2', 'cos://bucket1/object3'] 
    ```
    
Notice that *iterdata* must be only one of the previous 3 types. Intermingled types are not allowed. For example, you cannot set in the same *iterdata* a bucket and some object keys:

```python
iterdata = ['cos://bucket1', 'cos://bucket1/object2', 'cos://bucket1/object3']  # Not allowed
```

Once iterdata is defined, you can execute PyWren as usual, either using *map()* or *map_reduce()* calls. If you need to split the files in smaller chunks, you can set (optionally) the *chunk_size* or *chunk_n* parameters.

```python
import pywren_ibm_cloud as pywren

chunk_size = 4*1024**2  # 4MB

pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, iterdata, chunk_size=chunk_size)
result = pw.get_result()
```

## Processing data from public URLs
This mode is activated when you write the parameter **url** into the function arguments. The input to the partitioner must be a list of object URls. As with COS data processing, if you set the *size of the chunk* or the *number of chunks*, the partitioner is activated inside PyWren and it is responsible to split the objects into smaller chunks, as long as the remote storage server allows requests in chunks (ranges). If range requests are not allowed in the remote storage server, each URL is treated as a single object. For example consider the following code that shows all the available attributes in *url*:

```python
import pywren_ibm_cloud as pywren

def my_map_function(url):
    print(url.path)
    print(url.data_stream.read())
    print(url.part)
    print(url.data_byte_range)
    print(url.chunk_size)

    for line in url.data_stream:
        # Do some process
    return partial_intersting_data

def my_reduce_function(results):
    for partial_intersting_data in results:
        # Do some process
    return final_result

iterdata = ['http://myurl/myobject1', 'http://myurl/myobject1'] 
chunk_n = 5

pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, iterdata, my_reduce_function, chunk_n=chunk_n)
result = pw.get_result()
```

See a complete example in [map_reduce_url.py](../examples/map_reduce_url.py).


## Reducer granularity            
When using the `map_reduce()` API call with `chunk_size` or `chunk_n`, by default there will be only one reducer for all the object chunks from all the objects. Alternatively, you can spawn one reducer for each object by setting the parameter `reducer_one_per_object=True`.

```python
pw.map_reduce(my_map_function, bucket_name, my_reduce_function, 
              chunk_size=chunk_size, reducer_one_per_object=True)
```
