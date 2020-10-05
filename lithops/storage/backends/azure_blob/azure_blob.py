#
# Copyright Cloudlab URV 2020
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

import logging
from lithops.storage.utils import StorageNoSuchKeyError
from azure.storage.blob import BlockBlobService
from azure.common import AzureMissingResourceHttpError
from io import BytesIO

logging.getLogger('azure.storage.common.storageclient').setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

class AzureBlobStorageBackend:

    def __init__(self, azure_blob_config, bucket=None, executor_id=None):
        self.blob_client = BlockBlobService(account_name=azure_blob_config['account_name'],
                                            account_key=azure_blob_config['account_key'])

    def get_client(self):
        """
        Get Azure BlockBlobService client.
        :return: storage client
        :rtype: azure.storage.blob.BlockBlobService
        """
        return self.blob_client

    def put_object(self, bucket_name, key, data):
        """
        Put an object in COS. Override the object if the key already exists.
        :param key: key of the object.
        :param data: data of the object
        :type data: str/bytes
        :return: None
        """
        if isinstance(data, str):
            data = data.encode()

        self.blob_client.create_blob_from_bytes(bucket_name, key, data)

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        if 'Range' in extra_get_args:   # expected common format: Range='bytes=L-H'
            bytes_range = extra_get_args.pop('Range')[6:]
            bytes_range = bytes_range.split('-')
            extra_get_args['start_range'] = int(bytes_range[0])
            extra_get_args['end_range'] = int(bytes_range[1])
        try:
            if stream:
                stream_out = BytesIO()
                self.blob_client.get_blob_to_stream(bucket_name, key, stream_out, **extra_get_args)
                stream_out.seek(0)
                return stream_out
            else:
                data = self.blob_client.get_blob_to_bytes(bucket_name, key, **extra_get_args)
                return data.content

        except AzureMissingResourceHttpError:
            raise StorageNoSuchKeyError(bucket_name, key)


    def head_object(self, bucket_name, key):
        """
        Head object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        blob = self.blob_client.get_blob_properties(bucket_name, key)

        # adapted to match ibm_cos method
        metadata = {}
        metadata['content-length'] = blob.properties.content_length
        return metadata

    def delete_object(self, bucket_name, key):
        """
        Delete an object from storage.
        :param bucket: bucket name
        :param key: data key
        """
        try:
            self.blob_client.delete_blob(bucket_name, key)
        except AzureMissingResourceHttpError:
            pass
            #raise StorageNoSuchKeyError(bucket_name, key)

    def delete_objects(self, bucket_name, key_list):
        """
        Delete a list of objects from storage.
        :param bucket: bucket name
        :param key_list: list of keys
        """
        for key in key_list:
            self.delete_object(bucket_name, key)

    def head_bucket(self, bucket_name):
        """
        Head container from COS with a name. Throws StorageNoSuchKeyError if the given container does not exist.
        :param bucket_name: name of the container
        :return: Data of the object
        """
        try:
           return self.blob_client.get_container_metadata(bucket_name)
        except Exception:
           raise StorageNoSuchKeyError(bucket_name, '')

    def bucket_exists(self, bucket_name):
        """
        Returns True if container exists in storage. Throws StorageNoSuchKeyError if the given container does not exist.
        :param bucket_name: name of the container
        """
        try:
           self.blob_client.get_container_metadata(bucket_name)
           return True
        except Exception:
           raise StorageNoSuchKeyError(bucket_name, '')

    def list_objects(self, bucket_name, prefix=None):
        """
        Return a list of objects for the given bucket and prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of objects in bucket that match the given prefix.
        :rtype: list of str
        """
        # adapted to match ibm_cos method
        try:
            blobs = self.blob_client.list_blobs(bucket_name, prefix)
            mod_list = []
            for blob in blobs:
                mod_list.append({
                    'Key' : blob.name,
                    'Size' : blob.properties.content_length
                })
            return mod_list
        except Exception:
            raise StorageNoSuchKeyError(bucket_name, '' if prefix is None else prefix)

    def list_keys(self, bucket_name, prefix=None):
        """
        Return a list of keys for the given prefix.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        """
        try:
            keys = [key for key in self.blob_client.list_blob_names(bucket_name, prefix).items]
            return keys
        except Exception:
            raise StorageNoSuchKeyError(bucket_name, '' if prefix is None else prefix)
