.. _data-processing:

Processing Data from the Cloud
==============================

Lithops provides built-in support for reading and processing data from **object storage**, **public URLs**, and **local files**. This functionality is automatically enabled when your function includes a reserved parameter named **obj**.

When you define a function with the parameter `obj`, Lithops knows to pass in a special object representing a file (or a chunk of a file) from an external data source. This allows you to write scalable data processing workflows with minimal boilerplate.

Data Partitioning
-----------------

Lithops includes an integrated **data partitioner** that allows you to automatically split large datasets into smaller, more manageable chunks. This partitioning enables massive parallelism across the compute backend, accelerating data processing tasks.

Partitioning is supported directly within the :meth:`map()` and :meth:`map_reduce()` APIs and can be controlled via:

- **`obj_chunk_size`**: The size (in bytes) of each chunk to split the object into.
- **`obj_chunk_number`**: The total number of chunks to split each object into.

Currently, the partitioner supports **text-based files** where rows are separated by newline characters (`\n`), such as `.txt` and `.csv`. Support for additional data types is planned in future releases.

Cloud Object Storage Integration
--------------------------------

When processing data from cloud object storage, your input must be one of the following:

1. A single bucket or a list of buckets  
2. A bucket prefix (e.g., a folder path)  
3. A list of specific object keys

Based on your configuration:

- If `obj_chunk_size` or `obj_chunk_number` is set, **each object is automatically split into smaller chunks**, and Lithops runs one function activation per chunk.
- If chunking is not configured, Lithops runs one function activation per full object.

Accessing Object Metadata
--------------------------

Inside your function, the `obj` parameter gives you access to metadata and data for the current chunk being processed.

Example:

.. code-block:: python

    def my_map_function(obj):
        print(obj.bucket)             # Bucket name
        print(obj.key)                # Object key
        print(obj.part)               # Chunk number
        print(obj.data_byte_range)    # Byte range for this chunk
        print(obj.chunk_size)         # Chunk size in bytes
        
        data = obj.data_stream.read() # Read the data for this chunk

Accepted Input Formats
-----------------------

Lithops accepts **only one type** of input format per execution. Do not mix formats in the same list. The supported formats are:

- **Buckets**: One or more buckets  
  *(See: `map_reduce_cos_bucket.py <../../examples/map_reduce_cos_bucket.py>`_)*

  .. code-block:: python

      iterdata = ['my-bucket-1', 'my-bucket-2']

- **Object Prefixes**: Folder-like paths ending with `/`  
  *(See: `map_cos_prefix.py <../../examples/map_cos_prefix.py>`_)*

  .. code-block:: python

      iterdata = ['my-bucket/data/csvs/', 'my-bucket/logs/']

  ⚠️ Prefixes must end with a `/` to indicate to the partitioner that you're specifying a folder-like path.

- **Object Keys**: Specific file paths  
  *(See: `map_reduce_cos_key.py <../../examples/map_reduce_cos_key.py>`_)*

  .. code-block:: python

      iterdata = ['my-bucket/file1.csv', 'my-bucket/file2.csv']

❌ **Mixing formats is not allowed**:

.. code-block:: python

    # This will raise an error
    iterdata = ['my-bucket', 'my-bucket/file2.csv']

Putting It All Together
------------------------

Once you've defined your input and function, you can run Lithops as usual with optional chunking:

.. code-block:: python

    import lithops

    object_chunksize = 4 * 1024 ** 2  # 4 MB per chunk

    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, obj_chunk_size=object_chunksize)
    result = fexec.get_result()


Processing Data from Public URLs
================================

Lithops also supports processing data directly from **public URLs**. The input can be a single URL or a list of URLs.

If you set the `obj_chunk_size` or `obj_chunk_number`, Lithops activates its internal partitioner to split each file into smaller chunks—**provided that the remote server supports HTTP range requests**. If range requests are not supported, each URL is processed as a single object.

As with other backends, the special **`obj`** parameter gives you access to metadata and the content of the chunk being processed.

Example:

.. code-block:: python

    import lithops

    def my_map_function(obj):
        print(obj.url)               # Full URL of the object
        print(obj.part)              # Chunk number
        print(obj.data_byte_range)   # Byte range for this chunk
        print(obj.chunk_size)        # Size of this chunk (in bytes)

        data = obj.data_stream.read()

        for line in data.splitlines():
            # Process each line
            pass

        return partial_result

    def my_reduce_function(results):
        for partial_result in results:
            # Aggregate results
            pass

        return final_result

    iterdata = ['http://example.com/file1.csv', 'http://example.com/file2.csv']
    chunk_number = 2

    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function,
                     obj_chunk_number=chunk_number)
    result = fexec.get_result()

📄 See the full example in:  
`map_reduce_url.py <https://github.com/lithops-cloud/lithops/blob/master/examples/map_reduce_url.py>`_


