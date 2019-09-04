"""
Simple PyWren example using the map method which runs a wordcount
over all the objects inside the 'bucketname' COS bucket independently.

This example processes some objects from COS. Be sure you have
a bucket with some data objects in your COS account. Then change
the value of the 'bucketname' variable to point to your bucket.

As in this case you are processing objects from COS, the map() method
will first discover objects inside the buckets. Then, it will launch
one map function for each object. So In this case you will get one
result from the each object in the bucket.

Note that when you want to process objects stored in COS by
using a 'bucketname', the 'bucket', 'key' and 'data_stream'
parameters are mandatory in the parameters of the map function.

In the reduce function there will be always one parameter
from where you can access to the partial results.
"""

import pywren_ibm_cloud as pywren

# Bucket with prefix
bucketname = 'cos://pw-sample-data/test/'  # Change-me


def my_map_function(obj):
    print('Bucket: {}'.format(obj.bucket))
    print('Key: {}'.format(obj.key))
    print('Partition num: {}'.format(obj.part))
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
    pw = pywren.ibm_cf_executor()
    pw.map(my_map_function, bucketname)
    print(pw.get_result())
