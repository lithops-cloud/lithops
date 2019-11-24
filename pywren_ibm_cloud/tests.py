#
# (C) Copyright IBM Corp. 2019
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import sys
import json
import argparse
import unittest
import pywren_ibm_cloud as pywren
import urllib.request
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.config import default_config, extract_storage_config
from multiprocessing.pool import ThreadPool

import logging
# logging.basicConfig(level=logging.DEBUG)

parser = argparse.ArgumentParser(description="test all PyWren's functionality", usage='python -m pywren_ibm_cloud.tests [-c CONFIG] [-f TESTNAME]')
parser.add_argument('-c', '--config', type=argparse.FileType('r'), metavar='', default=None, help="use json config file")
parser.add_argument('-t', '--test', metavar='', default='all', help='run a specific test, type "-t help" for tests list')
args = parser.parse_args()

CONFIG = default_config()
STORAGE_CONFIG = extract_storage_config(CONFIG)
STORAGE = InternalStorage(STORAGE_CONFIG).storage_handler
PREFIX = '__pywren.test'
TEST_FILES_URLS = ["http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.enron.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.kos.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nips.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nytimes.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.pubmed.txt"]


def initTests():
    print('Uploading test files...')

    def up(param):
        i, url = param
        content = urllib.request.urlopen(url).read()
        STORAGE.put_object(bucket_name=STORAGE_CONFIG['bucket'],
                           key='{}/test{}'.format(PREFIX, str(i)),
                           data=content)
        return len(content.split())

    pool = ThreadPool(128)
    results = pool.map(up, enumerate(TEST_FILES_URLS))
    pool.close()
    pool.join()
    result_to_compare = 1 + sum(results)  # including result's word

    STORAGE.put_object(bucket_name=STORAGE_CONFIG['bucket'],
                       key='{}/result'.format(PREFIX),
                       data=str(result_to_compare).encode())


def list_test_keys():
    return STORAGE.list_keys(bucket_name=STORAGE_CONFIG['bucket'], prefix=PREFIX)


def cleanTests():
    print('Deleting test files...')
    for key in list_test_keys():
        STORAGE.delete_object(bucket_name=STORAGE_CONFIG['bucket'],
                              key=key)


def hello_world(param):
    return "Hello World!"


def simple_map_function(x, y):
    return x + y


def simple_reduce_function(results):
    total = 0
    for map_result in results:
        total = total + map_result
    return total


def pywren_inside_pywren_map_function1(x):
    def _func(x):
        return x

    pw = pywren.function_executor(config=CONFIG)
    pw.map(_func, range(x))
    return pw.get_result()


def pywren_inside_pywren_map_function2(x):
    def _func(x):
        return x

    pw = pywren.function_executor(config=CONFIG)
    pw.call_async(_func, x)
    return pw.get_result()


def pywren_inside_pywren_map_function3(x):
    def _func(x):
        return x

    pw = pywren.function_executor(config=CONFIG)
    fut1 = pw.map(_func, range(x))
    fut2 = pw.map(_func, range(x))
    return [pw.get_result(fut1), pw.get_result(fut2)]


def my_map_function_obj(obj):
    print('I am processing the object /{}/{}'.format(obj.bucket, obj.key))
    counter = {}

    data = obj.data_stream.read()

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1

    return counter


def my_map_function_url(url):
    print('I am processing the object from {}'.format(url.path))
    counter = {}

    data = url.data_stream.read()

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1

    return counter


def my_map_function_ibm_cos(key_i, bucket_name, ibm_cos):
    print('I am processing the object /{}/{}'.format(bucket_name, key_i))
    counter = {}

    data = ibm_cos.get_object(Bucket=bucket_name, Key=key_i)['Body'].read()

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1

    return counter


def my_reduce_function(results):
    final_result = 0

    for count in results:
        for word in count:
            final_result += count[word]

    return final_result


def my_cloudobject_put(obj, internal_storage):
    counter = my_map_function_obj(obj)
    cloudobject = internal_storage.put_object(counter)
    return cloudobject


def my_cloudobject_get(results, internal_storage):
    data = [internal_storage.get_object(cloudobject) for cloudobject in results]
    return my_reduce_function(data)


