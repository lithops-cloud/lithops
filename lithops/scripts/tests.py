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
import pickle
import argparse
import unittest
import logging
import inspect
from io import BytesIO

import lithops
import urllib.request

from lithops.storage import Storage
from lithops.config import get_mode, default_config, extract_storage_config
from concurrent.futures import ThreadPoolExecutor

from lithops.storage.utils import StorageNoSuchKeyError
from lithops.utils import setup_logger

logger = logging.getLogger(__name__)

CONFIG = None
STORAGE_CONFIG = None
STORAGE = None

PREFIX = '__lithops.test'
DATASET_PREFIX = PREFIX + '/dataset'
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
            STORAGE.put_object(bucket=STORAGE_CONFIG['bucket'],
                               key='{}/test{}'.format(DATASET_PREFIX, str(i)),
                               body=content)
            return len(content.split())

        with ThreadPoolExecutor() as pool:
            results = list(pool.map(up, enumerate(TEST_FILES_URLS)))

        result_to_compare = sum(results)
        return result_to_compare

    @staticmethod
    def list_test_keys():
        return STORAGE.list_keys(bucket=STORAGE_CONFIG['bucket'], prefix=PREFIX + '/')

    @staticmethod
    def list_dataset_keys():
        return STORAGE.list_keys(bucket=STORAGE_CONFIG['bucket'],
                                 prefix=DATASET_PREFIX + '/')

    @staticmethod
    def cleanTests():
        for key in TestUtils.list_test_keys():
            STORAGE.delete_object(bucket=STORAGE_CONFIG['bucket'],
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

        fexec = lithops.FunctionExecutor()
        fexec.map(_func, range(x))
        return fexec.get_result()

    @staticmethod
    def lithops_return_futures_map_function1(x):
        def _func(x):
            return x + 1

        fexec = lithops.FunctionExecutor()
        return fexec.map(_func, range(x))

    @staticmethod
    def lithops_return_futures_map_function2(x):
        def _func(x):
            return x + 1

        fexec = lithops.FunctionExecutor()
        return fexec.call_async(_func, x + 5)

    @staticmethod
    def lithops_return_futures_map_function3(x):
        def _func(x):
            return x + 1

        fexec = lithops.FunctionExecutor()
        fut1 = fexec.map(_func, range(x))
        fut2 = fexec.map(_func, range(x))
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
        cloudobject = storage.put_cloudobject(pickle.dumps(counter))
        return cloudobject

    @staticmethod
    def my_cloudobject_get(cloudobjects, storage):
        data = [pickle.loads(storage.get_cloudobject(co)) for co in cloudobjects]
        return TestMethods.my_reduce_function(data)


class TestLithops(unittest.TestCase):
    cos_result_to_compare = None

    @classmethod
    def setUpClass(cls):
        logger.info('Uploading test files')
        cls.cos_result_to_compare = TestUtils.initTests()

    @classmethod
    def tearDownClass(cls):
        logger.info('Deleting test files')
        TestUtils.cleanTests()

    @classmethod
    def tearDown(cls):
        print()

    def test_call_async(self):
        logger.info('Testing call_async()')
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.call_async(TestMethods.hello_world, "")
        result = fexec.get_result()
        self.assertEqual(result, "Hello World!")

        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.call_async(TestMethods.concat, ["a", "b"])
        result = fexec.get_result()
        self.assertEqual(result, "a b")

        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.call_async(TestMethods.simple_map_function, (4, 6))
        result = fexec.get_result()
        self.assertEqual(result, 10)

        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.call_async(TestMethods.simple_map_function, {'x': 2, 'y': 8})
        result = fexec.get_result()
        self.assertEqual(result, 10)

    def test_map(self):
        logger.info('Testing map()')
        iterdata = [(1, 1), (2, 2), (3, 3), (4, 4)]
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map(TestMethods.simple_map_function, iterdata)
        result = fexec.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        fexec = lithops.FunctionExecutor(config=CONFIG, workers=1)
        fexec.map(TestMethods.simple_map_function, iterdata)
        result = fexec.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        fexec = lithops.FunctionExecutor(config=CONFIG)
        set_iterdata = set(range(2))
        fexec.map(TestMethods.hello_world, set_iterdata)
        result = fexec.get_result()
        self.assertEqual(result, ['Hello World!'] * 2)

        fexec = lithops.FunctionExecutor(config=CONFIG)
        generator_iterdata = range(2)
        fexec.map(TestMethods.hello_world, generator_iterdata)
        result = fexec.get_result()
        self.assertEqual(result, ['Hello World!'] * 2)

        fexec = lithops.FunctionExecutor(config=CONFIG)
        listDicts_iterdata = [{'x': 2, 'y': 8}, {'x': 2, 'y': 8}]
        fexec.map(TestMethods.simple_map_function, listDicts_iterdata)
        result = fexec.get_result()
        self.assertEqual(result, [10, 10])

        fexec = lithops.FunctionExecutor(config=CONFIG)
        set_iterdata = [["a", "b"], ["c", "d"]]
        fexec.map(TestMethods.concat, set_iterdata)
        result = fexec.get_result()
        self.assertEqual(result, ["a b", "c d"])

    def test_map_reduce(self):
        logger.info('Testing map_reduce()')
        iterdata = [(1, 1), (2, 2), (3, 3), (4, 4)]
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map_reduce(TestMethods.simple_map_function, iterdata,
                         TestMethods.simple_reduce_function)
        result = fexec.get_result()
        self.assertEqual(result, 20)

    def test_multiple_executions(self):
        logger.info('Testing multiple executions')
        fexec = lithops.FunctionExecutor(config=CONFIG)
        iterdata = [(1, 1), (2, 2)]
        fexec.map(TestMethods.simple_map_function, iterdata)
        iterdata = [(3, 3), (4, 4)]
        fexec.map(TestMethods.simple_map_function, iterdata)
        result = fexec.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        iterdata = [(1, 1), (2, 2)]
        fexec.map(TestMethods.simple_map_function, iterdata)
        result = fexec.get_result()
        self.assertEqual(result, [2, 4])

        iterdata = [(1, 1), (2, 2)]
        futures1 = fexec.map(TestMethods.simple_map_function, iterdata)
        result1 = fexec.get_result(fs=futures1)
        iterdata = [(3, 3), (4, 4)]
        futures2 = fexec.map(TestMethods.simple_map_function, iterdata)
        result2 = fexec.get_result(fs=futures2)
        self.assertEqual(result1, [2, 4])
        self.assertEqual(result2, [6, 8])

    def test_internal_executions(self):
        logger.info('Testing internal executions')
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map(TestMethods.lithops_inside_lithops_map_function, range(1, 11))
        result = fexec.get_result()
        self.assertEqual(result, [list(range(i)) for i in range(1, 11)])

        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.call_async(TestMethods.lithops_return_futures_map_function1, 3)
        fexec.get_result()

        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.call_async(TestMethods.lithops_return_futures_map_function2, 3)
        fexec.get_result()

        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.call_async(TestMethods.lithops_return_futures_map_function3, 3)
        fexec.wait()
        fexec.get_result()

    def test_map_reduce_obj_bucket(self):
        logger.info('Testing map_reduce() over a bucket')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
                         TestMethods.my_reduce_function)
        result = fexec.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_map_reduce_obj_bucket_one_reducer_per_object(self):
        logger.info('Testing map_reduce() over a bucket with one reducer per object')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
                         TestMethods.my_reduce_function,
                         reducer_one_per_object=True)
        result = fexec.get_result()
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)

    def test_map_reduce_obj_key(self):
        logger.info('Testing map_reduce() over object keys')
        sb = STORAGE_CONFIG['backend']
        bucket_name = STORAGE_CONFIG['bucket']
        iterdata = [sb + '://' + bucket_name + '/' + key for key in TestUtils.list_dataset_keys()]
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map_reduce(TestMethods.my_map_function_obj, iterdata,
                         TestMethods.my_reduce_function)
        result = fexec.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_map_reduce_obj_key_one_reducer_per_object(self):
        logger.info('Testing map_reduce() over object keys with one reducer per object')
        sb = STORAGE_CONFIG['backend']
        bucket_name = STORAGE_CONFIG['bucket']
        iterdata = [sb + '://' + bucket_name + '/' + key for key in TestUtils.list_dataset_keys()]
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map_reduce(TestMethods.my_map_function_obj, iterdata,
                         TestMethods.my_reduce_function,
                         reducer_one_per_object=True)
        result = fexec.get_result()
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)

    def test_map_reduce_url(self):
        logger.info('Testing map_reduce() over URLs')
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map_reduce(TestMethods.my_map_function_url, TEST_FILES_URLS,
                         TestMethods.my_reduce_function)
        result = fexec.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_storage_handler(self):
        logger.info('Testing "storage" function arg')
        iterdata = [(key, STORAGE_CONFIG['bucket']) for key in TestUtils.list_dataset_keys()]
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map_reduce(TestMethods.my_map_function_storage, iterdata,
                         TestMethods.my_reduce_function)
        result = fexec.get_result()
        self.assertEqual(result, self.__class__.cos_result_to_compare)

    def test_chunks_bucket(self):
        logger.info('Testing chunks on a bucket')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'

        fexec = lithops.FunctionExecutor(config=CONFIG)
        futures = fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
                                   TestMethods.my_reduce_function,
                                   chunk_size=1 * 1024 ** 2)
        result = fexec.get_result(futures)
        self.assertEqual(result, self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 8)

        fexec = lithops.FunctionExecutor(config=CONFIG)
        futures = fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
                                   TestMethods.my_reduce_function, chunk_n=2)
        result = fexec.get_result(futures)
        self.assertEqual(result, self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 11)

    def test_chunks_bucket_one_reducer_per_object(self):
        logger.info('Testing chunks on a bucket with one reducer per object')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'

        fexec = lithops.FunctionExecutor(config=CONFIG)
        futures = fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
                                   TestMethods.my_reduce_function,
                                   chunk_size=1 * 1024 ** 2, reducer_one_per_object=True)
        result = fexec.get_result(futures)
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 12)

        fexec = lithops.FunctionExecutor(config=CONFIG)
        futures = fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
                                   TestMethods.my_reduce_function, chunk_n=2,
                                   reducer_one_per_object=True)
        result = fexec.get_result(futures)
        self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
        self.assertEqual(len(futures), 15)

    def test_cloudobject(self):
        logger.info('Testing cloudobjects')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
        with lithops.FunctionExecutor(config=CONFIG) as fexec:
            fexec.map(TestMethods.my_cloudobject_put, data_prefix)
            cloudobjects = fexec.get_result()
            fexec.call_async(TestMethods.my_cloudobject_get, cloudobjects)
            result = fexec.get_result()
            self.assertEqual(result, self.__class__.cos_result_to_compare)
            fexec.clean(cs=cloudobjects)

    def test_storage_put_get_by_stream(self):
        logger.info('Testing Storage.put_object and get_object with streams')
        bucket = STORAGE_CONFIG['bucket']
        bytes_data = b'123'
        bytes_key = PREFIX + '/bytes'

        STORAGE.put_object(bucket, bytes_key, BytesIO(bytes_data))
        bytes_stream = STORAGE.get_object(bucket, bytes_key, stream=True)

        self.assertTrue(hasattr(bytes_stream, 'read'))
        self.assertEqual(bytes_stream.read(), bytes_data)

    def test_storage_get_by_range(self):
        logger.info('Testing Storage.get_object with Range argument')
        bucket = STORAGE_CONFIG['bucket']
        key = PREFIX + '/bytes'
        STORAGE.put_object(bucket, key, b'0123456789')

        result = STORAGE.get_object(bucket, key, extra_get_args={'Range': 'bytes=1-4'})

        self.assertEqual(result, b'1234')

    def test_storage_list_keys(self):
        logger.info('Testing Storage.list_keys')
        bucket = STORAGE_CONFIG['bucket']
        test_keys = sorted([
            PREFIX + '/foo/baz',
            PREFIX + '/foo/bar/baz',
            PREFIX + '/foo_bar/baz',
            PREFIX + '/foo_baz',
            PREFIX + '/bar',
            PREFIX + '/bar_baz',
        ])
        for key in test_keys:
            STORAGE.put_object(bucket, key, key.encode())

        all_bucket_keys = STORAGE.list_keys(bucket)
        prefix_keys = STORAGE.list_keys(bucket, PREFIX)
        foo_keys = STORAGE.list_keys(bucket, PREFIX + '/foo')
        foo_slash_keys = STORAGE.list_keys(bucket, PREFIX + '/foo/')
        bar_keys = STORAGE.list_keys(bucket, PREFIX + '/bar')
        non_existent_keys = STORAGE.list_keys(bucket, PREFIX + '/doesnt_exist')

        self.assertTrue(set(all_bucket_keys).issuperset(test_keys))
        self.assertTrue(set(prefix_keys).issuperset(test_keys))
        self.assertTrue(all(key.startswith(PREFIX) for key in prefix_keys))
        # To ensure parity between filesystem and object storage implementations, test that
        # prefixes are treated as textual prefixes, not directory names.
        self.assertEqual(sorted(foo_keys), sorted([
            PREFIX + '/foo/baz',
            PREFIX + '/foo/bar/baz',
            PREFIX + '/foo_bar/baz',
            PREFIX + '/foo_baz',
        ]))
        self.assertEqual(sorted(foo_slash_keys), sorted([
            PREFIX + '/foo/baz',
            PREFIX + '/foo/bar/baz',
        ]))
        self.assertEqual(sorted(bar_keys), sorted([
            PREFIX + '/bar',
            PREFIX + '/bar_baz',
        ]))

        self.assertEqual(non_existent_keys, [])

    def test_storage_head_object(self):
        logger.info('Testing Storage.head_object')
        bucket = STORAGE_CONFIG['bucket']
        data = b'123456789'
        STORAGE.put_object(bucket, PREFIX + '/data', data)

        result = STORAGE.head_object(bucket, PREFIX + '/data')
        self.assertEqual(result['content-length'], str(len(data)))

        def get_nonexistent_object():
            STORAGE.head_object(bucket, PREFIX + '/doesnt_exist')
        self.assertRaises(StorageNoSuchKeyError, get_nonexistent_object)


