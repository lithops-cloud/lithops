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
import logging
import lithops
from lithops.tests.conftest import DATASET_PREFIX, PREFIX, TEST_FILES_URLS
from lithops.config import extract_storage_config
from lithops.tests.functions import (
    simple_reduce_function,
    my_reduce_function,
    simple_map_function,
    my_map_function_obj,
    my_map_function_url
)


logger = logging.getLogger(__name__)


class TestMapReduce:

    @classmethod
    def setup_class(cls):
        storage_config = extract_storage_config(pytest.lithops_config)
        storage = lithops.Storage(storage_config=storage_config)
        cls.storage = storage
        cls.storage_backend = storage.backend
        cls.bucket = storage.bucket

    def test_map_reduce(self):
        logger.info('Testing map_reduce() using memory')
        iterdata = [(1, 1), (2, 2), (3, 3), (4, 4)]
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(simple_map_function, iterdata,
                         simple_reduce_function)
        result = fexec.get_result()
        assert result == 20

    def test_map_reduce_obj_bucket(self):
        logger.info('Testing map_reduce() over a bucket')
        data_prefix = self.storage_backend + '://' + self.bucket + '/' + DATASET_PREFIX + '/'
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_obj, data_prefix,
                         my_reduce_function)
        result = fexec.get_result()
        assert result == pytest.words_in_files

    def test_map_reduce_obj_bucket_reduce_by_key(self):
        logger.info('Testing map_reduce() over a bucket with one reducer per object')
        data_prefix = self.storage_backend + '://' + self.bucket + '/' + DATASET_PREFIX + '/'
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_obj, data_prefix,
                         my_reduce_function,
                         obj_reduce_by_key=True)
        result = fexec.get_result()
        assert sum(result) == pytest.words_in_files

    def test_map_reduce_obj_key(self):
        logger.info('Testing map_reduce() over object keys')
        keys = self.storage.list_keys(bucket=self.bucket, prefix=PREFIX + '/')
        iterdata = [self.storage_backend + '://' + self.bucket + '/' + key for key in keys]
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_obj, iterdata,
                         my_reduce_function)
        result = fexec.get_result()
        assert result == pytest.words_in_files

    def test_map_reduce_obj_key_reduce_by_key(self):
        logger.info('Testing map_reduce() over object keys with one reducer per object')
        keys = self.storage.list_keys(bucket=self.bucket, prefix=PREFIX + '/')
        iterdata = [self.storage_backend + '://' + self.bucket + '/' + key for key in keys]
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_obj, iterdata,
                         my_reduce_function,
                         obj_reduce_by_key=True)
        result = fexec.get_result()
        assert sum(result) == pytest.words_in_files

    def test_map_reduce_url(self):
        logger.info('Testing map_reduce() over URLs')
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map_reduce(my_map_function_url, TEST_FILES_URLS,
                         my_reduce_function, obj_chunk_number=2)
        result = fexec.get_result()
        assert result == pytest.words_in_files

    def test_chunks_bucket(self):
        """tests the ability to create a separate function invocation based on the following parameters:
         chunk_size - creates [file_size//chunk_size] invocations to process each chunk_size bytes, of a given object.
         chunk_number - creates 'chunk_number' invocations that process [file_size//chunk_number] bytes each. """

        logger.info('Testing chunks on a bucket')
        OBJ_CHUNK_SIZE = 1 * 800 ** 2  # create a new invocation
        OBJ_CHUNK_NUMBER = 2
        activations = 0

        data_prefix = self.storage_backend + '://' + self.bucket + '/' + DATASET_PREFIX + '/'

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(my_map_function_obj, data_prefix,
                                   my_reduce_function,
                                   obj_chunk_size=OBJ_CHUNK_SIZE)
        result = fexec.get_result(futures)
        assert result == pytest.words_in_files

        for size in get_dataset_key_size(self.storage, self.bucket):
            activations += math.ceil(size / OBJ_CHUNK_SIZE)

        assert len(futures) == activations + 1  # +1 due to the reduce function

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(my_map_function_obj, data_prefix,
                                   my_reduce_function, obj_chunk_number=OBJ_CHUNK_NUMBER)
        result = fexec.get_result(futures)
        assert result == pytest.words_in_files

        assert len(futures) == len(TEST_FILES_URLS) * OBJ_CHUNK_NUMBER + 1

    def test_chunks_bucket_one_reducer_per_object(self):
        """tests the ability to create a separate function invocation based on the following parameters, as well as
         create a separate invocation of a reduce function for each object:
         chunk_size - creates [file_size//chunk_size] invocations to process each chunk_size bytes, of a given object.
         chunk_number - creates 'chunk_number' invocations that process [file_size//chunk_number] bytes each. """

        logger.info('Testing chunks on a bucket with one reducer per object')
        OBJ_CHUNK_SIZE = 1 * 1024 ** 2
        OBJ_CHUNK_NUMBER = 2
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
        assert sum(result) == pytest.words_in_files

        for size in get_dataset_key_size(self.storage, self.bucket):
            activations += math.ceil(size / OBJ_CHUNK_SIZE)

        # + len(TEST_FILES_URLS) due to map_reduce activation per object
        assert len(futures) == activations + len(TEST_FILES_URLS)

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(
            my_map_function_obj,
            data_prefix,
            my_reduce_function,
            obj_chunk_number=OBJ_CHUNK_NUMBER,
            obj_reduce_by_key=True
        )
        result = fexec.get_result(futures)
        assert sum(result) == pytest.words_in_files
        # + len(TEST_FILES_URLS) due to map_reduce activation per object
        assert len(futures) == len(TEST_FILES_URLS) * OBJ_CHUNK_NUMBER + len(TEST_FILES_URLS)


def get_dataset_key_size(storage, bucket):
    """return a list of file sizes in bytes, belonging to files whose names are
    prefixed by 'prefix' """
    sizes = []
    keys = storage.list_keys(bucket=bucket, prefix=PREFIX + '/')
    for key in keys:
        sizes.append(float(storage.head_object(bucket, key)['content-length']))
    return sizes