class TestPywren(unittest.TestCase):

    def checkResult(self, result):
        result_to_compare = STORAGE.get_object(bucket_name=STORAGE_CONFIG['bucket'],
                                               key=f'{PREFIX}/result')

        if isinstance(result, list):
            total = 0
            for r in result:
                total += r
        else:
            total = result

        self.assertEqual(total, int(result_to_compare))

    def test_call_async(self):
        print('Testing call_async()...')
        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(hello_world, "")
        result = pw.get_result()
        self.assertEqual(result, "Hello World!")

        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(simple_map_function, [4, 6])
        result = pw.get_result()
        self.assertEqual(result, 10)

        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(simple_map_function, {'x': 2, 'y': 8})
        result = pw.get_result()
        self.assertEqual(result, 10)

    def test_map(self):
        print('Testing map()...')
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = pywren.function_executor(config=CONFIG)
        pw.map(simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

    def test_map_reduce(self):
        print('Testing map_reduce()...')
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(simple_map_function, iterdata, simple_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, 20)

    def test_multiple_executions(self):
        print('Testing multiple executions...')
        pw = pywren.function_executor(config=CONFIG)
        iterdata = [[1, 1], [2, 2]]
        pw.map(simple_map_function, iterdata)
        iterdata = [[3, 3], [4, 4]]
        pw.map(simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        iterdata = [[1, 1], [2, 2]]
        pw.map(simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4])

        iterdata = [[1, 1], [2, 2]]
        futures1 = pw.map(simple_map_function, iterdata)
        result1 = pw.get_result(fs=futures1)
        iterdata = [[3, 3], [4, 4]]
        futures2 = pw.map(simple_map_function, iterdata)
        result2 = pw.get_result(fs=futures2)
        self.assertEqual(result1, [2, 4])
        self.assertEqual(result2, [6, 8])

    def test_internal_executions(self):
        print('Testing internal executions...')
        pw = pywren.function_executor(config=CONFIG)
        pw.map(pywren_inside_pywren_map_function1, range(1, 11))
        result = pw.get_result()
        self.assertEqual(result, [0] + [list(range(i)) for i in range(2, 11)])

        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(pywren_inside_pywren_map_function2, 10)
        result = pw.get_result()
        self.assertEqual(result, 10)

        pw = pywren.function_executor(config=CONFIG)
        pw.map(pywren_inside_pywren_map_function3, range(1, 11))
        result = pw.get_result()
        self.assertEqual(result, [[0, 0]] + [[list(range(i)), list(range(i))] for i in range(2, 11)])

    def test_map_reduce_cos_bucket(self):
        print('Testing map_reduce() over a COS bucket...')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb+'://'+STORAGE_CONFIG['bucket']+'/'+PREFIX+'/'
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(my_map_function_obj, data_prefix, my_reduce_function)
        result = pw.get_result()
        self.checkResult(result)

    def test_map_reduce_cos_bucket_one_reducer_per_object(self):
        print('Testing map_reduce() over a COS bucket with one reducer per object...')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb+'://'+STORAGE_CONFIG['bucket']+'/'+PREFIX+'/'
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(my_map_function_obj, data_prefix, my_reduce_function, reducer_one_per_object=True)
        result = pw.get_result()
        self.checkResult(result)

    def test_map_reduce_cos_key(self):
        print('Testing map_reduce() over COS keys...')
        sb = STORAGE_CONFIG['backend']
        bucket_name = STORAGE_CONFIG['bucket']
        iterdata = [sb+'://'+bucket_name+'/'+key for key in list_test_keys()]
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(my_map_function_obj, iterdata, my_reduce_function)
        result = pw.get_result()
        self.checkResult(result)

    def test_map_reduce_cos_key_one_reducer_per_object(self):
        print('Testing map_reduce() over COS keys with one reducer per object...')
        sb = STORAGE_CONFIG['backend']
        bucket_name = STORAGE_CONFIG['bucket']
        iterdata = [sb+'://'+bucket_name+'/'+key for key in list_test_keys()]
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(my_map_function_obj, iterdata, my_reduce_function, reducer_one_per_object=True)
        result = pw.get_result()
        self.checkResult(result)

    def test_map_reduce_url(self):
        print('Testing map_reduce() over URLs...')
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(my_map_function_url, TEST_FILES_URLS, my_reduce_function)
        result = pw.get_result()
        self.checkResult(result + 1)

    def test_storage_handler(self):
        print('Testing ibm_cos function arg...')
        iterdata = [[key, STORAGE_CONFIG['bucket']] for key in list_test_keys()]
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(my_map_function_ibm_cos, iterdata, my_reduce_function)
        result = pw.get_result()
        self.checkResult(result)

    def test_chunks_bucket(self):
        print('Testing cunk_size on a bucket...')
        data_prefix = STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(my_map_function_obj, data_prefix, my_reduce_function, chunk_size=1*1024**2)
        result = pw.get_result()
        self.checkResult(result)

    def test_chunks_bucket_one_reducer_per_object(self):
        print('Testing cunk_size on a bucket with one reducer per object...')
        data_prefix = STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(my_map_function_obj, data_prefix, my_reduce_function, chunk_size=1*1024**2,
                      reducer_one_per_object=True)
        result = pw.get_result()
        self.checkResult(result)

    def test_cloudobject(self):
        print('Testing cloudobjects...')
        data_prefix = STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(my_cloudobject_put, data_prefix, my_cloudobject_get)
        result = pw.get_result()
        self.checkResult(result)


if __name__ == '__main__':

    if args.test == 'help':
        print("available test functions:")
        print("-> test_call_async")
        print("-> test_map")
        print("-> test_map_reduce")
        print("-> test_multiple_executions")
        print("-> test_internal_executions")
        print("-> test_map_reduce_cos_bucket")
        print("-> test_map_reduce_cos_bucket_one_reducer_per_object")
        print("-> test_map_reduce_cos_key")
        print("-> test_map_reduce_cos_key_one_reducer_per_object")
        print("-> test_map_reduce_url")
        print("-> test_storage_handler")
        print("-> test_chunks_bucket")
        print("-> test_chunks_bucket_one_reducer_per_object")
        print("-> test_cloudobject")

    else:
        suite = unittest.TestSuite()
        if args.test == 'all':
            suite.addTest(unittest.makeSuite(TestPywren))
        else:
            try:
                suite.addTest(TestPywren(args.test))
            except ValueError:
                print("unknown test, use: --help")
                sys.exit()

        if args.config:
            args.config = json.load(args.config)

        initTests()
        runner = unittest.TextTestRunner()
        runner.run(suite)
        cleanTests()
