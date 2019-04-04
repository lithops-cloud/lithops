import sys
import yaml
import os
import unittest
import ibm_boto3
from ibm_botocore.client import Config
from ibm_botocore.client import ClientError
import pywren_ibm_cloud as pywren
import urllib.request
import logging

PREFIX = '__pywren.test'

#logging.basicConfig(level=logging.DEBUG)

try:
    dir_path = os.path.dirname(__file__)
    path = os.path.join(dir_path, 'data')
    with open(path, 'r') as data_file:
        TEST_FILES_URLS = [url for url in data_file.read().split()]
except:
    print("can't open data file")
    sys.exit()

try:
    if 'PYWREN_CONFIG_FILE' in os.environ:
        config_path = os.environ['PYWREN_CONFIG_FILE']
    else:
        config_path = os.path.join(os.path.expanduser("~/.pywren_config"))
    with open(config_path, 'r') as config_file:
        CONFIG = yaml.safe_load(config_file)
except:
    print("can't open config file")
    sys.exit()


def initCos():
    return ibm_boto3.resource("s3",
                              ibm_api_key_id=CONFIG['ibm_cos']['api_key'],
                              ibm_auth_endpoint='https://iam.ng.bluemix.net/oidc/token',
                              config=Config(signature_version="oauth"),
                              endpoint_url=CONFIG['ibm_cos']['endpoint']
                              )


def putFileToCOS(cos, bucket_name, key, bytes):
    try:
        cos.Object(bucket_name, key).put(Body=bytes)
        print("Upload file: {} - SUCCESS".format(key))
    except ClientError as be:
        print("CLIENT ERROR: {0}\n".format(be))
    except Exception as e:
        print("Unable to create bucket: {0}".format(e))


def getFilenamesFromCOS(cos, bucket_name, prefix):
    print("Retrieving items' names from bucket: {0}, prefix: {1}".format(bucket_name, prefix))
    result = []
    try:
        for data in cos.Bucket(bucket_name).objects.filter(Prefix=prefix):
            result.append(data.key)
    except ClientError as be:
        print("CLIENT ERROR: {0}\n".format(be))
    except Exception as e:
        print("Unable to delete item: {0}".format(e))
    return result


def getFileFromCOS(cos, bucket_name, key):
    print("Retrieving item from bucket: {0}, key: {1}".format(bucket_name, key))
    try:
        file = cos.Object(bucket_name, key).get()
        return file["Body"].read()
    except ClientError as be:
        print("CLIENT ERROR: {0}\n".format(be))
    except Exception as e:
        print("Unable to retrieve file contents: {0}".format(e))


def deleteFileFromCOS(cos, bucket_name, key):
    try:
        cos.Object(bucket_name, key).delete()
        print("File: {0} deleted!".format(key))
    except ClientError as be:
        print("CLIENT ERROR: {0}\n".format(be))
    except Exception as e:
        print("Unable to delete item: {0}".format(e))


