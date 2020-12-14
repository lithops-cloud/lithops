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

import logging
from io import BytesIO
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from lithops.storage.utils import StorageNoSuchKeyError
from lithops.constants import STORAGE_CLI_MSG

logger = logging.getLogger(__name__)


class AzureBlobStorageBackend:

    def __init__(self, azure_blob_config):
        logger.debug("Creating Azure Blob Storage client")
        self.storage_account = azure_blob_config['storage_account']
        self.blob_service_url = 'https://{}.blob.core.windows.net'.format(self.storage_account)
        self.blob_client = BlobServiceClient(account_url=self.blob_service_url,
                                             credential=azure_blob_config['storage_account_key'])

        msg = STORAGE_CLI_MSG.format('Azure Blob')
        logger.info("{}".format(msg))

    def get_client(self):
        """
        Get Azure BlobServiceClient client.
        :return: storage client
        :rtype: azure.storage.blob.BlobServiceClient
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

        container_client = self.blob_client.get_container_client(bucket_name)
        container_client.upload_blob(key, data, overwrite=True)

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
            extra_get_args['offset'] = int(bytes_range[0])
            extra_get_args['length'] = int(bytes_range[1]) - extra_get_args['offset']
        try:
            container_client = self.blob_client.get_container_client(bucket_name)
            if stream:
                stream_out = BytesIO()
                container_client.download_blob(key, **extra_get_args).download_to_stream(stream_out)
                stream_out.seek(0)
                return stream_out
            else:
                data = container_client.download_blob(key, **extra_get_args).content_as_bytes()
                return data

        except ResourceNotFoundError:
            raise StorageNoSuchKeyError(bucket_name, key)

    def head_object(self, bucket_name, key):
        """
        Head object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        container_client = self.blob_client.get_container_client(bucket_name)
        blob = container_client.get_blob_client(key)

        # adapted to match ibm_cos method
        metadata = {}
        metadata['content-length'] = blob.get_blob_properties().size
        return metadata

    def delete_object(self, bucket_name, key):
        """
        Delete an object from storage.
        :param bucket: bucket name
        :param key: data key
        """
        try:
            container_client = self.blob_client.get_container_client(bucket_name)
            container_client.delete_blob(key, "include")
        except ResourceNotFoundError:
            pass

    def delete_objects(self, bucket_name, key_list):
        """
        Delete a list of objects from storage.
        :param bucket: bucket name
        :param key_list: list of keys
        """
        try:
            container_client = self.blob_client.get_container_client(bucket_name)
            container_client.delete_blobs(*key_list, delete_snapshots="include")
        except ResourceNotFoundError:
            pass

    def head_bucket(self, bucket_name):
        """
        Head container from COS with a name. Throws StorageNoSuchKeyError if the given container does not exist.
        :param bucket_name: name of the container
        :return: Data of the object
        """
        try:
            container_client = self.blob_client.get_container_client(bucket_name)
            return container_client.get_container_properties()
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
            container_client = self.blob_client.get_container_client(bucket_name)
            blobs = container_client.list_blobs(prefix)
            mod_list = []
            for blob in blobs:
                mod_list.append({
                    'Key': blob.name,
                    'Size': blob.size
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
            container_client = self.blob_client.get_container_client(bucket_name)
            keys = [blob.name for blob in container_client.list_blobs(prefix)]
            return keys
        except Exception:
            raise StorageNoSuchKeyError(bucket_name, '' if prefix is None else prefix)
