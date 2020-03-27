#
# (C) Copyright IBM Corp. 2020
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
import pickle
import argparse
import unittest
import logging
import inspect
import pywren_ibm_cloud as pywren
import urllib.request
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.config import default_config, extract_storage_config
from concurrent.futures import ThreadPoolExecutor

# logging.basicConfig(level=logging.DEBUG)

CONFIG = None
STORAGE_CONFIG = None
STORAGE = None

PREFIX = '__pywren.test'
TEST_FILES_URLS = ["http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.enron.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.kos.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nips.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nytimes.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.pubmed.txt"]


class TestUtils:

    @staticmethod
    def initTests():
        def up(param):
            i, url = param
            content = urllib.request.urlopen(url).read()
            STORAGE.put_object(bucket_name=STORAGE_CONFIG['bucket'],
                               key='{}/test{}'.format(PREFIX, str(i)),
                               data=content)
            return len(content.split())

        with ThreadPoolExecutor() as pool:
            results = list(pool.map(up, enumerate(TEST_FILES_URLS)))

        result_to_compare = sum(results)
        return result_to_compare

    @staticmethod
    def list_test_keys():
        return STORAGE.list_keys(bucket_name=STORAGE_CONFIG['bucket'], prefix=PREFIX + '/')

    @staticmethod
    def cleanTests():
        for key in TestUtils.list_test_keys():
            STORAGE.delete_object(bucket_name=STORAGE_CONFIG['bucket'],
                                  key=key)


class TestMethods:

    @staticmethod
    def hello_world(param):
        return "Hello World!"

    @staticmethod
    def simple_map_function(x, y):
        return x + y

    @staticmethod
    def simple_reduce_function(results):
        total = 0
        for map_result in results:
            total = total + map_result
        return total

    @staticmethod
    def pywren_inside_pywren_map_function(x):
        def _func(x):
            return x

        pw = pywren.function_executor()
        pw.map(_func, range(x))
        return pw.get_result()

    @staticmethod
    def pywren_return_futures_map_function1(x):
        def _func(x):
            return x + 1

        pw = pywren.ibm_cf_executor()
        return pw.map(_func, range(x))

    @staticmethod
    def pywren_return_futures_map_function2(x):
        def _func(x):
            return x + 1

        pw = pywren.ibm_cf_executor()
        return pw.call_async(_func, x + 5)

    @staticmethod
    def pywren_return_futures_map_function3(x):
        def _func(x):
            return x + 1

        pw = pywren.ibm_cf_executor()
        fut1 = pw.map(_func, range(x))
        fut2 = pw.map(_func, range(x))
        return fut1 + fut2

    @staticmethod
    def my_map_function_obj(obj, id):
        print('Bucket: {}'.format(obj.bucket))
        print('Key: {}'.format(obj.key))
        print('Partition num: {}'.format(obj.part))
        print('Action id: {}'.format(id))
        counter = {}
        data = obj.data_stream.read()
        for line in data.splitlines():
            for word in line.decode('utf-8').split():
                if word not in counter:
                    counter[word] = 1
                else:
                    counter[word] += 1
        return counter

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def my_reduce_function(results):
        final_result = 0
        for count in results:
            for word in count:
                final_result += count[word]
        return final_result

    @staticmethod
    def my_cloudobject_put(obj, internal_storage):
        counter = TestMethods.my_map_function_obj(obj, 0)
        cloudobject = internal_storage.put_object(pickle.dumps(counter))
        return cloudobject

    @staticmethod
    def my_cloudobject_get(results, internal_storage):
        data = [pickle.loads(internal_storage.get_object(cloudobject)) for cloudobject in results]
        return TestMethods.my_reduce_function(data)


