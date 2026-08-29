#
# (C) Copyright IBM Corp. 2020
# (C) Copyright Cloudlab URV 2020
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
import json
import logging
import itertools
import importlib
from typing import Optional, List, Union, Dict, TextIO, BinaryIO, Any, Iterable

from lithops.constants import CACHE_DIR, RUNTIMES_PREFIX, JOBS_PREFIX, TEMP_PREFIX
from lithops.utils import is_lithops_worker
from lithops.storage import utils
from lithops.config import extract_storage_config, default_storage_config

logger = logging.getLogger(__name__)


RUNTIME_META_CACHE = {}
COBJECTS_INDEX = itertools.count()
_INVALID_CO_BACKEND = "CloudObject: Invalid Storage backend"


class Storage:
    """
    A Storage object is used by the partitioner and other components to access
    the underlying storage backend without exposing the implementation details.
    """

    def __init__(self, config=None, backend=None, storage_config=None):
        """ Creates a Storage instance

        :param config: lithops configuration dict
        :param backend: storage backend name
        :param storage_config: storage configuration dict

        :return: Storage instance.
        """
        if storage_config:
            self.config = storage_config
        else:
            self.config = extract_storage_config(
                default_storage_config(config_data=config, backend=backend)
            )

        self.backend = self.config['backend']

        try:
            sb_module = importlib.import_module(
                f'lithops.storage.backends.{self.backend}'
            )
            StorageBackend = getattr(sb_module, 'StorageBackend')
            self.storage_handler = StorageBackend(self.config[self.backend])
        except Exception:
            logger.error(
                "There was an error trying to create the "
                f"'{self.backend}' storage backend",
                exc_info=True,
            )
            raise

        bucket = self.config[self.backend].get('storage_bucket')
        self.bucket = bucket or self.storage_handler.generate_bucket_name()

    def get_client(self) -> object:
        """
        Retrieves the underlying storage client.

        :return: Storage backend client
        """
        return self.storage_handler.get_client()

    def get_storage_config(self) -> Dict:
        """
        Retrieves the configuration of this storage handler.

        :return: Storage configuration
        """
        return self.config

    def create_bucket(self, bucket: str):
        """
        Creates a bucket if it does not exist. Backends that create their
        buckets on their own do nothing here.

        :param bucket: Name of the bucket
        """
        if hasattr(self.storage_handler, 'create_bucket'):
            return self.storage_handler.create_bucket(bucket)

    def put_object(self, bucket: str, key: str,
                   body: Union[str, bytes, TextIO, BinaryIO]):
        """
        Adds an object to a bucket of the storage backend.

        :param bucket: Name of the bucket
        :param key: Key of the object
        :param body: Object data
        """
        return self.storage_handler.put_object(bucket, key, body)

    def get_object(self, bucket: str, key: str, stream: Optional[bool] = False,
                   extra_get_args: Optional[Dict] = {}) -> Union[
                       str, bytes, TextIO, BinaryIO]:
        """
        Retrieves objects from the storage backend.

        :param bucket: Name of the bucket
        :param key: Key of the object
        :param stream: Get the object data or a file-like object
        :param extra_get_args: Extra get arguments to be passed to the
            underlying backend implementation (dict). For example, to specify
            the byte-range to read: ``extra_get_args={'Range': 'bytes=0-100'}``.

        :return: Object, as a binary array or as a file-like stream if
            parameter `stream` is enabled
        """
        return self.storage_handler.get_object(
            bucket, key, stream, extra_get_args
        )

    def upload_file(self, file_name: str, bucket: str,
                    key: Optional[str] = None,
                    extra_args: Optional[Dict] = {},
                    config: Optional[Any] = None) -> Union[
                        str, bytes, TextIO, BinaryIO]:
        """
        Uploads a file to a bucket of the storage backend. (Multipart upload)

        :param file_name: Name of the file to upload
        :param bucket: Name of the bucket
        :param key: Key of the object
        :param extra_args: Extra get arguments to be passed to the underlying
            backend implementation (dict).
        :param config: The transfer configuration to be used when performing
            the transfer (boto3.s3.transfer.TransferConfig).
        """
        return self.storage_handler.upload_file(
            file_name, bucket, key, extra_args, config
        )

    def download_file(self, bucket: str, key: str,
                      file_name: Optional[str] = None,
                      extra_args: Optional[Dict] = {},
                      config: Optional[Any] = None) -> Union[
                          str, bytes, TextIO, BinaryIO]:
        """
        Downloads a file from the storage backend. (Multipart download)

        :param bucket: Name of the bucket
        :param key: Key of the object
        :param file_name: Name of the file to save the object data
        :param extra_args: Extra get arguments to be passed to the underlying
            backend implementation (dict).
        :param config: The transfer configuration to be used when performing
            the transfer (boto3.s3.transfer.TransferConfig).

        :return: Object, as a binary array or as a file-like stream if
            parameter `stream` is enabled
        """
        return self.storage_handler.download_file(
            bucket, key, file_name, extra_args, config
        )

    def head_object(self, bucket: str, key: str) -> Dict:
        """
        The HEAD operation retrieves metadata from an object without returning
        the object itself. This operation is useful if you're only interested
        in an object's metadata.

        :param bucket: Name of the bucket
        :param key: Key of the object

        :return: Object metadata
        """
        return self.storage_handler.head_object(bucket, key)

    def delete_object(self, bucket: str, key: str):
        """
        Removes objects from the storage backend.

        :param bucket: Name of the bucket
        :param key: Key of the object
        """
        return self.storage_handler.delete_object(bucket, key)

    def delete_objects(self, bucket: str, key_list: List[str]):
        """
        This operation enables you to delete multiple objects from a bucket
        using a single HTTP request. If you know the object keys that you want
        to delete, then this operation provides a suitable alternative to
        sending individual delete requests, reducing per-request overhead.

        :param bucket: Name of the bucket
        :param key_list: List of object keys
        """
        return self.storage_handler.delete_objects(bucket, key_list)

    def head_bucket(self, bucket: str) -> Dict:
        """
        This operation is useful to determine if a bucket exists and you have
        permission to access it. The operation returns a 200 OK if the bucket
        exists and you have permission to access it. Otherwise, the operation
        might return responses such as 404 Not Found and 403 Forbidden.

        :param bucket: Name of the bucket

        :return: Request response
        """
        return self.storage_handler.head_bucket(bucket)

    def list_objects(self, bucket: str, prefix: Optional[str] = None,
                     match_pattern: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Returns all of the object keys in a bucket. For each object, the list
        contains a dictionary with at least the object key ('Key') and the size
        in bytes ('Size'). Additional fields may be present, depending on the
        backend implementation.

        :param bucket: Name of the bucket
        :param prefix: Key prefix for filtering

        :return: List of dictionaries containing at least 'Key' and 'Size'
            for each object
        """
        return self.storage_handler.list_objects(bucket, prefix, match_pattern)

    def list_keys(self, bucket, prefix=None) -> List[str]:
        """
        Similar to list_objects(), it returns all of the object keys in a
        bucket. For each object, the list contains only the names of the
        objects (keys).

        :param bucket: Name of the bucket
        :param prefix: Key prefix for filtering

        :return: List of object keys
        """
        return self.storage_handler.list_keys(bucket, prefix)

    def _cloudobject_location(self, cloudobject: utils.CloudObject):
        """Returns the bucket and the key a CloudObject of this backend lives in"""
        if cloudobject.backend != self.backend:
            raise Exception(_INVALID_CO_BACKEND)
        return cloudobject.bucket, cloudobject.key

    def put_cloudobject(self, body: Union[str, bytes, TextIO, BinaryIO],
                        bucket: Optional[str] = None,
                        key: Optional[str] = None) -> utils.CloudObject:
        """
        Puts a CloudObject into storage.

        :param body: Data content, can be a string or byte array or a
            text/bytes file-like object
        :param bucket: Destination bucket
        :param key: Destination key

        :return: CloudObject instance
        """
        prefix = os.environ.get('__LITHOPS_SESSION_ID', '')
        coid = hex(next(COBJECTS_INDEX))[2:]
        coname = f'cloudobject_{coid}'
        name = '/'.join([prefix, coname]) if prefix else coname
        key = key or '/'.join([TEMP_PREFIX, name])
        bucket = bucket or self.bucket
        self.storage_handler.put_object(bucket, key, body)
        return utils.CloudObject(self.backend, bucket, key)

    def get_cloudobject(self, cloudobject: utils.CloudObject,
                        stream: Optional[bool] = False) -> Union[
                            str, bytes, TextIO, BinaryIO]:
        """
        Gets the content of a CloudObject from storage.

        :param cloudobject: CloudObject instance
        :param stream: Get the object data or a file-like object

        :return: Cloud object content
        """
        bucket, key = self._cloudobject_location(cloudobject)
        return self.storage_handler.get_object(bucket, key, stream=stream)

    def delete_cloudobject(self, cloudobject: utils.CloudObject):
        """
        Deletes a CloudObject from storage.

        :param cloudobject: CloudObject instance
        """
        bucket, key = self._cloudobject_location(cloudobject)
        return self.storage_handler.delete_object(bucket, key)

    def delete_cloudobjects(self, cloudobjects: List[utils.CloudObject]):
        """
        Deletes multiple CloudObjects from storage.

        :param cloudobjects: List of CloudObject instances
        """
        keys_per_bucket = {}
        for co in cloudobjects:
            # Checked before deleting anything, so that a foreign object in
            # the list does not leave the others half deleted
            if co.backend != self.backend:
                raise Exception(_INVALID_CO_BACKEND)
            keys_per_bucket.setdefault(co.bucket, []).append(co.key)

        for bucket, keys in keys_per_bucket.items():
            self.storage_handler.delete_objects(bucket, keys)


class InternalStorage:
    """
    An InternalStorage object is used by executors and other components to
    access the underlying storage backend without exposing the implementation
    details. Every key it reads and writes lives in the configured bucket
    """

    def __init__(self, storage_config: Dict[str, Any]):
        self.storage = Storage(storage_config=storage_config)
        self.backend = self.storage.backend
        self.bucket = self.storage.bucket

        if not self.bucket:
            raise Exception(
                f"'storage_bucket' is mandatory under '{self.backend}'"
                " section of the configuration"
            )

        self.storage.create_bucket(self.bucket)

    def get_client(self):
        """Returns the client of the underlying storage backend"""
        return self.storage.get_client()

    def get_storage_config(self):
        """Returns the configuration of this storage handler"""
        return self.storage.get_storage_config()

    def put_data(self, key, data):
        """Writes the data of a job"""
        return self.storage.put_object(self.bucket, key, data)

    def put_func(self, key, func):
        """Writes a serialized function"""
        return self.storage.put_object(self.bucket, key, func)

    def get_data(self, key, stream=False, extra_get_args={}):
        """Reads the data of a job, as bytes or as a stream"""
        return self.storage.get_object(self.bucket, key, stream, extra_get_args)

    def get_func(self, key):
        """Reads a serialized function"""
        return self.storage.get_object(self.bucket, key)

    def del_data(self, key):
        """Deletes the data of a job"""
        return self.storage.delete_object(self.bucket, key)

    def get_job_status(self, executor_id, job_ids: Optional[Iterable[str]] = None):
        """
        Returns the ids of the calls that have started and of the ones that
        have finished, as two sets.

        Listing the prefix of each given job keeps finished jobs out of the
        listing; without job_ids the whole executor prefix is listed
        """
        if job_ids:
            keys = []
            for job_id in job_ids:
                prefix = '/'.join([
                    JOBS_PREFIX, utils.create_job_key(executor_id, job_id)
                ])
                keys.extend(self.storage.list_keys(self.bucket, prefix))
        else:
            callset_prefix = '/'.join([JOBS_PREFIX, executor_id])
            keys = self.storage.list_keys(self.bucket, callset_prefix)

        running_keys = [
            k.split('/') for k in keys if utils.init_key_suffix in k
        ]
        running_callids = [
            (
                tuple(k[1].rsplit("-", 1) + [k[2]]),
                k[3].replace(utils.init_key_suffix, ''),
            )
            for k in running_keys
        ]

        done_keys = [
            k.split('/')[1:] for k in keys if utils.status_key_suffix in k
        ]
        done_callids = [
            tuple(k[0].rsplit("-", 1) + [k[1]]) for k in done_keys
        ]

        return set(running_callids), set(done_callids)

    def get_call_status(self, executor_id, job_id, call_id):
        """
        Returns the status of a single call, or None while it has not been
        written yet
        """
        status_key = utils.create_status_key(executor_id, job_id, call_id)
        try:
            data = self.storage.get_object(self.bucket, status_key)
            return json.loads(data.decode('ascii'))
        except utils.StorageNoSuchKeyError:
            return None

    def get_call_output(self, executor_id, job_id, call_id):
        """
        Returns the serialized result of a single call, or None while it has
        not been written yet
        """
        output_key = utils.create_output_key(executor_id, job_id, call_id)
        try:
            return self.storage.get_object(self.bucket, output_key)
        except utils.StorageNoSuchKeyError:
            return None

    def _runtime_meta_refs(self, key):
        """
        Returns where the metadata of a runtime lives: the path parts of the
        local cache file, the key of the in-memory cache, and the storage key,
        which is posix even when the local path is not
        """
        path = [RUNTIMES_PREFIX, key + ".meta.json"]
        cache_key = '/'.join(path)
        return path, cache_key, cache_key.replace('\\', '/')

    def _local_runtime_meta_path(self, key):
        """Returns the path of the local disk cache file of a runtime"""
        path, _, _ = self._runtime_meta_refs(key)
        return os.path.join(CACHE_DIR, *path)

    def _write_runtime_meta_file(self, filename_local_path, runtime_meta):
        """Writes the metadata of a runtime to the local disk cache"""
        os.makedirs(os.path.dirname(filename_local_path), exist_ok=True)
        with open(filename_local_path, "w") as f:
            f.write(json.dumps(runtime_meta))

    def _cached_runtime_meta(self, cache_key, filename_local_path):
        """
        Returns the metadata of a runtime from the memory cache, or from the
        disk cache, which a worker does not use because its disk is not the
        one that wrote it
        """
        if cache_key in RUNTIME_META_CACHE:
            logger.debug("Runtime metadata found in local memory cache")
            return RUNTIME_META_CACHE[cache_key]

        if is_lithops_worker() or not os.path.exists(filename_local_path):
            return None

        logger.debug("Runtime metadata found in local disk cache")
        with open(filename_local_path, "r") as f:
            runtime_meta = json.loads(f.read())
        RUNTIME_META_CACHE[cache_key] = runtime_meta
        return runtime_meta

    def get_runtime_meta(self, key):
        """
        Returns the metadata of a runtime, looking in the memory cache, then
        the disk cache, then storage. Returns None when the runtime has no
        metadata yet, which is what tells the caller to deploy it
        """
        _, cache_key, obj_key = self._runtime_meta_refs(key)
        filename_local_path = self._local_runtime_meta_path(key)

        runtime_meta = self._cached_runtime_meta(cache_key, filename_local_path)
        if runtime_meta is not None:
            return runtime_meta

        logger.debug(
            "Runtime metadata not found in local cache. Retrieving it from storage"
        )
        logger.debug(
            'Trying to download runtime metadata from: '
            f'{self.backend}://{self.bucket}/{obj_key}'
        )
        try:
            json_str = self.storage.get_object(self.bucket, obj_key)
        except utils.StorageNoSuchKeyError:
            logger.debug('Runtime metadata not found in storage')
            return None

        logger.debug('Runtime metadata found in storage')
        runtime_meta = json.loads(json_str.decode("ascii"))

        try:
            self._write_runtime_meta_file(filename_local_path, runtime_meta)
        except Exception as e:
            # A cache that cannot be written only costs the next download
            logger.error(f"Could not save runtime meta to local cache: {e}")

        RUNTIME_META_CACHE[cache_key] = runtime_meta
        return runtime_meta

    def put_runtime_meta(self, key, runtime_meta):
        """
        Writes the metadata of a runtime to storage, and to the local disk
        cache unless this is a worker, whose disk nothing else reads
        """
        _, _, obj_key = self._runtime_meta_refs(key)
        logger.debug(
            f"Uploading runtime metadata to: "
            f"{self.backend}://{self.bucket}/{obj_key}"
        )
        self.storage.put_object(self.bucket, obj_key, json.dumps(runtime_meta))

        if not is_lithops_worker():
            filename_local_path = self._local_runtime_meta_path(key)
            logger.debug(
                f"Storing runtime metadata into local cache: {filename_local_path}"
            )
            self._write_runtime_meta_file(filename_local_path, runtime_meta)

    def delete_runtime_meta(self, key):
        """Deletes the metadata of a runtime from storage and from the cache"""
        _, _, obj_key = self._runtime_meta_refs(key)
        filename_local_path = self._local_runtime_meta_path(key)
        if os.path.exists(filename_local_path):
            os.remove(filename_local_path)
        self.storage.delete_object(self.bucket, obj_key)
