#
# (C) Copyright IBM Corp. 2020
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import sys
import json
import pickle
import argparse
import time
import unittest
import logging
import inspect
import lithops
import urllib.request
from lithops.storage import InternalStorage
from lithops.config import default_config, extract_storage_config
from concurrent.futures import ThreadPoolExecutor
from lithops import multiprocessing as lithops_multiprocessing


# CONFIG = None
# STORAGE_CONFIG = None
# STORAGE = None
#
# PREFIX = '__lithops.test'
# TEST_FILES_URLS = ['http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.enron.txt',
#                    'http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.kos.txt',
#                    'http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nips.txt',
#                    'http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nytimes.txt',
#                    'http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.pubmed.txt']


# class TestUtils:
#
#     @staticmethod
#     def initTests():
#         def up(param):
#             i, url = param
#             content = urllib.request.urlopen(url).read()
#             STORAGE.put_object(bucket_name=STORAGE_CONFIG['bucket'],
#                                key='{}/test{}'.format(PREFIX, str(i)),
#                                data=content)
#             return len(content.split())
#
#         with ThreadPoolExecutor() as pool:
#             results = list(pool.map(up, enumerate(TEST_FILES_URLS)))
#
#         result_to_compare = sum(results)
#         return result_to_compare
#
#     @staticmethod
#     def list_test_keys():
#         return STORAGE.list_keys(bucket_name=STORAGE_CONFIG['bucket'], prefix=PREFIX + '/')
#
#     @staticmethod
#     def cleanTests():
#         for key in TestUtils.list_test_keys():
#             STORAGE.delete_object(bucket_name=STORAGE_CONFIG['bucket'],
#                                   key=key)


class TestMethods:

    @staticmethod
    def hello_world(param):
        return 'Hello World!'

    @staticmethod
    def concat(lst):
        return "".join(lst)

    @staticmethod
    def simple_map_function(x, y):
        return x + y

    @staticmethod
    def sleep(seconds):
        time.sleep(seconds)
        return "I've slept {} seconds".format(seconds)

    @staticmethod
    def success_callback(result):
        print('Success! Result: {}'.format(result))

    @staticmethod
    def division_zero():
        return 1 / 0


