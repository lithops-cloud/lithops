#
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

import oss2
import logging

from lithops.serverless.backends.aliyun_fc.config import CONNECTION_POOL_SIZE
from lithops.storage.utils import StorageNoSuchKeyError
from lithops.utils import is_lithops_worker
from lithops.constants import STORAGE_CLI_MSG


logger = logging.getLogger(__name__)


class AliyunObjectStorageServiceBackend:

    def __init__(self, config):
        logger.debug("Creating Alibaba Object Storage client")
        self.config = config
        self.auth = oss2.Auth(self.config['access_key_id'], self.config['access_key_secret'])


        if is_lithops_worker():
            self.endpoint = self.config['internal_endpoint']
        else:
            self.endpoint = self.config['public_endpoint']

        # Connection pool size in aliyun_oss must be updated to avoid "connection pool is full" type errors.
        oss2.defaults.connection_pool_size = CONNECTION_POOL_SIZE

        msg = STORAGE_CLI_MSG.format('Alibaba Object Storage')
        logger.info("{} - Endpoint: {}".format(msg, self.endpoint))

    def _connect_bucket(self, bucket_name):
        if hasattr(self, 'bucket') and self.bucket.bucket_name == bucket_name:
            bucket = self.bucket
        else:
            self.bucket = oss2.Bucket(self.auth, self.endpoint, bucket_name)
            bucket = self.bucket
        return bucket

    def get_client(self):
        return self

    def put_object(self, bucket_name, key, data):
        """
        Put an object in OSS. Override the object if the key already exists.
        Throws StorageNoSuchKeyError if the bucket does not exist.
        :param bucket_name: bucket name
        :param key: key of the object.
        :param data: data of the object
        :type data: str/bytes
        :return: None
        """
        if isinstance(data, str):
            data = data.encode()

        try:
            bucket = self._connect_bucket(bucket_name)
            bucket.put_object(key, data)
        except oss2.exceptions.NoSuchBucket:
            raise StorageNoSuchKeyError(bucket_name, '')

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from OSS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param bucket_name: bucket name
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        try:
            bucket = self._connect_bucket(bucket_name)

            if 'Range' in extra_get_args:   # expected common format: Range='bytes=L-H'
                bytes_range = extra_get_args.pop('Range')
                if isinstance(bytes_range, str):
                    bytes_range = bytes_range[6:]
                    bytes_range = bytes_range.split('-')

                # Cannot use byte range surpassing the content length
                if int(bytes_range[0]) != 0:
                    object_length = bucket.head_object(key).content_length
                    if int(bytes_range[1]) >= object_length:
                        bytes_range[1] = object_length - 1

                extra_get_args['byte_range'] = (int(bytes_range[0]), int(bytes_range[1]))


            data = bucket.get_object(key=key, **extra_get_args)
            if stream:
                return data
            else:
                return data.read()

        except (oss2.exceptions.NoSuchKey, oss2.exceptions.NoSuchBucket):
            raise StorageNoSuchKeyError(bucket_name, key)

    def head_object(self, bucket_name, key):
        """
        Head object from OSS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param bucket_name: bucket name
        :param key: key of the object
        :return: Data of the object
        :rtype: dict
        """
        bucket = self._connect_bucket(bucket_name)

        try:
            headobj = bucket.head_object(key)
            # adapted to match ibm_cos method
            metadata = vars(headobj)
            metadata['content-length'] = metadata.pop('content_length')
            return metadata
        except (oss2.exceptions.NoSuchKey, oss2.exceptions.NoSuchBucket):
            raise StorageNoSuchKeyError(bucket_name, key)

    def delete_object(self, bucket_name, key):
        """
        Delete an object from storage.
        :param bucket_name: bucket name
        :param key: data key
        """
        bucket = self._connect_bucket(bucket_name)
        bucket.delete_object(key)

    def delete_objects(self, bucket_name, key_list):
        """
        Delete a list of objects from storage.
        :param bucket_name: bucket name
        :param key_list: list of keys
        """
        bucket = self._connect_bucket(bucket_name)
        bucket.batch_delete_objects(key_list)

    def head_bucket(self, bucket_name):
        """
        Head bucket from OSS with a name. Throws StorageNoSuchKeyError if the given bucket does not exist.
        :param bucket_name: name of the bucket
        :return: metadata of the bucket
        :rtype: dict
        """
        bucket = self._connect_bucket(bucket_name)
        try:
            metadata = bucket.get_bucket_info()
            return vars(metadata)
        except oss2.exceptions.NoSuchBucket:
            raise StorageNoSuchKeyError(bucket_name, '')

    def list_objects(self, bucket_name, prefix=None):
        """
        Return a list of objects for the given bucket and prefix.
        :param bucket_name: name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of objects in bucket that match the given prefix.
        :rtype: list of dict
        """
        bucket = self._connect_bucket(bucket_name)

        # adapted to match ibm_cos method
        prefix = '' if prefix is None else prefix
        try:
            res = bucket.list_objects(prefix=prefix)
            obj_list = [{'Key': obj.key, 'Size': obj.size} for obj in res.object_list]
            return obj_list

        except (oss2.exceptions.NoSuchKey, oss2.exceptions.NoSuchBucket):
            raise StorageNoSuchKeyError(bucket_name, prefix)

    def list_keys(self, bucket_name, prefix=None):
        """
        Return a list of keys for the given prefix.
        :param bucket_name: name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        """
        bucket = self._connect_bucket(bucket_name)

        # adapted to match ibm_cos method
        prefix = '' if prefix is None else prefix
        try:
            res = bucket.list_objects(prefix=prefix)
            keys = [obj.key for obj in res.object_list]
            return [] if keys is None else keys

        except (oss2.exceptions.NoSuchKey, oss2.exceptions.NoSuchBucket):
            raise StorageNoSuchKeyError(bucket_name, prefix)
