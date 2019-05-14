import sys
import unittest
import pywren_ibm_cloud as pywren
import urllib.request
from pywren_ibm_cloud.storage.backends import cos
from pywren_ibm_cloud import wrenconfig
from multiprocessing.pool import ThreadPool
import logging


# logging.basicConfig(level=logging.DEBUG)


def initTests():
    print('Uploading test files...')

    def up(param):
        i, url = param
        content = urllib.request.urlopen(url).read()
        STORAGE.put_object(bucket_name=STORAGE_CONFIG['storage_bucket'],
                           key=f'{PREFIX}/test{str(i)}',
                           data=content)
        return len(content.split())

    pool = ThreadPool(128)
    results = pool.map(up, enumerate(TEST_FILES_URLS))
    pool.close()
    pool.join()
    result_to_compare = 1 + sum(results)  # including result's word

    STORAGE.put_object(bucket_name=STORAGE_CONFIG['storage_bucket'],
                       key=f'{PREFIX}/result',
                       data=str(result_to_compare).encode())


def list_test_keys():
    return STORAGE.list_keys_with_prefix(bucket_name=STORAGE_CONFIG['storage_bucket'],
                                         prefix=PREFIX)


def cleanTests():
    print('Deleting test files...')
    for key in list_test_keys():
        STORAGE.delete_object(bucket_name=STORAGE_CONFIG['storage_bucket'],
                              key=key)


PREFIX = '__pywren.test'
TEST_FILES_URLS = ["http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.enron.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.kos.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nips.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.nytimes.txt",
                   "http://archive.ics.uci.edu/ml/machine-learning-databases/bag-of-words/vocab.pubmed.txt"]


def hello_world(param):
    return "Hello World!"


def simple_map_function(x, y):
    return x + y


def simple_reduce_function(results):
    total = 0
    for map_result in results:
        total = total + map_result
    return total