class TestPywren(unittest.TestCase):
    cos_result_to_compare = None

    @classmethod
    def setUpClass(cls):
        print('Uploading test files...')
        cls.cos_result_to_compare = TestUtils.initTests()

    @classmethod
    def tearDownClass(cls):
        print('Deleting test files...')
        TestUtils.cleanTests()

    def test_call_async(self):
        print('Testing call_async()...')
        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(TestMethods.hello_world, "")
        result = pw.get_result()
        self.assertEqual(result, "Hello World!")

        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(TestMethods.simple_map_function, [4, 6])
        result = pw.get_result()
        self.assertEqual(result, 10)

        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(TestMethods.simple_map_function, {'x': 2, 'y': 8})
        result = pw.get_result()
        self.assertEqual(result, 10)

    def test_map(self):
        print('Testing map()...')
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = pywren.function_executor(config=CONFIG)
        pw.map(TestMethods.simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        pw = pywren.function_executor(config=CONFIG, workers=1)
        pw.map(TestMethods.simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        pw = pywren.function_executor(config=CONFIG)
        set_iterdata = set(range(2))
        pw.map(TestMethods.hello_world, set_iterdata)
        result = pw.get_result()
        self.assertEqual(result, ['Hello World!'] * 2)

        pw = pywren.function_executor(config=CONFIG)
        generator_iterdata = range(2)
        pw.map(TestMethods.hello_world, generator_iterdata)
        result = pw.get_result()
        self.assertEqual(result, ['Hello World!'] * 2)

        pw = pywren.function_executor(config=CONFIG)
        listDicts_iterdata = [{'x': 2, 'y': 8}, {'x': 2, 'y': 8}]
        pw.map(TestMethods.simple_map_function, listDicts_iterdata)
        result = pw.get_result()
        self.assertEqual(result, [10, 10])

    def test_map_reduce(self):
        print('Testing map_reduce()...')
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.simple_map_function, iterdata, TestMethods.simple_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, 20)

    def test_multiple_executions(self):
        print('Testing multiple executions...')
        pw = pywren.function_executor(config=CONFIG)
        iterdata = [[1, 1], [2, 2]]
        pw.map(TestMethods.simple_map_function, iterdata)
        iterdata = [[3, 3], [4, 4]]
        pw.map(TestMethods.simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        iterdata = [[1, 1], [2, 2]]
        pw.map(TestMethods.simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4])

        iterdata = [[1, 1], [2, 2]]
        futures1 = pw.map(TestMethods.simple_map_function, iterdata)
        result1 = pw.get_result(fs=futures1)
        iterdata = [[3, 3], [4, 4]]
        futures2 = pw.map(TestMethods.simple_map_function, iterdata)
        result2 = pw.get_result(fs=futures2)
        self.assertEqual(result1, [2, 4])
        self.assertEqual(result2, [6, 8])

    def test_internal_executions(self):
        print('Testing internal executions...')
        pw = pywren.function_executor(config=CONFIG)
        pw.map(TestMethods.pywren_inside_pywren_map_function, range(1, 11))
        result = pw.get_result()
        self.assertEqual(result, [list(range(i)) for i in range(1, 11)])

        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(TestMethods.pywren_return_futures_map_function1, 3)
        pw.get_result()

        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(TestMethods.pywren_return_futures_map_function2, 3)
        pw.get_result()

        pw = pywren.function_executor(config=CONFIG)
        pw.call_async(TestMethods.pywren_return_futures_map_function3, 3)
        pw.get_result()

    def test_map_reduce_cos_bucket(self):
        print('Testing map_reduce() over a COS bucket...')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_map_reduce_cos_bucket_one_reducer_per_object(self):
        print('Testing map_reduce() over a COS bucket with one reducer per object...')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function,
                      reducer_one_per_object=True)
        result = pw.get_result()
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)

    def test_map_reduce_cos_key(self):
        print('Testing map_reduce() over COS keys...')
        sb = STORAGE_CONFIG['backend']
        bucket_name = STORAGE_CONFIG['bucket']
        iterdata = [sb + '://' + bucket_name + '/' + key for key in TestUtils.list_test_keys()]
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_obj, iterdata, TestMethods.my_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_map_reduce_cos_key_one_reducer_per_object(self):
        print('Testing map_reduce() over COS keys with one reducer per object...')
        sb = STORAGE_CONFIG['backend']
        bucket_name = STORAGE_CONFIG['bucket']
        iterdata = [sb + '://' + bucket_name + '/' + key for key in TestUtils.list_test_keys()]
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_obj, iterdata, TestMethods.my_reduce_function,
                      reducer_one_per_object=True)
        result = pw.get_result()
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)

    def test_map_reduce_url(self):
        print('Testing map_reduce() over URLs...')
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_url, TEST_FILES_URLS, TestMethods.my_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_storage_handler(self):
        print('Testing ibm_cos function arg...')
        iterdata = [[key, STORAGE_CONFIG['bucket']] for key in TestUtils.list_test_keys()]
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_ibm_cos, iterdata, TestMethods.my_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_chunks_bucket(self):
        print('Testing chunks on a bucket...')
        data_prefix = STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'

        pw = pywren.function_executor(config=CONFIG)
        futures = pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function,
                                chunk_size=1 * 1024 ** 2)
        result = pw.get_result(futures)
        self.assertEqual(result, self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 8)

        pw = pywren.function_executor(config=CONFIG)
        futures = pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function, chunk_n=2)
        result = pw.get_result(futures)
        self.assertEqual(result, self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 11)

    def test_chunks_bucket_one_reducer_per_object(self):
        print('Testing chunks on a bucket with one reducer per object...')
        data_prefix = STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'

        pw = pywren.function_executor(config=CONFIG)
        futures = pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function,
                                chunk_size=1 * 1024 ** 2, reducer_one_per_object=True)
        result = pw.get_result(futures)
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 12)

        pw = pywren.function_executor(config=CONFIG)
        futures = pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function, chunk_n=2,
                                reducer_one_per_object=True)
        result = pw.get_result(futures)
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 15)

    def test_cloudobject(self):
        print('Testing cloudobjects...')
        data_prefix = STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        pw = pywren.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_cloudobject_put, data_prefix, TestMethods.my_cloudobject_get)
        result = pw.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)


def print_help():
    print("available test functions:")
    func_names = filter(lambda s: s[:4] == 'test',
                        map(lambda t: t[0], inspect.getmembers(TestPywren(), inspect.ismethod)))
    for func_name in func_names:
        print(f'-> {func_name}')


def run_tests(test_to_run, config=None):
    global CONFIG, STORAGE_CONFIG, STORAGE

    CONFIG = json.load(args.config) if config else default_config()
    STORAGE_CONFIG = extract_storage_config(CONFIG)
    STORAGE = InternalStorage(STORAGE_CONFIG).storage_handler

    suite = unittest.TestSuite()
    if test_to_run == 'all':
        suite.addTest(unittest.makeSuite(TestPywren))
    else:
        try:
            suite.addTest(TestPywren(test_to_run))
        except ValueError:
            print("unknown test, use: --help")
            sys.exit()

    runner = unittest.TextTestRunner()
    runner.run(suite)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="test all PyWren's functionality",
                                     usage='python -m pywren_ibm_cloud.tests [-c CONFIG] [-t TESTNAME]')
    parser.add_argument('-c', '--config', type=argparse.FileType('r'), metavar='', default=None,
                        help="use json config file")
    parser.add_argument('-t', '--test', metavar='', default='all',
                        help='run a specific test, type "-t help" for tests list')
    args = parser.parse_args()

    if args.test == 'help':
        print_help()
    else:
        run_tests(args.test, args.config)
