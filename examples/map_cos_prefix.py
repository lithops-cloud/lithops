"""
Simple Lithops example using the map method which runs a wordcount
over all the objects inside the 'bucketname' COS bucket independently.

This example processes some objects from COS. Be sure you have
a bucket with some data objects in your COS account. Then change
the value of the 'bucketname' variable to point to your bucket.

As in this case you are processing objects from COS, the map() method
will first discover objects inside the buckets. Then, it will launch
one map function for each object. So In this case you will get one
result from the each object in the bucket.

In the reduce function there will be always one parameter
from where you can access to the partial results.
"""

import lithops

# Bucket with prefix
data_location = 'cos://lithops-sample-data/test/'  # Change-me


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


if __name__ == "__main__":
    fexec = lithops.FunctionExecutor(log_level='DEBUG')
    fexec.map(my_map_function, data_location)
    print(fexec.get_result())
