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
import lithops
import urllib.request
from lithops.storage import InternalStorage
from lithops.config import default_config, extract_storage_config
from concurrent.futures import ThreadPoolExecutor

CONFIG = None
STORAGE_CONFIG = None
STORAGE = None

PREFIX = '__lithops.test'
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
    def concat(lst):
        return " ".join(lst)

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
    def lithops_inside_lithops_map_function(x):
        def _func(x):
            return x

        pw = lithops.function_executor()
        pw.map(_func, range(x))
        return pw.get_result()

    @staticmethod
    def lithops_return_futures_map_function1(x):
        def _func(x):
            return x + 1

        pw = lithops.function_executor()
        return pw.map(_func, range(x))

    @staticmethod
    def lithops_return_futures_map_function2(x):
        def _func(x):
            return x + 1

        pw = lithops.function_executor()
        return pw.call_async(_func, x + 5)

    @staticmethod
    def lithops_return_futures_map_function3(x):
        def _func(x):
            return x + 1

        pw = lithops.function_executor()
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
    def my_map_function_storage(key_i, bucket_name, storage):
        print('I am processing the object /{}/{}'.format(bucket_name, key_i))
        counter = {}
        data = storage.get_object(bucket_name, key_i)
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
    def my_cloudobject_put(obj, storage):
        counter = TestMethods.my_map_function_obj(obj, 0)
        cloudobject = storage.put_cobject(pickle.dumps(counter))
        return cloudobject

    @staticmethod
    def my_cloudobject_get(results, storage):
        data = [pickle.loads(storage.get_cobject(cloudobject)) for cloudobject in results]
        return TestMethods.my_reduce_function(data)


