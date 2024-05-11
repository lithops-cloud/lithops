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

import pytest
import math
import base64
import urllib
import logging
import lithops
from concurrent.futures import ThreadPoolExecutor
from lithops.tests.conftest import TESTS_PREFIX
from lithops.config import extract_storage_config
from lithops.tests.functions import (
    simple_reduce_function,
    my_reduce_function,
    simple_map_function,
    my_map_function_obj,
    my_map_function_url
)


DATASET_PREFIX = TESTS_PREFIX + '/dataset'
base64_bytes = 'aHR0cHM6Ly9zMy1ldS13ZXN0LTEuYW1hem9uYXdzLmNvbS9hcnRtLw=='.encode('ascii')
TEST_FILES_REPO = base64.b64decode(base64_bytes).decode('ascii')
TEST_FILES_URLS = [
    TEST_FILES_REPO + "vocab.enron.txt",
    TEST_FILES_REPO + "vocab.kos.txt",
    TEST_FILES_REPO + "vocab.nips.txt",
    TEST_FILES_REPO + "vocab.nytimes.txt",
    TEST_FILES_REPO + "vocab.pubmed.txt"
]

logger = logging.getLogger(__name__)


class TestMapReduce:

    @classmethod
    def setup_class(cls):
        storage_config = extract_storage_config(pytest.lithops_config)
        storage = lithops.Storage(storage_config=storage_config)
        cls.words_in_files = upload_data_sets(storage)
        cls.storage = storage
        cls.storage_backend = storage.backend
        cls.bucket = storage.bucket

    @classmethod
    def teardown_class(cls):
        for key in cls.storage.list_keys(bucket=cls.bucket, prefix=DATASET_PREFIX):
            cls.storage.delete_object(bucket=cls.bucket, key=key)

    def test_simple_map_reduce(self):
        logger.info('Testing map_reduce() using memory')
        iterdata = [(1, 1), (2, 2), (3, 3), (4, 4)]
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(simple_map_function, iterdata, simple_reduce_function)
        result = fexec.get_result()
        assert result == 20

    def test_obj_bucket(self):
        logger.info('Testing map_reduce() over a bucket')
        data_prefix = self.storage_backend + '://' + self.bucket + '/' + DATASET_PREFIX + '/'
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_obj, data_prefix,
                         my_reduce_function)
        result = fexec.get_result()
        assert result == self.words_in_files

    def test_obj_bucket_reduce_by_key(self):
        logger.info('Testing map_reduce() over a bucket with one reducer per object')
        data_prefix = self.storage_backend + '://' + self.bucket + '/' + DATASET_PREFIX + '/'
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_obj, data_prefix,
                         my_reduce_function, obj_reduce_by_key=True)
        result = fexec.get_result()
        assert sum(result) == self.words_in_files

    def test_obj_key(self):
        logger.info('Testing map_reduce() over object keys')
        keys = self.storage.list_keys(bucket=self.bucket, prefix=DATASET_PREFIX + '/')
        iterdata = [self.storage_backend + '://' + self.bucket + '/' + key for key in keys]
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_obj, iterdata, my_reduce_function)
        result = fexec.get_result()
        assert result == self.words_in_files

    def test_obj_key_reduce_by_key(self):
        logger.info('Testing map_reduce() over object keys with one reducer per object')
        keys = self.storage.list_keys(bucket=self.bucket, prefix=DATASET_PREFIX + '/')
        iterdata = [self.storage_backend + '://' + self.bucket + '/' + key for key in keys]
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_obj, iterdata,
                         my_reduce_function, obj_reduce_by_key=True)
        result = fexec.get_result()
        assert sum(result) == self.words_in_files

    def test_url_processing(self):
        logger.info('Testing map_reduce() over URLs')
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_url, TEST_FILES_URLS,
                         my_reduce_function, obj_chunk_number=2)
        result = fexec.get_result()
        assert result == self.words_in_files

    def test_bucket_chunk_size(self):
        """tests the ability to create a separate function invocation
        based on the following parameters: chunk_size creates [file_size//chunk_size]
        invocations to process each chunk_size bytes, of a given object.
        """
        OBJ_CHUNK_SIZE = 1 * 800 ** 2  # create a new invocation
        activations = 0

        data_prefix = self.storage_backend + '://' + self.bucket + '/' + DATASET_PREFIX + '/'

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(
            my_map_function_obj, data_prefix,
            my_reduce_function, obj_chunk_size=OBJ_CHUNK_SIZE
        )
        result = fexec.get_result(futures)
        assert result == self.words_in_files

        for size in get_dataset_key_size(self.storage, self.bucket):
            activations += math.ceil(size / OBJ_CHUNK_SIZE)

        assert len(futures) == activations + 1  # +1 due to the reduce function

    def test_bucket_chunk_number(self):
        """tests the ability to create a separate function invocation
        based on the following parameters: chunk_number
        creates 'chunk_number' invocations that process [file_size//chunk_number] bytes each.
        """
        OBJ_CHUNK_NUMBER = 2

        data_prefix = self.storage_backend + '://' + self.bucket + '/' + DATASET_PREFIX + '/'

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(
            my_map_function_obj, data_prefix,
            my_reduce_function, obj_chunk_number=OBJ_CHUNK_NUMBER
        )
        result = fexec.get_result(futures)
        assert result == self.words_in_files

        assert len(futures) == len(TEST_FILES_URLS) * OBJ_CHUNK_NUMBER + 1

    def test_bucket_chunk_size_one_reducer_per_object(self):
        """tests the ability to create a separate function invocation based
        on the following parameters, as well as create a separate invocation
        of a reduce function for each object: chunk_size creates [file_size//chunk_size]
        invocations to process each chunk_size bytes, of a given object. hunk_number
        creates 'chunk_number' invocations that process [file_size//chunk_number] bytes each.
        """
        OBJ_CHUNK_SIZE = 1 * 1024 ** 2
        activations = 0
        data_prefix = self.storage_backend + '://' + self.bucket + '/' + DATASET_PREFIX + '/'

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(
            my_map_function_obj, data_prefix,
            my_reduce_function,
            obj_chunk_size=OBJ_CHUNK_SIZE,
            obj_reduce_by_key=True
        )
        result = fexec.get_result(futures)
        assert sum(result) == self.words_in_files

        for size in get_dataset_key_size(self.storage, self.bucket):
            activations += math.ceil(size / OBJ_CHUNK_SIZE)

        # + len(TEST_FILES_URLS) due to map_reduce activation per object
        assert len(futures) == activations + len(TEST_FILES_URLS)

    def test_bucket_chunk_number_one_reducer_per_object(self):
        """tests the ability to create a separate function invocation based
        on the following parameters, as well as create a separate invocation
        of a reduce function for each object: chunk_size creates [file_size//chunk_size]
        invocations to process each chunk_size bytes, of a given object. hunk_number
        creates 'chunk_number' invocations that process [file_size//chunk_number] bytes each.
        """
        OBJ_CHUNK_NUMBER = 2
        data_prefix = self.storage_backend + '://' + self.bucket + '/' + DATASET_PREFIX + '/'

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(
            my_map_function_obj,
            data_prefix,
            my_reduce_function,
            obj_chunk_number=OBJ_CHUNK_NUMBER,
            obj_reduce_by_key=True
        )
        result = fexec.get_result(futures)
        assert sum(result) == self.words_in_files
        # + len(TEST_FILES_URLS) due to map_reduce activation per object
        assert len(futures) == len(TEST_FILES_URLS) * OBJ_CHUNK_NUMBER + len(TEST_FILES_URLS)


def get_dataset_key_size(storage, bucket):
    """return a list of file sizes in bytes, belonging to files whose names are
    prefixed by 'prefix' """
    sizes = []
    keys = storage.list_keys(bucket=bucket, prefix=DATASET_PREFIX + '/')
    for key in keys:
        sizes.append(float(storage.head_object(bucket, key)['content-length']))
    return sizes


def upload_data_sets(storage):
    """
    Uploads datasets to storage and return a list of
    the number of words within each test file
    """
    def up(param):
        dataset_name = param[1].split("/")[-1]
        logger.info(f'Uploading bag-of-words dataset: {dataset_name}')
        i, url = param
        content = urllib.request.urlopen(url).read()
        storage.put_object(bucket=storage.bucket,
                           key=f'{DATASET_PREFIX}/{dataset_name}',
                           body=content)
        return len(content.split())

    with ThreadPoolExecutor() as pool:
        results = list(pool.map(up, enumerate(TEST_FILES_URLS)))

    return sum(results)