class TestPywren(unittest.TestCase):

    def test_call_async(self):
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.call_async(hello_world, "")
        result = pw.get_result()
        self.assertEqual(result, "Hello World!")

        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.call_async(simple_map_function, [4, 6])
        result = pw.get_result()
        self.assertEqual(result, 10)

        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.call_async(simple_map_function, {'x': 2, 'y': 8})
        result = pw.get_result()
        self.assertEqual(result, 10)

    def test_map(self):
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map(simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

    def test_map_reduce(self):
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map_reduce(simple_map_function, iterdata, simple_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, 20)

    def test_multiple_executions(self):
        pw = pywren.ibm_cf_executor(config=CONFIG)
        iterdata = [[1, 1], [2, 2]]
        pw.map(simple_map_function, iterdata)
        iterdata = [[3, 3], [4, 4]]
        pw.map(simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        iterdata = [[1, 1], [2, 2]]
        futures1 = pw.map(simple_map_function, iterdata)
        result1 = pw.get_result(futures=futures1)
        iterdata = [[3, 3], [4, 4]]
        futures2 = pw.map(simple_map_function, iterdata)
        result2 = pw.get_result(futures=futures2)
        self.assertEqual(result1, [2, 4])
        self.assertEqual(result2, [6, 8])


def my_map_function_bucket(bucket, key, data_stream, ibm_cos):
    print('I am processing the object {}'.format(key))
    counter = {}

    data = data_stream.read()
    temp = ibm_cos.get_object(Bucket=bucket, Key=key)['Body'].read()

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1

    return counter


def my_map_function_key(key, data_stream, ibm_cos):
    print('I am processing the object {}'.format(key))
    counter = {}

    data = data_stream.read()
    temp = ibm_cos.get_object(Bucket=key.split('/')[0], Key='/'.join(key.split('/')[1:]))['Body'].read()

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1

    return counter


def my_map_function_url(url, data_stream):
    print('I am processing the object from {}'.format(url))
    counter = {}

    data = data_stream.read()

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1

    return counter


def my_map_function_storage_handler(key_i, bucket_name, ibm_cos):
    print('I am processing the object {}'.format(key_i))
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


class TestPywrenCos(unittest.TestCase):

    def checkResult(self, result):
        result_to_compare = STORAGE.get_object(bucket_name=STORAGE_CONFIG['storage_bucket'],
                                               key=f'{PREFIX}/result')

        if isinstance(result, list):
            total = 0
            for r in result:
                total += r
        else:
            total = result

        self.assertEqual(total, int(result_to_compare))

    def test_map_reduce_cos_bucket(self):
        data_prefix = STORAGE_CONFIG['storage_bucket'] + '/' + PREFIX
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map_reduce(my_map_function_bucket, data_prefix, my_reduce_function)
        result = pw.get_result()
        self.checkResult(result)

    def test_map_reduce_cos_bucket_one_reducer_per_object(self):
        data_prefix = STORAGE_CONFIG['storage_bucket'] + '/' + PREFIX
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map_reduce(my_map_function_bucket, data_prefix, my_reduce_function, reducer_one_per_object=True)
        result = pw.get_result()
        self.checkResult(result)

    def test_map_reduce_cos_key(self):
        bucket_name = STORAGE_CONFIG['storage_bucket']
        iterdata = [bucket_name + '/' + key for key in list_test_keys()]
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map_reduce(my_map_function_key, iterdata, my_reduce_function)
        result = pw.get_result()
        self.checkResult(result)

    def test_map_reduce_cos_key_one_reducer_per_object(self):
        bucket_name = STORAGE_CONFIG['storage_bucket']
        iterdata = [bucket_name + '/' + key for key in list_test_keys()]
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map_reduce(my_map_function_key, iterdata, my_reduce_function, reducer_one_per_object=True)
        result = pw.get_result()
        self.checkResult(result)

    def test_map_reduce_url(self):
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map_reduce(my_map_function_url, TEST_FILES_URLS, my_reduce_function)
        result = pw.get_result()
        self.checkResult(result + 1)

    def test_storage_handler(self):
        iterdata = [[key, STORAGE_CONFIG['storage_bucket']] for key in list_test_keys()]
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map_reduce(my_map_function_storage_handler, iterdata, my_reduce_function)
        result = pw.get_result()
        self.checkResult(result)

    def test_chunks_bucket(self):
        data_prefix = STORAGE_CONFIG['storage_bucket'] + '/' + PREFIX
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map_reduce(my_map_function_bucket, data_prefix, my_reduce_function, chunk_size=1 * 1024 ** 2)
        result = pw.get_result()
        self.checkResult(result)

    def test_chunks_bucket_one_reducer_per_object(self):
        data_prefix = STORAGE_CONFIG['storage_bucket'] + '/' + PREFIX
        pw = pywren.ibm_cf_executor(config=CONFIG)
        pw.map_reduce(my_map_function_bucket, data_prefix, my_reduce_function, chunk_size=1 * 1024 ** 2,
                      reducer_one_per_object=True)
        result = pw.get_result()
        self.checkResult(result)


def run(config=None):
    global CONFIG
    global STORAGE_CONFIG
    global STORAGE

    if config is None:
        CONFIG = wrenconfig.default()
    else:
        CONFIG = wrenconfig.default(config)

    STORAGE_CONFIG = wrenconfig.extract_storage_config(CONFIG)
    STORAGE = cos.COSBackend(STORAGE_CONFIG['ibm_cos'])

    if len(sys.argv) <= 1:
        task = 'full'
    else:
        task = sys.argv[1]

    suite = unittest.TestSuite()
    if task == 'pywren':
        suite.addTest(unittest.makeSuite(TestPywren))
    elif task == 'pywren_cos':
        suite.addTest(unittest.makeSuite(TestPywrenCos))
    elif task == 'full':
        suite.addTest(unittest.makeSuite(TestPywren))
        suite.addTest(unittest.makeSuite(TestPywrenCos))
    elif task == 'test_call_async':
        suite.addTest(TestPywren('test_call_async'))
    elif task == 'test_map':
        suite.addTest(TestPywren('test_map'))
    elif task == 'test_map_reduce':
        suite.addTest(TestPywren('test_map_reduce'))
    elif task == 'test_multiple_executions':
        suite.addTest(TestPywren('test_multiple_executions'))
    elif task == 'test_map_reduce_cos_bucket':
        suite.addTest(TestPywrenCos('test_map_reduce_cos_bucket'))
    elif task == 'test_map_reduce_cos_bucket_one_reducer_per_object':
        suite.addTest(TestPywrenCos('test_map_reduce_cos_bucket_one_reducer_per_object'))
    elif task == 'test_map_reduce_cos_key':
        suite.addTest(TestPywrenCos('test_map_reduce_cos_key'))
    elif task == 'test_map_reduce_cos_key_one_reducer_per_object':
        suite.addTest(TestPywrenCos('test_map_reduce_cos_key_one_reducer_per_object'))
    elif task == 'test_map_reduce_url':
        suite.addTest(TestPywrenCos('test_map_reduce_url'))
    elif task == 'test_storage_handler':
        suite.addTest(TestPywrenCos('test_storage_handler'))
    elif task == 'test_chunks_bucket':
        suite.addTest(TestPywrenCos('test_chunks_bucket'))
    elif task == 'test_chunks_bucket_one_reducer_per_object':
        suite.addTest(TestPywrenCos('test_chunks_bucket_one_reducer_per_object'))
    else:
        print('Unknown Command... use: "init", "pywren", "pywren_cos", "clean" or a test function name.')
        sys.exit()

    initTests()
    runner = unittest.TextTestRunner()
    runner.run(suite)
    cleanTests()


if __name__ == '__main__':
    run()