def print_help():
    print("Available test functions:")
    func_names = filter(lambda s: s[:4] == 'test',
                        map(lambda t: t[0], inspect.getmembers(TestLithops(), inspect.ismethod)))
    for func_name in func_names:
        print(f'-> {func_name}')


def run_tests(test_to_run, config=None, mode=None, backend=None, storage=None):
    global CONFIG, STORAGE_CONFIG, STORAGE

    mode = mode or get_mode(config)
    config_ow = {'lithops': {'mode': mode}}
    if storage:
        config_ow['lithops']['storage'] = storage
    if backend:
        config_ow[mode] = {'backend': backend}
    CONFIG = default_config(config, config_ow)

    STORAGE_CONFIG = extract_storage_config(CONFIG)
    STORAGE = Storage(storage_config=STORAGE_CONFIG)

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
                                     usage='python -m lithops.scripts.tests [-c CONFIG] [-t TESTNAME]')
    parser.add_argument('-c', '--config', type=argparse.FileType('r'), metavar='', default=None,
                        help="use json config file")
    parser.add_argument('-t', '--test', metavar='', default='all',
                        help='run a specific test, type "-t help" for tests list')
    parser.add_argument('-m', '--mode', metavar='', default=None,
                        help='serverless, standalone or localhost')
    parser.add_argument('-b', '--backend', metavar='', default=None,
                        help='compute backend')
    parser.add_argument('-s', '--storage', metavar='', default=None,
                        help='storage backend')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='activate debug logging')
    args = parser.parse_args()

    log_level = logging.INFO if not args.debug else logging.DEBUG
    setup_logger(log_level)

    if args.test == 'help':
        print_help()
    else:
        run_tests(args.test, args.config, args.mode, args.backend, args.storage)
