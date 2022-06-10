.. _data-processing:

Processing data from the Cloud
===========================================

Lithops has built-in logic for processing data objects from public URLs and object storage services. This logic is automatically activated with the reseverd parameter named **obj**. When you write in the parameters of a function the parameter name **obj**, you are telling to Lithops that you want to process objects located in an object storage service, public urls, or localhost files.

Additionally, the built-in data-processing logic integrates a **data partitioner** system that allows to automatically split the dataset in smallest chunks. Splitting a file into smaller chunks permit to leverage the parallelism provided by the compute backends to process the data. We designed the partitioner within the ``map()`` and ``map_reduce()`` API calls, an it is configurable by specifying the *size of the chunk*, or the *number of chunks* to split each file. The current implementation of the data partitioner supports to split files that contain multiple lines (or rows) ended by '\n', for example, a .txt book or a common .csv file among others. More data-types will be supported in future releases.


Cloud Object Storage
--------------------
For processing data from a cloud object storage service, the input data must be either a list of buckets, a list of buckets with object prefix, or a list of data objects. If you set the *size of the chunk* or the *number of chunks*, the partitioner is activated inside Lithops and it is responsible to split the objects into smaller chunks, eventually running one function activation for each generated chunk. If *size of the chunk* and *number of chunks* are not set, chunk is an entire object, so one function activation is executed for each individual object.

The **obj** parameter is a python class from where you can access all the information related to the object (or chunk) that the function is processing. For example, consider the following function that shows all the available attributes in **obj** when you are processing objects from an object store:


.. code:: python

    def my_map_function(obj):
        print(obj.bucket)
        print(obj.key)
        print(obj.part)
        print(obj.data_byte_range)
        print(obj.chunk_size)
    
        data = obj.data_stream.read()

The allowed inputs of a function can be:

- Input data is a bucket or a list of buckets. See an example in [map_reduce_cos_bucket.py](../../examples/map_reduce_cos_bucket.py):

.. code:: python

    iterdata = 'bucket1'

- Input data is a bucket(s) with object prefix. See an example in [map_cos_prefix.py](../../examples/map_cos_prefix.py):

.. code:: python

    iterdata = ['bucket1/images/', 'bucket1/videos/']

Notice that you must write the end slash (/) to inform partitioner you are providing an object prefix.

- Input data is a list of object keys. See an example in [map_reduce_cos_key.py](../../examples/map_reduce_cos_key.py):

.. code:: python

    iterdata = ['bucket1/object1', 'bucket1/object2', 'bucket1/object3']

Notice that *iterdata* must be only one of the previous 3 types. Intermingled types are not allowed. For example, you cannot set in the same *iterdata* a bucket and some object keys:

.. code:: python

    iterdata = ['bucket1', 'bucket1/object2', 'bucket1/object3']  # Not allowed

Once iterdata is defined, you can execute Lithops as usual, either using *map()* or *map_reduce()* calls. If you need to split the files in smaller chunks, you can set (optionally) the *obj_chunk_size* or *obj_chunk_number* parameters.

.. code:: python

    import lithops

    object_chunksize = 4*1024**2  # 4MB

    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, obj_chunk_size=object_chunksize)
    result = fexec.get_result()

Processing data from public URLs
--------------------------------
For processing data from public URLs, the input data must be either a single URL or a list of URLs. As in the previous case, if you set the *size of the chunk* or the *number of chunks*, the partitioner is activated inside Lithops and it is responsible to split the objects into smaller chunks, as long as the remote storage server allows requests in chunks (ranges). If range requests are not allowed in the remote storage server, each URL is treated as a single object.

The **obj** parameter is a python class from where you can access all the information related to the object (or chunk) that the function is processing. For example, consider the following function that shows all the available attributes in **obj** when you are processing URLs:


.. code:: python

    import lithops

    def my_map_function(obj):
        print(obj.url)
        print(obj.part)
        print(obj.data_byte_range)
        print(obj.chunk_size)

        data = obj.data_stream.read()

        for line in data.splitlines():
            # Do some process
        return partial_intersting_data

    def my_reduce_function(results):
        for partial_intersting_data in results:
            # Do some process
        return final_result

    iterdata = ['http://myurl/my_file_1.csv', 'http://myurl/my_file_2.csv']
    object_chunk_number= 2

    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function,
                     obj_chunk_number=object_chunk_number)
    result = fexec.get_result()

See a complete example in `map_reduce_url.py <https://github.com/lithops-cloud/lithops/blob/master/examples/map_reduce_url.py>`_


Processing data from localhost files
------------------------------------

.. note:: This is only allowed when running Lithops with the localhost backend

For processing data from localhost files, the input data must be either a directory path, a list of directory paths, a file path a list of file paths. As in the previous cases, if you set the *size of the chunk* or the *number of chunks*, the partitioner is activated inside Lithops and it is responsible to split the objects into smaller chunks, eventually spawning one function for each generated chunk. If *size of the chunk* and *number of chunks* are not set, chunk is an entire object, so one function activation is executed for each individual object.

The **obj** parameter is a python class from where you can access all the information related to the object (or chunk) that the function is processing. For example, consider the following function that shows all the available attributes in **obj** when you are processing localhost files:

.. code:: python

    import lithops

    def my_map_function(obj):
        print(obj.path)
        print(obj.part)
        print(obj.data_byte_range)
        print(obj.chunk_size)

        data = obj.data_stream.read()

        for line in data.splitlines():
            # Do some process
        return partial_intersting_data

    def my_reduce_function(results):
        for partial_intersting_data in results:
            # Do some process
        return final_result

    iterdata = ['/home/user/data/my_file_1.csv', '/home/user/data/my_file_2.csv']
    object_chunk_number= 2

    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function,
                     obj_chunk_number=object_chunk_number)
    result = fexec.get_result()

See a complete example in `map_reduce_localhost.py <https://github.com/lithops-cloud/lithops/blob/master/examples/map_reduce_localhost.py>`_.


Reducer granularity
-------------------
When using the ``map_reduce()`` API call with ``obj_chunk_size`` or ``obj_chunk_number``, by default there will be only one reducer for all the object chunks from all the objects. Alternatively, you can spawn one reducer for each object by setting the parameter ``obj_reduce_by_key=True``.

.. code:: python

    fexec.map_reduce(my_map_function, bucket_name, my_reduce_function,
                     obj_chunk_size=obj_chunk_size, obj_reduce_by_key=True)
