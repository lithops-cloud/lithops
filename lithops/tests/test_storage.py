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


import unittest
import logging
from io import BytesIO
from lithops.storage.utils import StorageNoSuchKeyError
import lithops
from lithops.tests import main_util
from lithops.tests.util_func.map_reduce_util import my_reduce_function
from lithops.tests.util_func.storage_util import my_map_function_storage, my_cloudobject_put, my_cloudobject_get, \
    list_dataset_keys

logger = logging.getLogger(__name__)

CONFIG = None
STORAGE_CONFIG = None
STORAGE = None
TEST_FILES_URLS = None
PREFIX = '__lithops.test'
DATASET_PREFIX = PREFIX + '/dataset'


class TestStorage(unittest.TestCase):
    words_in_cos_files = None

    @classmethod
    def setUpClass(cls):
        global CONFIG, STORAGE, STORAGE_CONFIG, TEST_FILES_URLS

        CONFIG, STORAGE, STORAGE_CONFIG = main_util.get_config().values()
        TEST_FILES_URLS = main_util.get_data_sets()
        cls.words_in_cos_files = main_util.get_words_in_files()

    @classmethod
    def setUp(cls):
        print('\n-------------------------------------------------------------\n')

    def test_storage_handler(self):
        logger.info('Testing "storage" function arg')
        iterdata = [(key, STORAGE_CONFIG['bucket']) for key in list_dataset_keys(STORAGE, STORAGE_CONFIG)]
        fexec = lithops.FunctionExecutor(config=CONFIG)
        fexec.map_reduce(my_map_function_storage, iterdata,
                         my_reduce_function)
        result = fexec.get_result()
        self.assertEqual(result, self.__class__.words_in_cos_files)

    def test_cloudobject(self):
        logger.info('Testing cloudobjects')
        sb = STORAGE_CONFIG['backend']
        data_prefix = sb + '://' + STORAGE_CONFIG['bucket'] + '/' + DATASET_PREFIX + '/'
        with lithops.FunctionExecutor(config=CONFIG) as fexec:
            fexec.map(my_cloudobject_put, data_prefix)
            cloudobjects = fexec.get_result()
            fexec.call_async(my_cloudobject_get, cloudobjects)
            result = fexec.get_result()
            self.assertEqual(result, self.__class__.words_in_cos_files)
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
