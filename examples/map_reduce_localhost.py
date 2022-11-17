"""
Simple Lithops example using the map_reduce method which
counts the number of words inside each object specified
in 'iterdata' variable.

This example processes some objects which are in a localhost path.

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

import os
import lithops
import requests
from urllib.parse import urlparse

# Dataset from: https://archive.ics.uci.edu/ml/datasets/bag+of+words
DATA_URLS = ['https://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.enron.txt',
             'https://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.kos.txt',
             'https://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nips.txt',
             'https://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nytimes.txt',
             'https://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.pubmed.txt']


def my_map_function(obj):
    print(f'I am processing the object from {obj.path}')
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
    iterdata = []

    for url in DATA_URLS:
        print('Downloading data from {}'.format(url))
        a = urlparse(url)
        file_path = '/tmp/{}'.format(os.path.basename(a.path))
        iterdata.append(file_path)
        if not os.path.isfile(file_path):
            r = requests.get(url, allow_redirects=True)
            open(file_path, 'wb').write(r.content)

    fexec = lithops.FunctionExecutor(backend='localhost', storage='localhost', log_level='DEBUG')
    fexec.map_reduce(my_map_function, iterdata, my_reduce_function, obj_chunk_number=2)
    result = fexec.get_result()
    print("Done!")