class TestPywren(unittest.TestCase):

    def hello_world(self, param):
        return "Hello World!"

    def simple_map_function(self, x, y):
        return x + y

    def simple_reduce_function(self, results):
        total = 0
        for map_result in results:
            total = total + map_result
        return total

    def test_call_async(self):
        pw = pywren.ibm_cf_executor()
        pw.call_async(self.hello_world, "")
        result = pw.get_result()
        self.assertEqual(result, "Hello World!")

        pw = pywren.ibm_cf_executor()
        pw.call_async(self.simple_map_function, [4, 6])
        result = pw.get_result()
        self.assertEqual(result, 10)

        pw = pywren.ibm_cf_executor()
        pw.call_async(self.simple_map_function, {'x': 2, 'y': 8})
        result = pw.get_result()
        self.assertEqual(result, 10)

    def test_map(self):
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = pywren.ibm_cf_executor()
        pw.map(self.simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

    def test_map_reduce(self):
        iterdata = [[1, 1], [2, 2], [3, 3], [4, 4]]
        pw = pywren.ibm_cf_executor()
        pw.map_reduce(self.simple_map_function, iterdata, self.simple_reduce_function)
        result = pw.get_result()
        self.assertEqual(result, 20)

    def test_multiple_executions(self):
        pw = pywren.ibm_cf_executor()
        iterdata = [[1, 1], [2, 2]]
        pw.map(self.simple_map_function, iterdata)
        iterdata = [[3, 3], [4, 4]]
        pw.map(self.simple_map_function, iterdata)
        result = pw.get_result()
        self.assertEqual(result, [2, 4, 6, 8])

        iterdata = [[1, 1], [2, 2]]
        futures1 = pw.map(self.simple_map_function, iterdata)
        result1 = pw.get_result(futures=futures1)
        iterdata = [[3, 3], [4, 4]]
        futures2 = pw.map(self.simple_map_function, iterdata)
        result2 = pw.get_result(futures=futures2)
        self.assertEqual(result1, [2, 4])
        self.assertEqual(result2, [6, 8])


def initTests():
    print('Uploading test files...')

    cos = initCos()
    result_to_compare = 1  # including result's word
    i = 0
    for url in TEST_FILES_URLS:
        content = urllib.request.urlopen(url).read()
        putFileToCOS(cos, CONFIG['pywren']['storage_bucket'], PREFIX + '/test' + str(i), content)
        result_to_compare += len(content.split())
        i += 1

    putFileToCOS(cos, CONFIG['pywren']['storage_bucket'], PREFIX + '/result', str(result_to_compare).encode())

    print("ALL DONE")


def cleanTests():
    print('Deleting test files...')

    cos = initCos()
    for key in getFilenamesFromCOS(cos, CONFIG['pywren']['storage_bucket'], PREFIX):
        deleteFileFromCOS(cos, CONFIG['pywren']['storage_bucket'], key)

    print("ALL DONE")


class TestPywrenCos(unittest.TestCase):

    def my_map_function_bucket(self, bucket, key, data_stream, ibm_cos):
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

    def my_map_function_key(self, key, data_stream, ibm_cos):
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

    def my_map_function_url(self, url, data_stream):
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

    def my_map_function_storage_handler(self, key_i, ibm_cos):
        print('I am processing the object {}'.format(key_i))
        counter = {}

        data = ibm_cos.get_object(Bucket=CONFIG['pywren']['storage_bucket'], Key=key_i)['Body'].read()

        for line in data.splitlines():
            for word in line.decode('utf-8').split():
                if word not in counter:
                    counter[word] = 1
                else:
                    counter[word] += 1

        return counter

    def my_reduce_function(self, results):
        final_result = 0

        for count in results:
            for word in count:
                final_result += count[word]

        return final_result

    def checkResult(self, cos, result):
        result_to_compare = getFileFromCOS(cos, CONFIG['pywren']['storage_bucket'], PREFIX + '/result')

        if isinstance(result, list):
            total = 0
            for r in result:
                total += r
        else:
            total = result

        self.assertEqual(total, int(result_to_compare))

    def test_map_reduce_cos_bucket(self):
        data_prefix = CONFIG['pywren']['storage_bucket'] + '/' + PREFIX
        pw = pywren.ibm_cf_executor()
        pw.map_reduce(self.my_map_function_bucket, data_prefix, self.my_reduce_function)
        result = pw.get_result()
        self.checkResult(initCos(), result)

    def test_map_reduce_cos_bucket_one_reducer_per_object(self):
        data_prefix = CONFIG['pywren']['storage_bucket'] + '/' + PREFIX
        pw = pywren.ibm_cf_executor()
        pw.map_reduce(self.my_map_function_bucket, data_prefix, self.my_reduce_function, reducer_one_per_object=True)
        result = pw.get_result()
        self.checkResult(initCos(), result)

    def test_map_reduce_cos_key(self):
        cos = initCos()
        bucket_name = CONFIG['pywren']['storage_bucket']
        iterdata = [bucket_name + '/' + key for key in getFilenamesFromCOS(cos, bucket_name, PREFIX)]
        pw = pywren.ibm_cf_executor()
        pw.map_reduce(self.my_map_function_key, iterdata, self.my_reduce_function)
        result = pw.get_result()
        self.checkResult(cos, result)

    def test_map_reduce_cos_key_one_reducer_per_object(self):
        cos = initCos()
        bucket_name = CONFIG['pywren']['storage_bucket']
        iterdata = [bucket_name + '/' + key for key in getFilenamesFromCOS(cos, bucket_name, PREFIX)]
        pw = pywren.ibm_cf_executor()
        pw.map_reduce(self.my_map_function_key, iterdata, self.my_reduce_function, reducer_one_per_object=True)
        result = pw.get_result()
        self.checkResult(cos, result)

    def test_map_reduce_url(self):
        pw = pywren.ibm_cf_executor()
        pw.map_reduce(self.my_map_function_url, TEST_FILES_URLS, self.my_reduce_function)
        result = pw.get_result()
        self.checkResult(initCos(), result + 1)

    def test_storage_handler(self):
        cos = initCos()
        bucket_name = CONFIG['pywren']['storage_bucket']
        iterdata = [key for key in getFilenamesFromCOS(cos, bucket_name, PREFIX)]
        pw = pywren.ibm_cf_executor()
        pw.map_reduce(self.my_map_function_storage_handler, iterdata, self.my_reduce_function)
        result = pw.get_result()
        self.checkResult(cos, result)

    def test_chunks_bucket(self):
        data_prefix = CONFIG['pywren']['storage_bucket'] + '/' + PREFIX
        pw = pywren.ibm_cf_executor()
        pw.map_reduce(self.my_map_function_bucket, data_prefix, self.my_reduce_function, chunk_size=1 * 1024 ** 2)
        result = pw.get_result()
        self.checkResult(initCos(), result)

    def test_chunks_bucket_one_reducer_per_object(self):
        data_prefix = CONFIG['pywren']['storage_bucket'] + '/' + PREFIX
        pw = pywren.ibm_cf_executor()
        pw.map_reduce(self.my_map_function_bucket, data_prefix, self.my_reduce_function, chunk_size=1 * 1024 ** 2,
                      reducer_one_per_object=True)
        result = pw.get_result()
        self.checkResult(initCos(), result)


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        task = 'full'
    else:
        task = sys.argv[1]

    if task == 'init':
        initTests()
    elif task == 'clean':
        cleanTests()
    else:
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

        runner = unittest.TextTestRunner()
        runner.run(suite)