class TestMultiprocessing(unittest.TestCase):
    def test_process(self):
        print('### PROCESS TEST ###')
        p = lithops_multiprocessing.Process(target=TestMethods.hello_world)
        p.start()
        p.join()

        p = lithops_multiprocessing.Process(target=TestMethods.concat, args=('a', 'b'))
        p.start()
        p.join()

        p = lithops_multiprocessing.Process(target=TestMethods.simple_map_function, args=[4, 6])
        p.start()
        p.join()
        
        p = lithops_multiprocessing.Process(target=TestMethods.simple_map_function, kwargs={'a': 4, 'b': 6})
        p.start()
        p.join()

    def test_pool(self):
        print('### POOL TEST ###')
        # single apply
        p = lithops_multiprocessing.Pool()
        self.assertEqual(p.apply(TestMethods.hello_world), 'Hello World!')
        p.close()
        p.join()

        # multiple apply same pool
        p = lithops_multiprocessing.Pool()
        self.assertEqual(p.apply(TestMethods.hello_world), 'Hello World!')
        self.assertEqual(p.apply(TestMethods.concat, ('a', 'b')), 'ab')
        self.assertEqual(p.apply(TestMethods.simple_map_function, kwds={'x': 4, 'y': 6}), 10)
        p.close()
        p.join()

        # apply_async and ApplyResult
        p = lithops_multiprocessing.Pool()
        async_result = p.apply_async(TestMethods.sleep, (3,))
        self.assertFalse(async_result.ready())
        async_result.wait()
        self.assertTrue(async_result.ready())
        self.assertEquals(async_result.get(), "I've slept 3 seconds")

        async_result = p.apply_async(TestMethods.sleep, (3,))
        self.assertRaises(ValueError, async_result.successful)
        self.assertEqual(async_result.get(), "I've slept 3 seconds")



    # def test_map(self):
    #     print('Testing map()...')
    #     iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.map(TestMethods.simple_map_function, iterdata)
    #     result = fexec.get_result()
    #     self.assertEqual(result, [2, 4, 6, 8])
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG, workers=1)
    #     fexec.map(TestMethods.simple_map_function, iterdata)
    #     result = fexec.get_result()
    #     self.assertEqual(result, [2, 4, 6, 8])
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     set_iterdata = set(range(2))
    #     fexec.map(TestMethods.hello_world, set_iterdata)
    #     result = fexec.get_result()
    #     self.assertEqual(result, ['Hello World!'] * 2)
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     generator_iterdata = range(2)
    #     fexec.map(TestMethods.hello_world, generator_iterdata)
    #     result = fexec.get_result()
    #     self.assertEqual(result, ['Hello World!'] * 2)
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     listDicts_iterdata = [{'x': 2, 'y': 8}, {'x': 2, 'y': 8}]
    #     fexec.map(TestMethods.simple_map_function, listDicts_iterdata)
    #     result = fexec.get_result()
    #     self.assertEqual(result, [10, 10])
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     set_iterdata = [['a', 'b'], ['c', 'd']]
    #     fexec.map(TestMethods.concat, set_iterdata)
    #     result = fexec.get_result()
    #     self.assertEqual(result, ['a b', 'c d'])
    #
    # def test_map_reduce(self):
    #     print('Testing map_reduce()...')
    #     iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.map_reduce(TestMethods.simple_map_function, iterdata,
    #                      TestMethods.simple_reduce_function)
    #     result = fexec.get_result()
    #     self.assertEqual(result, 20)
    #
    # def test_multiple_executions(self):
    #     print('Testing multiple executions...')
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     iterdata = [[1, 1], [2, 2]]
    #     fexec.map(TestMethods.simple_map_function, iterdata)
    #     iterdata = [[3, 3], [4, 4]]
    #     fexec.map(TestMethods.simple_map_function, iterdata)
    #     result = fexec.get_result()
    #     self.assertEqual(result, [2, 4, 6, 8])
    #
    #     iterdata = [[1, 1], [2, 2]]
    #     fexec.map(TestMethods.simple_map_function, iterdata)
    #     result = fexec.get_result()
    #     self.assertEqual(result, [2, 4])
    #
    #     iterdata = [[1, 1], [2, 2]]
    #     futures1 = fexec.map(TestMethods.simple_map_function, iterdata)
    #     result1 = fexec.get_result(fs=futures1)
    #     iterdata = [[3, 3], [4, 4]]
    #     futures2 = fexec.map(TestMethods.simple_map_function, iterdata)
    #     result2 = fexec.get_result(fs=futures2)
    #     self.assertEqual(result1, [2, 4])
    #     self.assertEqual(result2, [6, 8])
    #
    # def test_internal_executions(self):
    #     print('Testing internal executions...')
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.map(TestMethods.lithops_inside_lithops_map_function, range(1, 11))
    #     result = fexec.get_result()
    #     self.assertEqual(result, [list(range(i)) for i in range(1, 11)])
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.call_async(TestMethods.lithops_return_futures_map_function1, 3)
    #     fexec.get_result()
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.call_async(TestMethods.lithops_return_futures_map_function2, 3)
    #     fexec.get_result()
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.call_async(TestMethods.lithops_return_futures_map_function3, 3)
    #     fexec.wait()
    #     fexec.get_result()
    #
    # def test_map_reduce_obj_bucket(self):
    #     print('Testing map_reduce() over a bucket...')
    #     sb = STORAGE_CONFIG['backend']
    #     data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
    #                      TestMethods.my_reduce_function)
    #     result = fexec.get_result()
    #     self.assertEqual(result, self.__class__.cos_result_to_compare)
    #
    # def test_map_reduce_obj_bucket_one_reducer_per_object(self):
    #     print('Testing map_reduce() over a bucket with one reducer per object...')
    #     sb = STORAGE_CONFIG['backend']
    #     data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
    #                      TestMethods.my_reduce_function,
    #                      reducer_one_per_object=True)
    #     result = fexec.get_result()
    #     self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
    #
    # def test_map_reduce_obj_key(self):
    #     print('Testing map_reduce() over object keys...')
    #     sb = STORAGE_CONFIG['backend']
    #     bucket_name = STORAGE_CONFIG['bucket']
    #     iterdata = [sb + '://' + bucket_name + '/' + key for key in TestUtils.list_test_keys()]
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.map_reduce(TestMethods.my_map_function_obj, iterdata,
    #                      TestMethods.my_reduce_function)
    #     result = fexec.get_result()
    #     self.assertEqual(result, self.__class__.cos_result_to_compare)
    #
    # def test_map_reduce_obj_key_one_reducer_per_object(self):
    #     print('Testing map_reduce() over object keys with one reducer per object...')
    #     sb = STORAGE_CONFIG['backend']
    #     bucket_name = STORAGE_CONFIG['bucket']
    #     iterdata = [sb + '://' + bucket_name + '/' + key for key in TestUtils.list_test_keys()]
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.map_reduce(TestMethods.my_map_function_obj, iterdata,
    #                      TestMethods.my_reduce_function,
    #                      reducer_one_per_object=True)
    #     result = fexec.get_result()
    #     self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
    #
    # def test_map_reduce_url(self):
    #     print('Testing map_reduce() over URLs...')
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.map_reduce(TestMethods.my_map_function_url, TEST_FILES_URLS,
    #                      TestMethods.my_reduce_function)
    #     result = fexec.get_result()
    #     self.assertEqual(result, self.__class__.cos_result_to_compare)
    #
    # def test_storage_handler(self):
    #     print('Testing 'storage' function arg...')
    #     iterdata = [[key, STORAGE_CONFIG['bucket']] for key in TestUtils.list_test_keys()]
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     fexec.map_reduce(TestMethods.my_map_function_storage, iterdata,
    #                      TestMethods.my_reduce_function)
    #     result = fexec.get_result()
    #     self.assertEqual(result, self.__class__.cos_result_to_compare)
    #
    # def test_chunks_bucket(self):
    #     print('Testing chunks on a bucket...')
    #     sb = STORAGE_CONFIG['backend']
    #     data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     futures = fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
    #                                TestMethods.my_reduce_function,
    #                                chunk_size=1 * 1024 ** 2)
    #     result = fexec.get_result(futures)
    #     self.assertEqual(result, self.__class__.cos_result_to_compare)
    #     self.assertEqual(len(futures), 8)
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     futures = fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
    #                                TestMethods.my_reduce_function, chunk_n=2)
    #     result = fexec.get_result(futures)
    #     self.assertEqual(result, self.__class__.cos_result_to_compare)
    #     self.assertEqual(len(futures), 11)
    #
    # def test_chunks_bucket_one_reducer_per_object(self):
    #     print('Testing chunks on a bucket with one reducer per object...')
    #     sb = STORAGE_CONFIG['backend']
    #     data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     futures = fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
    #                                TestMethods.my_reduce_function,
    #                                chunk_size=1 * 1024 ** 2, reducer_one_per_object=True)
    #     result = fexec.get_result(futures)
    #     self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
    #     self.assertEqual(len(futures), 12)
    #
    #     fexec = lithops.FunctionExecutor(config=CONFIG)
    #     futures = fexec.map_reduce(TestMethods.my_map_function_obj, data_prefix,
    #                                TestMethods.my_reduce_function, chunk_n=2,
    #                                reducer_one_per_object=True)
    #     result = fexec.get_result(futures)
    #     self.assertEqual(sum(result), self.__class__.cos_result_to_compare)
    #     self.assertEqual(len(futures), 15)
    #
    # def test_cloudobject(self):
    #     print('Testing cloudobjects...')
    #     sb = STORAGE_CONFIG['backend']
    #     data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + PREFIX + '/'
    #     with lithops.FunctionExecutor(config=CONFIG) as fexec:
    #         fexec.map_reduce(TestMethods.my_cloudobject_put, data_prefix, TestMethods.my_cloudobject_get)
    #         result = fexec.get_result()
    #         self.assertEqual(result, self.__class__.cos_result_to_compare)


def print_help():
    print('Available test functions:')
    func_names = filter(lambda s: s[:4] == 'test',
                        map(lambda t: t[0], inspect.getmembers(TestMultiprocessing(), inspect.ismethod)))
    for func_name in func_names:
        print(f'-> {func_name}')


def run_tests(test_to_run, executor, config=None):
    global CONFIG, STORAGE_CONFIG, STORAGE

    config_ow = {}
    if executor:
        config_ow['lithops'] = {'executor': executor}

    CONFIG = json.load(config) if config else default_config(config_overwrite=config_ow)
    STORAGE_CONFIG = extract_storage_config(CONFIG)
    STORAGE = InternalStorage(STORAGE_CONFIG).storage

    suite = unittest.TestSuite()
    if test_to_run == 'all':
        suite.addTest(unittest.makeSuite(TestMultiprocessing))
    else:
        try:
            suite.addTest(TestMultiprocessing(test_to_run))
        except ValueError:
            print('unknown test, use: --help')
            sys.exit()

    runner = unittest.TextTestRunner()
    runner.run(suite)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="test all Lithops's functionality",
                                     usage='python -m lithops.tests [-c CONFIG] [-t TESTNAME]')
    parser.add_argument('-c', '--config', type=argparse.FileType('r'), metavar='', default=None,
                        help='use json config file')
    parser.add_argument('-t', '--test', metavar='', default='all',
                        help="run a specific test, type '-t help' for tests list")
    parser.add_argument('-e', '--executor', metavar='', default=None,
                        help='serverless, standalone or localhost')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='activate debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    if args.test == 'help':
        print_help()
    else:
        run_tests(args.test, args.executor, args.config)
