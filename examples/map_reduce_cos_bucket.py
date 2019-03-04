"""
Simple PyWren example using the map_reduce method which
runs a wordcount over all the objects inside the 'bucketname'
COS bucket.

This example processes some objects from COS. Be sure you have
a bucket with some data objects in your COS account. Then change
the value of the 'bucketname' variable to point to your bucket.

As in this case you are processing objects from COS, the
map_reduce() method will first launch a partitioner to split
the objects in smaller chunks, thus increasing the parallelism
of the execution and reducing the total time needed to process
the data. After creating the partitions, it will launch one
map function for each partition. To finish one reducer will be
launched for all the objects in the Bucket. So In this case you
will get just one result from the reduce method.

Note that when you want to process objects stored in COS by
using a 'bucketname', the 'bucket', 'key' and 'data_stream'
parameters are mandatory in the parameters of the map function.

In the reduce function there will be always one parameter
from where you can access to the partial results.
"""

import pywren_ibm_cloud as pywren

bucketname = 'pw-sample-data'


def my_map_function(bucket, key, data_stream):
    print('I am processing the object {}/{}'.format(bucket, key))
    counter = {}

    data = data_stream.read()

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1

    return counter


def my_reduce_function(results):
    final_result = {}
    for count in results:
        for word in count:
            if word not in final_result:
                final_result[word] = count[word]
            else:
                final_result[word] += count[word]

    return final_result

chunk_size = 4*1024**2  # 4MB

pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, bucketname, my_reduce_function, chunk_size=chunk_size)
print(pw.get_result())

"""
One reducer for each object in the bucket
"""
print()
print('Testing one reducer per object:')
pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, bucketname, my_reduce_function, chunk_size=chunk_size,
              reducer_one_per_object=True)
print(pw.get_result())
