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

import pytest
import logging
import lithops
from io import BytesIO
from lithops.config import extract_storage_config
from lithops.storage.utils import CloudObject, StorageNoSuchKeyError
from lithops.tests.conftest import TESTS_PREFIX
from lithops.tests.functions import my_map_function_storage, \
    my_cloudobject_put, my_cloudobject_get, my_reduce_function


logger = logging.getLogger(__name__)

STORAGE_PREFIX = TESTS_PREFIX + '/storage'


class TestStorage:

    @classmethod
    def setup_class(cls):
        storage_config = extract_storage_config(pytest.lithops_config)
        storage = lithops.Storage(storage_config=storage_config)
        cls.storage = storage
        cls.storage_backend = storage.backend
        cls.bucket = storage.bucket
        storage.put_object(cls.bucket, STORAGE_PREFIX + '/test0', BytesIO(b'test storage handler'))
        storage.put_object(cls.bucket, STORAGE_PREFIX + '/test1', BytesIO(b'test storage'))
        cls.words_in_files = 5

    @classmethod
    def teardown_class(cls):
        for key in cls.storage.list_keys(bucket=cls.bucket, prefix=STORAGE_PREFIX):
            cls.storage.delete_object(bucket=cls.bucket, key=key)

    def test_storage_handler(self):
        logger.info('Testing "storage" function arg')
        keys = self.storage.list_keys(bucket=self.bucket, prefix=STORAGE_PREFIX)
        iterdata = [(key, self.bucket) for key in keys]
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_storage, iterdata, my_reduce_function)
        result = fexec.get_result()
        assert result == self.words_in_files

    def test_cloudobject(self):
        logger.info('Testing cloudobjects')
        data_prefix = self.storage_backend + '://' + self.bucket + '/' + STORAGE_PREFIX + '/'
        with lithops.FunctionExecutor(config=pytest.lithops_config) as fexec:
            fexec.map(my_cloudobject_put, data_prefix)
            cloudobjects = fexec.get_result()
            fexec.call_async(my_cloudobject_get, cloudobjects)
            result = fexec.get_result()
            assert result == self.words_in_files
            fexec.clean(cs=cloudobjects)

    def test_put_get_by_stream(self):
        logger.info('Testing Storage.put_object and get_object with streams')

        bytes_data = b'123'
        bytes_key = STORAGE_PREFIX + '/bytes'
        self.storage.put_object(self.bucket, bytes_key, BytesIO(bytes_data))
        bytes_stream = self.storage.get_object(self.bucket, bytes_key, stream=True)

        assert hasattr(bytes_stream, 'read')
        assert bytes_stream.read() == bytes_data

    def test_get_by_range(self):
        logger.info('Testing Storage.get_object with Range argument')
        key = STORAGE_PREFIX + '/bytes'
        self.storage.put_object(self.bucket, key, b'0123456789')

        result = self.storage.get_object(self.bucket, key, extra_get_args={'Range': 'bytes=1-4'})

        assert result == b'1234'

    def test_list_keys(self):
        logger.info('Testing Storage.list_keys')
        test_keys = sorted([
            STORAGE_PREFIX + '/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
            STORAGE_PREFIX + '/foo_bar/baz',
            STORAGE_PREFIX + '/foo_baz',
            STORAGE_PREFIX + '/bar',
            STORAGE_PREFIX + '/bar_baz',
        ])
        for key in test_keys:
            self.storage.put_object(self.bucket, key, key.encode())

        all_bucket_keys = self.storage.list_keys(self.bucket)
        prefix_keys = self.storage.list_keys(self.bucket, STORAGE_PREFIX)
        foo_keys = self.storage.list_keys(self.bucket, STORAGE_PREFIX + '/foo')
        foo_slash_keys = self.storage.list_keys(self.bucket, STORAGE_PREFIX + '/foo/')
        bar_keys = self.storage.list_keys(self.bucket, STORAGE_PREFIX + '/bar')
        non_existent_keys = self.storage.list_keys(self.bucket, STORAGE_PREFIX + '/doesnt_exist')

        assert set(all_bucket_keys).issuperset(test_keys)
        assert set(prefix_keys).issuperset(test_keys)
        assert all(key.startswith(STORAGE_PREFIX) for key in prefix_keys)
        assert sorted(foo_keys) == sorted([
            STORAGE_PREFIX + '/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
            STORAGE_PREFIX + '/foo_bar/baz',
            STORAGE_PREFIX + '/foo_baz',
        ])
        assert sorted(foo_slash_keys) == sorted([
            STORAGE_PREFIX + '/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
        ])
        assert sorted(bar_keys) == sorted([
            STORAGE_PREFIX + '/bar',
            STORAGE_PREFIX + '/bar_baz',
        ])

        assert non_existent_keys == []

    def test_head_object(self):
        logger.info('Testing Storage.head_object')
        data = b'123456789'
        self.storage.put_object(self.bucket, STORAGE_PREFIX + '/data', data)

        result = self.storage.head_object(self.bucket, STORAGE_PREFIX + '/data')
        assert result['content-length'] == str(len(data))

        with pytest.raises(StorageNoSuchKeyError):
            self.storage.head_object(self.bucket, STORAGE_PREFIX + '/doesnt_exist')

    def test_list_objects(self):
        logger.info('Testing Storage.list_objects')
        test_keys = sorted([
            STORAGE_PREFIX + '/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
            STORAGE_PREFIX + '/foo_bar/baz',
            STORAGE_PREFIX + '/foo_baz',
            STORAGE_PREFIX + '/bar',
            STORAGE_PREFIX + '/bar_baz',
        ])
        for key in test_keys:
            self.storage.put_object(self.bucket, key, key.encode())

        all_bucket_objects = self.storage.list_objects(self.bucket)
        prefix_objects = self.storage.list_objects(self.bucket, STORAGE_PREFIX)
        foo_objects = self.storage.list_objects(self.bucket, STORAGE_PREFIX + '/foo')
        foo_slash_objects = self.storage.list_objects(self.bucket, STORAGE_PREFIX + '/foo/')
        bar_objects = self.storage.list_objects(self.bucket, STORAGE_PREFIX + '/bar')
        non_existent_objects = self.storage.list_objects(self.bucket, STORAGE_PREFIX + '/doesnt_exist')

        def extract_keys(bucket_objects):
            keys = []
            for obj in bucket_objects:
                keys.append(obj['Key'])
            return keys

        assert set(extract_keys(all_bucket_objects)).issuperset(test_keys)
        assert set(extract_keys(prefix_objects)).issuperset(test_keys)
        assert all(key.startswith(STORAGE_PREFIX) for key in extract_keys(prefix_objects))
        assert sorted(extract_keys(foo_objects)) == sorted([
            STORAGE_PREFIX + '/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
            STORAGE_PREFIX + '/foo_bar/baz',
            STORAGE_PREFIX + '/foo_baz',
        ])
        assert sorted(extract_keys(foo_slash_objects)) == sorted([
            STORAGE_PREFIX + '/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
        ])
        assert sorted(extract_keys(bar_objects)) == sorted([
            STORAGE_PREFIX + '/bar',
            STORAGE_PREFIX + '/bar_baz',
        ])

        assert non_existent_objects == []

    def test_list_objects_size(self):
        logger.info('Testing Storage.list_objects_size')
        test_keys = sorted([
            STORAGE_PREFIX + '/list/foo/baz',
            STORAGE_PREFIX + '/list/foo/bar/baz',
            STORAGE_PREFIX + '/list/foo_bar/baz',
            STORAGE_PREFIX + '/list/foo_baz',
            STORAGE_PREFIX + '/list/bar',
            STORAGE_PREFIX + '/list/bar_baz',
        ])
        for key in test_keys:
            self.storage.put_object(self.bucket, key, key.encode())

        all_bucket_objects = self.storage.list_objects(self.bucket, prefix=STORAGE_PREFIX + '/list')
        isEqual = all(obj['Size'] == len(obj['Key'].encode()) for obj in all_bucket_objects)
        assert isEqual

    def test_delete_object(self):
        logger.info('Testing Storage.delete_object')
        test_keys = sorted([
            STORAGE_PREFIX + '/delete/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
            STORAGE_PREFIX + '/foo_baz',
            STORAGE_PREFIX + '/bar',
            STORAGE_PREFIX + '/to_be_deleted',
        ])
        for key in test_keys:
            self.storage.put_object(self.bucket, key, key.encode())

        self.storage.delete_object(self.bucket, STORAGE_PREFIX + '/to_be_deleted')
        all_bucket_keys = self.storage.list_keys(self.bucket)
        assert STORAGE_PREFIX + '/to_be_deleted' not in all_bucket_keys

    def test_delete_objects(self):
        logger.info('Testing Storage.delete_objects')
        test_keys = sorted([
            STORAGE_PREFIX + '/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
            STORAGE_PREFIX + '/foo_baz',
            STORAGE_PREFIX + '/bar',
            STORAGE_PREFIX + '/to_be_deleted1',
            STORAGE_PREFIX + '/to_be_deleted2',
            STORAGE_PREFIX + '/to_be_deleted3'
        ])
        keys_to_delete = [
            STORAGE_PREFIX + '/to_be_deleted1',
            STORAGE_PREFIX + '/to_be_deleted2',
            STORAGE_PREFIX + '/to_be_deleted3'
        ]
        for key in test_keys:
            self.storage.put_object(self.bucket, key, key.encode())

        self.storage.delete_objects(self.bucket, keys_to_delete)
        all_bucket_keys = self.storage.list_keys(self.bucket)
        assert all(key not in all_bucket_keys for key in keys_to_delete)

    def test_head_bucket(self):
        logger.info('Testing Storage.head_bucket')
        result = self.storage.head_bucket(self.bucket)
        assert result['ResponseMetadata']['HTTPStatusCode'] == 200

    def test_delete_cloudobject(self):
        logger.info('Testing Storage.delete_cloudobject')
        test_keys = sorted([
            STORAGE_PREFIX + '/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
            STORAGE_PREFIX + '/foo_baz',
            STORAGE_PREFIX + '/bar',
            STORAGE_PREFIX + '/to_be_deleted',
        ])
        for key in test_keys:
            self.storage.put_object(self.bucket, key, key.encode())
        cloudobject = CloudObject(self.storage_backend, self.bucket, STORAGE_PREFIX + '/to_be_deleted')
        self.storage.delete_cloudobject(cloudobject)
        all_bucket_keys = self.storage.list_keys(self.bucket)
        assert STORAGE_PREFIX + '/to_be_deleted' not in all_bucket_keys

    def test_delete_cloudobjects(self):
        logger.info('Testing Storage.delete_cloudobjects')
        test_keys = sorted([
            STORAGE_PREFIX + '/foo/baz',
            STORAGE_PREFIX + '/foo/bar/baz',
            STORAGE_PREFIX + '/foo_baz',
            STORAGE_PREFIX + '/bar',
            STORAGE_PREFIX + '/to_be_deleted1',
            STORAGE_PREFIX + '/to_be_deleted2',
            STORAGE_PREFIX + '/to_be_deleted3'
        ])
        cloudobjects = []
        keys_to_delete = [
            STORAGE_PREFIX + '/to_be_deleted1',
            STORAGE_PREFIX + '/to_be_deleted2',
            STORAGE_PREFIX + '/to_be_deleted3'
        ]
        for key in keys_to_delete:
            cobject = CloudObject(self.storage_backend, self.bucket, key)
            cloudobjects.append(cobject)
        for key in test_keys:
            self.storage.put_object(self.bucket, key, key.encode())

        self.storage.delete_cloudobjects(cloudobjects)
        all_bucket_keys = self.storage.list_keys(self.bucket)
        assert all(key not in all_bucket_keys for key in keys_to_delete)