class TestLithops(unittest.TestCase):
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
        pw = lithops.function_executor(config=CONFIG)
        pw.call_async(TestMethods.hello_world, "")
        result = pw.get_result()
        self.assertEqual(result, "Hello World!")

        pw = lithops.function_executor(config=CONFIG)
        pw.call_async(TestMethods.concat, ["a", "b"])
        result = pw.get_result()
        self.assertEqual(result, "a b")

        pw = lithops.function_executor(config=CONFIG)
        pw.call_async(TestMethods.simple_map_function, [4, 6])
        result = pw.get_result()
        self.assertEqual(result, 10)

        pw = lithops.function_executor(config=CONFIG)
        pw.call_async(TestMethods.simple_map_function, {'x': 2, 'y': 8})
        result = pw.get_result()
        self.assertEqual(result, 10)

    def test_map(self):
        print('Testing map()...')
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = lithops.function_executor(config=CONFIG)
        pw.map(TestMethods.simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        pw = lithops.function_executor(config=CONFIG, workers=1)
        pw.map(TestMethods.simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        pw = lithops.function_executor(config=CONFIG)
        set_iterdata = set(range(2))
        pw.map(TestMethods.hello_world, set_iterdata)
        result = pw.get_result()
        self.assertEqual(result, ['Hello World!'] * 2)

        pw = lithops.function_executor(config=CONFIG)
        generator_iterdata = range(2)
        pw.map(TestMethods.hello_world, generator_iterdata)
        result = pw.get_result()
        self.assertEqual(result, ['Hello World!'] * 2)

        pw = lithops.function_executor(config=CONFIG)
        listDicts_iterdata = [{'x': 2, 'y': 8}, {'x': 2, 'y': 8}]
        pw.map(TestMethods.simple_map_function, listDicts_iterdata)
        result = pw.get_result()
        self.assertEqual(result, [10, 10])

        pw = lithops.function_executor(config=CONFIG)
        set_iterdata = [["a", "b"], ["c", "d"]]
        pw.map(TestMethods.concat, set_iterdata)
        result = pw.get_result()
        self.assertEqual(result, ["a b", "c d"])

    def test_map_reduce(self):
        print('Testing map_reduce()...')
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = lithops.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.simple_map_function, iterdata, TestMethods.simple_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, 20)

    def test_multiple_executions(self):
        print('Testing multiple executions...')
        pw = lithops.function_executor(config=CONFIG)
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
        pw = lithops.function_executor(config=CONFIG)
        pw.map(TestMethods.lithops_inside_lithops_map_function, range(1, 11))
        result = pw.get_result()
        self.assertEqual(result, [list(range(i)) for i in range(1, 11)])

        pw = lithops.function_executor(config=CONFIG)
        pw.call_async(TestMethods.lithops_return_futures_map_function1, 3)
        pw.get_result()

        pw = lithops.function_executor(config=CONFIG)
        pw.call_async(TestMethods.lithops_return_futures_map_function2, 3)
        pw.get_result()

        pw = lithops.function_executor(config=CONFIG)
        pw.call_async(TestMethods.lithops_return_futures_map_function3, 3)
        pw.wait()
        pw.get_result()

    def test_map_reduce_obj_bucket(self):
        print('Testing map_reduce() over a bucket...')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        pw = lithops.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_map_reduce_obj_bucket_one_reducer_per_object(self):
        print('Testing map_reduce() over a bucket with one reducer per object...')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        pw = lithops.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function,
                      reducer_one_per_object=True)
        result = pw.get_result()
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)

    def test_map_reduce_obj_key(self):
        print('Testing map_reduce() over object keys...')
        sb = STORAGE_CONFIG['backend']
        bucket_name = STORAGE_CONFIG['bucket']
        iterdata = [sb + '://' + bucket_name + '/' + key for key in TestUtils.list_test_keys()]
        pw = lithops.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_obj, iterdata, TestMethods.my_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_map_reduce_obj_key_one_reducer_per_object(self):
        print('Testing map_reduce() over object keys with one reducer per object...')
        sb = STORAGE_CONFIG['backend']
        bucket_name = STORAGE_CONFIG['bucket']
        iterdata = [sb + '://' + bucket_name + '/' + key for key in TestUtils.list_test_keys()]
        pw = lithops.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_obj, iterdata, TestMethods.my_reduce_function,
                      reducer_one_per_object=True)
        result = pw.get_result()
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)

    def test_map_reduce_url(self):
        print('Testing map_reduce() over URLs...')
        pw = lithops.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_url, TEST_FILES_URLS, TestMethods.my_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_storage_handler(self):
        print('Testing "storage" function arg...')
        iterdata = [[key, STORAGE_CONFIG['bucket']] for key in TestUtils.list_test_keys()]
        pw = lithops.function_executor(config=CONFIG)
        pw.map_reduce(TestMethods.my_map_function_storage, iterdata, TestMethods.my_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_chunks_bucket(self):
        print('Testing chunks on a bucket...')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'

        pw = lithops.function_executor(config=CONFIG)
        futures = pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function,
                                chunk_size=1 * 1024 ** 2)
        result = pw.get_result(futures)
        self.assertEqual(result, self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 8)

        pw = lithops.function_executor(config=CONFIG)
        futures = pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function, chunk_n=2)
        result = pw.get_result(futures)
        self.assertEqual(result, self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 11)

    def test_chunks_bucket_one_reducer_per_object(self):
        print('Testing chunks on a bucket with one reducer per object...')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'

        pw = lithops.function_executor(config=CONFIG)
        futures = pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function,
                                chunk_size=1 * 1024 ** 2, reducer_one_per_object=True)
        result = pw.get_result(futures)
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 12)

        pw = lithops.function_executor(config=CONFIG)
        futures = pw.map_reduce(TestMethods.my_map_function_obj, data_prefix, TestMethods.my_reduce_function, chunk_n=2,
                                reducer_one_per_object=True)
        result = pw.get_result(futures)
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 15)

    def test_cloudobject(self):
        print('Testing cloudobjects...')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        with lithops.function_executor(config=CONFIG) as pw:
            pw.map_reduce(TestMethods.my_cloudobject_put, data_prefix, TestMethods.my_cloudobject_get)
            result = pw.get_result()
            self.assertEqual(result, self.__class__.cos_result_to_compare)


def print_help():
    print("Available test functions:")
    func_names = filter(lambda s: s[:4] == 'test',
                        map(lambda t: t[0], inspect.getmembers(TestLithops(), inspect.ismethod)))
    for func_name in func_names:
        print(f'-> {func_name}')


def run_tests(test_to_run, config=None):
    global CONFIG, STORAGE_CONFIG, STORAGE

    CONFIG = json.load(args.config) if config else default_config()
    STORAGE_CONFIG = extract_storage_config(CONFIG)
    STORAGE = InternalStorage(STORAGE_CONFIG).storage

    suite = unittest.TestSuite()
    if test_to_run == 'all':
        suite.addTest(unittest.makeSuite(TestLithops))
    else:
        try:
            suite.addTest(TestLithops(test_to_run))
        except ValueError:
            print("unknown test, use: --help")
            sys.exit()

    runner = unittest.TextTestRunner()
    runner.run(suite)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="test all Lithops's functionality",
                                     usage='python -m lithops.tests [-c CONFIG] [-t TESTNAME]')
    parser.add_argument('-c', '--config', type=argparse.FileType('r'), metavar='', default=None,
                        help="use json config file")
    parser.add_argument('-t', '--test', metavar='', default='all',
                        help='run a specific test, type "-t help" for tests list')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='activate debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    if args.test == 'help':
        print_help()
    else:
        run_tests(args.test, args.config)
