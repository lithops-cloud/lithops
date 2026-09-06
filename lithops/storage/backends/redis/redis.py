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

import os
import io
import copy
import redis
import shutil
import logging
from lithops.storage.utils import StorageNoSuchKeyError
from lithops.constants import STORAGE_CLI_MSG


logger = logging.getLogger(__name__)


class RedisBackend:
    def __init__(self, config):
        logger.debug("Creating Redis storage client")
        self.config = config
        self.user_agent = self.config['user_agent']
        self.host = self.config['host']

        redis_config = copy.deepcopy(config)
        redis_config.pop('storage_bucket')
        redis_config.pop('user_agent')
        self._client = redis.Redis(**redis_config)

        msg = STORAGE_CLI_MSG.format('Redis')
        logger.info(f"{msg} - Host: {self.host}")

    def get_client(self):
        return self._client

    def put_object(self, bucket_name, key, data):
        """
        Put an object in Redis. Override the object if the key already exists.
        :param bucket_name: bucket name
        :param key: key of the object.
        :param data: data of the object
        :type data: str/bytes/file-like
        :return: None
        """
        if hasattr(data, 'read'):
            data = data.read()
        if not isinstance(data, (str, bytes, bytearray)):
            raise TypeError(type(data), 'valid types: {}'.format((str, bytes, bytearray)))

        redis_key = self._format_key(bucket_name, key)
        components = redis_key.split('/')

        # NOTE: could use a lua script and add from the lowest
        # to the highest dir and stop when SADD returns 0 since
        # then we can assume higher dirs already exist
        pipeline = self._client.pipeline(False)

        # create parent dirs
        for i in range(1, len(components) - 1):
            loc = '/'.join(components[:i]) + '/'
            pipeline.sadd(loc, components[i] + '/')

        # add file to lowest dir
        loc = '/'.join(components[:-1]) + '/'
        pipeline.sadd(loc, components[-1])

        # set actual key
        pipeline.set(redis_key, data)
        pipeline.execute()

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from Redis with a key.
        Throws StorageNoSuchKeyError if the given key does not exist.
        :param bucket_name: bucket name
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """

        redis_key = self._format_key(bucket_name, key)
        try:
            if 'Range' in extra_get_args:  # expected format: Range='bytes=L-H'
                start, end = self._parse_range(extra_get_args['Range'][6:])
                pipeline = self._client.pipeline(False)
                pipeline.exists(redis_key)
                pipeline.getrange(redis_key, start, end)
                exists, data = pipeline.execute()
                # GETRANGE answers the empty string for a key that is not
                # there, which is also a legitimate answer for one that is
                if not exists:
                    data = None
            else:
                data = self._client.get(redis_key)

        except redis.exceptions.ResponseError:
            raise StorageNoSuchKeyError(bucket_name, key)

        if data is None:
            raise StorageNoSuchKeyError(bucket_name, key)

        if stream:
            return io.BytesIO(data)
        else:
            return data

    def upload_file(self, file_name, bucket, key=None, extra_args={}, config=None):
        """Upload a file

        :param file_name: File to upload
        :param bucket: Bucket to upload to
        :param key: S3 object name. If not specified then file_name is used
        :return: True if file was uploaded, else False
        """
        # If S3 key was not specified, use file_name
        if key is None:
            key = os.path.basename(file_name)

        # Upload the file
        try:
            with open(file_name, 'rb') as in_file:
                self.put_object(bucket, key, in_file)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def download_file(self, bucket, key, file_name=None, extra_args={}, config=None):
        """Download a file

        :param bucket: Bucket to download from
        :param key: S3 object name. If not specified then file_name is used
        :param file_name: File to upload
        :return: True if file was downloaded, else False
        """
        # If file_name was not specified, use S3 key
        if file_name is None:
            file_name = key

        # Download the file
        try:
            dirname = os.path.dirname(file_name)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname)
            with open(file_name, 'wb') as out:
                data_stream = self.get_object(bucket, key, stream=True)
                shutil.copyfileobj(data_stream, out)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def head_object(self, bucket_name, key):
        """
        Head object from Redis with a key.
        Throws StorageNoSuchKeyError if the given key does not exist.
        :param bucket_name: bucket name
        :param key: key of the object
        :return: Data of the object
        :rtype: dict
        """
        redis_key = self._format_key(bucket_name, key)

        pipeline = self._client.pipeline(False)
        pipeline.exists(redis_key)
        pipeline.strlen(redis_key)
        exists, length = pipeline.execute()

        if not exists:
            raise StorageNoSuchKeyError(bucket_name, key)

        return {'content-length': str(length)}

    def delete_object(self, bucket_name, key):
        """
        Delete an object from storage.
        :param bucket_name: bucket name
        :param key: data key
        """
        self.delete_objects(bucket_name, [key])

    def delete_objects(self, bucket_name, key_list):
        """
        Delete a list of objects from storage.
        :param bucket_name: bucket name
        :param key_list: list of keys
        """
        if not key_list:
            return

        redis_key_list = [self._format_key(bucket_name, k) for k in key_list]

        pipeline = self._client.pipeline(False)
        pipeline.delete(*redis_key_list)

        for full_path in redis_key_list:
            components = full_path.split('/')
            pdir = '/'.join(components[:-1]) + '/'
            pipeline.srem(pdir, components[-1])

        pipeline.execute()

    def head_bucket(self, bucket_name):
        """
        Head bucket from Redis with a name.
        Throws StorageNoSuchKeyError if the given bucket does not exist.
        :param bucket_name: name of the bucket
        :return: metadata of the bucket
        :rtype: dict
        """
        if not self._client.exists(self._format_key(bucket_name, '')):
            raise StorageNoSuchKeyError(bucket_name, '')

        return {'ResponseMetadata': {'HTTPStatusCode': 200}}

    def list_objects(self, bucket_name, prefix=None, match_pattern=None):
        """
        Return a list of objects for the given bucket and prefix.
        :param bucket_name: name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of objects in bucket that match the given prefix.
        :rtype: list of dict
        """
        keys = self.list_keys(bucket_name, prefix)

        # STRLEN keeps the listing off the wire: the sizes are all that is
        # needed and the bodies can be arbitrarily large. EXISTS goes with
        # it because STRLEN answers 0 for a key that is not there, and the
        # directory sets outlive a value that was evicted or expired - a
        # phantom has to be dropped, not reported as a zero-byte object
        pipeline = self._client.pipeline(False)
        for key in keys:
            redis_key = self._format_key(bucket_name, key)
            pipeline.exists(redis_key)
            pipeline.strlen(redis_key)
        res = pipeline.execute()

        return [
            {'Key': key, 'Size': size}
            for key, exists, size in zip(keys, res[::2], res[1::2]) if exists
        ]

    def list_keys(self, bucket_name, prefix=None):
        """
        Return a list of keys for the given prefix.
        :param bucket_name: name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        """
        prefix = prefix or ''
        redis_prefix = self._format_key(bucket_name, prefix)

        pdir = '/'.join(redis_prefix.split('/')[:-1]) + '/'
        key_list = []
        pending = []

        for member in self._client.smembers(pdir):
            full_key = pdir + member.decode()
            if full_key.startswith(redis_prefix):
                target = pending if full_key.endswith('/') else key_list
                target.append(full_key)

        # Breadth-first, one pipelined round trip per level of the tree.
        # Descending one directory at a time costs a round trip per
        # directory, and a job holds one directory per activation
        while pending:
            pipeline = self._client.pipeline(False)
            for dir_key in pending:
                pipeline.smembers(dir_key)

            next_level = []
            for dir_key, members in zip(pending, pipeline.execute()):
                for member in members:
                    full_key = dir_key + member.decode()
                    target = next_level if full_key.endswith('/') else key_list
                    target.append(full_key)
            pending = next_level

        offset = len(bucket_name) + 1
        return [key[offset:] for key in key_list]

    def _format_key(self, bucket, key):
        return '/'.join([bucket, key])

    def _parse_range(self, bytes_range):
        """
        Translates an HTTP byte range into the (start, end) pair GETRANGE
        wants, where both ends are inclusive and -1 is the last byte.
        Accepts 'L-H', 'L-' (from L to the end) and '-N' (the last N bytes)
        """
        start, _, end = bytes_range.partition('-')

        if not start:  # '-N': the last N bytes
            return -int(end), -1

        return int(start), int(end) if end else -1