Processing Data from Localhost Files
====================================

.. note:: This feature is only available when using the **localhost backend**.

Lithops can also process files stored on the local filesystem. The input can be:

- A single file path
- A list of file paths
- A directory path
- A list of directory paths

As in other cases, if you set `obj_chunk_size` or `obj_chunk_number`, the file(s) will be split into chunks and processed in parallel. If not set, each file is processed as a single object.

The **`obj`** parameter again exposes the metadata and content of the chunk.

Example:

.. code-block:: python

    import lithops

    def my_map_function(obj):
        print(obj.path)              # Full local file path
        print(obj.part)              # Chunk number
        print(obj.data_byte_range)   # Byte range for this chunk
        print(obj.chunk_size)        # Size of this chunk (in bytes)

        data = obj.data_stream.read()

        for line in data.splitlines():
            # Process each line
            pass

        return partial_result

    def my_reduce_function(results):
        for partial_result in results:
            # Aggregate results
            pass

        return final_result

    iterdata = ['/home/user/file1.csv', '/home/user/file2.csv']
    chunk_number = 2

    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function,
                     obj_chunk_number=chunk_number)
    result = fexec.get_result()

📄 See the full example in:  
`map_reduce_localhost.py <https://github.com/lithops-cloud/lithops/blob/master/examples/map_reduce_localhost.py>`_


Reducer Granularity
-------------------

When using the :meth:`map_reduce()` API along with `obj_chunk_size` or `obj_chunk_number`, Lithops defaults to using **a single reducer** to aggregate results across **all chunks and objects**.

If you'd prefer to reduce results **per original object** (e.g., one reducer per file), you can set the parameter `obj_reduce_by_key=True`.

Example:

.. code-block:: python

    fexec.map_reduce(my_map_function, bucket_name, my_reduce_function,
                     obj_chunk_size=obj_chunk_size,
                     obj_reduce_by_key=True)


Elastic Data Processing and Cloud-Optimized Formats
===================================================

Lithops is especially powerful for **massively parallel data processing**. When the input to `map()` or `map_reduce()` is a **storage bucket** or a collection of large files, Lithops will automatically:

- Launch one function per file, or  
- Partition large files into chunks and assign each chunk to a different function  

This behavior enables **elastic scaling** that fully utilizes the underlying compute backend.

Cloud-Optimized Formats
------------------------

Lithops is ideally suited for processing **cloud-optimized data formats** such as:

- **ZARR**
- **COG** (Cloud Optimized GeoTIFF)
- **COPC** (Cloud Optimized Point Clouds)
- **FlatGeoBuf**

These formats are designed to support **random access via HTTP range requests**, making them a perfect match for cloud object storage and serverless computing.

By leveraging HTTP range primitives, Lithops enables fast and scalable parallel processing — distributing workload across many concurrent function activations, each fetching only the data it needs. This approach takes full advantage of the **high aggregate bandwidth** provided by modern object storage systems.

Partitioning Non-Optimized Formats with Dataplug
-------------------------------------------------

Thanks to the `DATAPLUG <https://github.com/CLOUDLAB-URV/dataplug>`_ library, Lithops also supports **on-the-fly partitioning** of data formats that are **not cloud-optimized**. Supported formats include:

- Genomics: **FASTA**, **FASTQ**, **FASTQ.GZ**
- Metabolomics: **mlMZ**
- Geospatial: **LIDAR (.laz)**

Dataplug wraps these formats into cloud-native interfaces and exposes partitioning strategies that Lithops can consume directly.

Example: Parallel Processing of a Cloud-Hosted LIDAR File
----------------------------------------------------------

In the example below, we use Dataplug to wrap a COPC (Cloud Optimized Point Cloud) file stored in S3, partition it into spatial chunks, and process each chunk in parallel using Lithops:

.. code-block:: python

    from dataplug import CloudObject
    from dataplug.formats.geospatial.copc import CloudOptimizedPointCloud, square_split_strategy
    import laspy
    import lithops

    # Function to process each LiDAR slice
    def process_lidar_slice(data_slice):
        las_data = data_slice.get()
        lidar_file = laspy.open(las_data)
        ...
    
    # Load the COPC file from S3 using Dataplug
    co = CloudObject.from_s3(
        CloudOptimizedPointCloud,
        "s3://geospatial/copc/CA_YosemiteNP_2019/USGS_LPC_CA_YosemiteNP_2019_D19_11SKB6892.laz",
        s3_config=local_minio,
    )

    # Partition the point cloud into 9 spatial chunks
    slices = co.partition(square_split_strategy, num_chunks=9)

    # Process slices in parallel using Lithops
    with lithops.FunctionExecutor() as executor:
        futures = executor.map(process_lidar_slice, slices)
        results = executor.get_result(futures)

This enables truly **elastic and serverless geospatial processing pipelines**, with no infrastructure overhead and full cloud-native efficiency.
