#
# Copyright 2018 PyWren Team
# Copyright IBM Corp. 2020
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

import os
import time
import logging
from typing import Any, List

from lithops.constants import JOBS_PREFIX


logger = logging.getLogger(__name__)


func_key_suffix = "func.pickle"
agg_data_key_suffix = "aggdata.pickle"
data_key_suffix = "data.pickle"
output_key_suffix = "output.pickle"
status_key_suffix = "status.json"
init_key_suffix = ".init"


class StorageNoSuchKeyError(Exception):
    """Raised when a key a caller asked for is not in the storage backend"""

    def __init__(self, bucket: str, key: str):
        msg = f"No such key /{bucket}/{key} found in storage."
        super().__init__(msg)


class StorageConfigMismatchError(Exception):
    """
    Raised when the data of a previous run lives in a different backend or
    bucket than the one currently configured
    """

    def __init__(self, current_path: List[str], prev_path: List[str]):
        msg = (
            f"The data is stored at {prev_path}, but current storage "
            f"is configured at {current_path}"
        )
        super().__init__(msg)


class CloudObject:
    """Reference to an object in a storage backend"""

    def __init__(self, backend: str, bucket: str, key: str):
        self.backend = backend
        self.bucket = bucket
        self.key = key

    def __str__(self):
        path = f'{self.backend}://{self.bucket}/{self.key}'
        return f'<CloudObject at {path}>'


class CloudObjectUrl:
    """Reference to an object named by its URL"""

    def __init__(self, url: str):
        self.url = url

    def __str__(self):
        return f'<CloudObject at {self.url}>'


class CloudObjectLocal:
    """Reference to an object that lives in the local filesystem"""

    def __init__(self, path: str):
        self.path = path
        self.bucket = os.path.dirname(path)
        self.key = os.path.basename(path)

    def __str__(self):
        return f'<CloudObject at {self.path}>'


def clean_bucket(
    storage: Any, bucket: str, prefix: str, sleep: int = 5
) -> None:
    """
    Deletes every object under a prefix, which is where the serialized
    function, its data and its results live. Lists again after each batch,
    because a backend may report keys that the previous delete had not
    applied yet
    """
    msg = f"Deleting objects from bucket '{bucket}'"
    if prefix:
        msg = f"{msg} and prefix '{prefix}'"
    logger.info(msg)
    total_objects = 0
    objects_to_delete = storage.list_keys(bucket, prefix)

    while objects_to_delete:
        total_objects += len(objects_to_delete)
        storage.delete_objects(bucket, objects_to_delete)
        time.sleep(sleep)
        objects_to_delete = storage.list_keys(bucket, prefix)

    logger.info(f'Finished deleting objects, total found: {total_objects}')


def create_job_key(executor_id: str, job_id: str) -> str:
    """Returns the key that identifies a job, shared by all of its calls"""
    return '-'.join([executor_id, job_id])


def _jobs_key(*parts: str) -> str:
    return '/'.join((JOBS_PREFIX, *parts))


def create_func_key(executor_id: str, function_hash: str) -> str:
    """
    Returns the key of a serialized function. The hash is part of the key, so
    that the same function is uploaded only once per executor
    """
    return _jobs_key(executor_id, f'{function_hash}.{func_key_suffix}')


def create_data_key(executor_id: str, job_id: str) -> str:
    """Returns the key of the aggregated data of every call of a job"""
    return _jobs_key(create_job_key(executor_id, job_id), agg_data_key_suffix)


def create_output_key(executor_id: str, job_id: str, call_id: str) -> str:
    """Returns the key the result of a single call is written to"""
    return _jobs_key(
        create_job_key(executor_id, job_id), call_id, output_key_suffix
    )


def create_status_key(executor_id: str, job_id: str, call_id: str) -> str:
    """Returns the key the final status of a single call is written to"""
    return _jobs_key(
        create_job_key(executor_id, job_id), call_id, status_key_suffix
    )


def create_init_key(
    executor_id: str, job_id: str, call_id: str, act_id: str
) -> str:
    """
    Returns the key a call writes when it starts running. The activation id
    is part of the key, so that a retried call does not overwrite the mark of
    the attempt that came before it
    """
    return _jobs_key(
        create_job_key(executor_id, job_id),
        call_id,
        f'{act_id}{init_key_suffix}',
    )


def get_storage_path(storage_config: dict) -> List[str]:
    """Returns the backend and the bucket the data of a run lives in"""
    backend = storage_config['backend']
    bucket = storage_config[backend]['storage_bucket']
    return [backend, bucket]


def check_storage_path(storage_config: dict, prev_path: List[str]) -> None:
    """
    Makes sure the configured storage is the one a previous run used, as data
    written elsewhere is not reachable from here
    """
    current_path = get_storage_path(storage_config)
    if current_path != prev_path:
        raise StorageConfigMismatchError(current_path, prev_path)
