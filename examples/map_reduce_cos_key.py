"""
Simple Lithops example using the map_reduce method which
counts the number of words inside each object specified
in 'iterdata' variable.

This example processes some objects which are in COS.
Be sure you have a bucket named 'sample_data' and the
objects object1, object2 and object3 inside it.

Otherwise, you can change the 'iterdata' variable and
point to some existing objects in your COS account.

As in this case you are processing objects from COS, the
map_reduce() method will first launch a partitioner to split
the objects in smaller chunks, thus increasing the parallelism
of the execution and reducing the total time needed to process
the data. After creating the partitions, it will launch one
map function for each partition, and one reducer for all
partitions of the same object. In this case you will get
one result for each object specified in 'iterdata' variable.

In the reduce function there will be always one parameter
from where you can access to the partial results.
"""

import lithops

iterdata = ['cos://lithops-sample-data/obj1.txt',
            'cos://lithops-sample-data/obj2.txt',
            'cos://lithops-sample-data/obj3.txt']   # Change-me


def my_map_function(obj):
    print(f'Bucket: {obj.bucket}')
    print(f'Key: {obj.key}')
    print(f'Partition num: {obj.part}')
    counter = {}
    data = obj.data_stream.read()

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


if __name__ == "__main__":
    chunk_size = 4*1024**2  # 4MB

    fexec = lithops.FunctionExecutor(log_level='INFO')
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function, obj_chunk_size=chunk_size)
    print(fexec.get_result())

    """
    With one reducer for each object
    """
    print()
    print('Testing one reducer per object:')
    fexec = lithops.FunctionExecutor()
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function, obj_chunk_size=chunk_size,
                     obj_reduce_by_key=True)
    print(fexec.get_result())
