# (C) Copyright Cloudlab URV 2023
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

import io
import os
import logging

import oci
from oci.object_storage import ObjectStorageClient

from lithops.storage.utils import StorageNoSuchKeyError
from lithops.constants import STORAGE_CLI_MSG
from lithops.utils import sizeof_fmt


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class OCIObjectStorageBackend:

    def __init__(self, oci_config):

        logger.info("Creating Oracle Object Storage client")
        self.config = oci_config
        self.region_name = oci_config['region']
        self.key_file = oci_config['key_file']
        self.compartment_id = oci_config['compartment_id']

        self.os_client = self._init_storage_client()
        self.namespace = oci_config.get(
            "tenancy_namespace", self.os_client.get_namespace().data)

        msg = STORAGE_CLI_MSG.format('Oracle Object Storage')
        logger.info(f"{msg} - Region: {self.region_name}")

    def _init_storage_client(self):
        if os.path.isfile(self.key_file):
            return ObjectStorageClient(self.config)
        else:
            self.signer = oci.auth.signers.get_resource_principals_signer()
            return ObjectStorageClient(config={}, signer=self.signer)

    def get_client(self):
        return self

    def generate_bucket_name(self):
        """
        Generates a unique bucket name
        """
        user = self.config['user']
        self.config['storage_bucket'] = f'lithops-{self.region}-{user[-8:-1].lower()}'

        return self.config['storage_bucket']

    def create_bucket(self, bucket_name):
        """
        Create a bucket if it doesn't exist
        """
        try:
            self.os_client.create_bucket(
                namespace_name=self.namespace,
                create_bucket_details=oci.object_storage.models.CreateBucketDetails(
                    name=bucket_name,
                    compartment_id=self.compartment_id))
        except oci.exceptions.ServiceError:
            pass

    def put_object(self, bucket_name, key, data):
        '''
        Uploads data to OCI Object Storage with a specified key. Throws StorageNoSuchKeyError if the key does not exist.

        :param bucket_name: The name of the bucket to which the object will be uploaded.
        :param key: The key under which the object will be stored.
        :param data: The data to be uploaded, either as a byte string or a BytesIO object.

        :raises StorageNoSuchKeyError: If the specified key does not exist in the bucket.
        '''
        # Check if data is a BytesIO object
        if isinstance(data, io.BytesIO):
            data = data.getvalue()

        try:
            self.os_client.put_object(self.namespace, bucket_name, key, data)
            logger.debug('OSS Object {} uploaded to bucket {} - Size: {}'.format(key, bucket_name, sizeof_fmt(len(data))))
        except oci.exceptions.ServiceError as e:
            logger.debug("ServiceError in put_object: %s", str(e))
            raise StorageNoSuchKeyError(bucket_name, key)

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        '''
        Get object from OCI Object Storage with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        '''
        data = None
        try:
            if 'Range' in extra_get_args:
                range = extra_get_args['Range']
                r = self.os_client.get_object(self.namespace, bucket_name, key, range=range)
            else:
                r = self.os_client.get_object(self.namespace, bucket_name, key)

            if stream:
                data = io.BytesIO(r.data.content)
            else:
                data = r.data.content
        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                raise StorageNoSuchKeyError(bucket_name, key)
            else:
                raise e
        return data

    def upload_file(self, file_name, bucket, key=None, extra_args={}, config=None):
        '''
        Uploads a file to OCI Object Storage. The file is read in binary mode and uploaded under a specified key.
        If no key is provided, the base name of the file is used as the key.

        :param file_name: Name of the bucket
        :param bucket: The name of the bucket to which the file will be uploaded
        :param key: The key under which the file will be stored. If None, the base name of the file is used
        :param (Optional) extra_args: Additional arguments that may be passed to the function. Currently unused
        :return: True if the file was successfully uploaded, False otherwise
        :rtype: bool
        '''
        if key is None:
            key = os.path.basename(file_name)

        try:
            with open(file_name, 'rb') as in_file:
                self.os_client.put_object(self.namespace, bucket, key, in_file)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def download_file(self, bucket, key, file_name=None, extra_args={}, config=None):
        '''
        Download a file from the specified bucket and key in the object storage.
        :param bucket: Name of the bucket
        :param key: The key or path of the file in the object storage
        :param file_name: (Optional) The name of the file to be saved locally. If not provided, the key is used as the file name
        :param extra_args: (Optional) Additional arguments for the download process.
        :return: True if the file is downloaded successfully, False otherwise.
        :rtype: bool
        '''
        if file_name is None:
            file_name = key

        # Download the file
        try:
            dirname = os.path.dirname(file_name)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname)
            with open(file_name, 'wb') as out:
                data_stream = self.os_client.get_object(self.namespace, bucket, key).data.content
                out.write(data_stream)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def head_object(self, bucket_name, key):
        '''
        Downloads a file from OCI Object Storage. The file is identified by a specified key and is written locally
        in binary mode. If no local file name is provided, the key is used as the local file name.

        :param bucket: Name of the bucket
        :param key: The key under which the file is stored
        :param (Optional) file_name: The local file path where the downloaded file will be written. If None, the key is used
        :param extra_args: Additional arguments that may be passed to the function
        :return: True if the file was successfully downloaded
        :rtype: bool
        '''
        try:
            headobj = self.os_client.head_object(self.namespace, bucket_name, key).headers
            return headobj
        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name, key)

    def delete_object(self, bucket_name, key):
        '''
        Deletes an object from OCI Object Storage. The object is identified by a specified key in a specified bucket.

        :param bucket_name: Name of the bucket
        :param key: The key under which the object is stored

        '''
        self.os_client.delete_object(self.namespace, bucket_name, key)

    def delete_objects(self, bucket_name, keys_list):
        '''
        Deletes multiple objects from OCI Object Storage. The objects are identified by a list of keys in a specified bucket.

        :param bucket_name: Name of the bucket
        :param keys_list: A list of keys under which the objects are stored
        '''
        for key in keys_list:
            self.os_client.delete_object(self.namespace, bucket_name, key)

    def head_bucket(self, bucket_name):
        '''
        Return the metadata for a bucket from OCI Object Storage.
        :param bucket_name: Name of the bucket
        :return: A dictionary containing the HTTP status code and headers for the bucket
        :rtype: dict
        :raises StorageNoSuchKeyError: If the specified bucket does not exist
        '''
        response = {
            'ResponseMetadata':
                {'HTTPStatusCode': 200,
                 'HTTPHeaders': {'content-type': 'application/xml',
                                 'server': 'OracleStorage'}}
        }
        try:
            metadata = self.os_client.head_bucket(self.namespace, bucket_name)
            response['ResponseMetadata']['HTTPStatusCode'] = metadata.status
            return response
        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name, '')

    def list_objects(self, bucket_name, prefix=None, match_pattern=None):
        '''
        Return the list of objects from OCI Object Storage for the specified bucket.

        :param bucket_name: Name of the bucket
        :param prefix: (Optional) Prefix to filter object names. Default is None
        :param match_pattern: (Optional) Match pattern to further filter object names. Default is None
        :return: A list of dictionaries containing the keys and sizes of the objects that match the given prefix and match pattern
        :rtype: list of dict
        :raises StorageNoSuchKeyError: If the specified bucket does not exist or there is a service error
        '''
        prefix = '' if prefix is None else prefix
        try:
            res = self.os_client.list_objects(self.namespace, bucket_name, prefix=prefix, limit=1000, fields="name,size")
            obj_list = [{'Key': obj.name, 'Size': obj.size} for obj in res.data.objects]

            return obj_list

        except oci.exceptions.ServiceError as e:
            logger.debug("ServiceError in list_objects: %s", str(e))
            raise StorageNoSuchKeyError(bucket_name, prefix)

    def list_keys(self, bucket_name, prefix=None):
        '''
        Return a list of keys for the given prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        '''
        prefix = '' if prefix is None else prefix
        try:
            objects = []
            next_start = None
            while True:
                res = self.os_client.list_objects(self.namespace, bucket_name, prefix=prefix, start=next_start)
                objects.extend(res.data.objects)
                if res.data.next_start_with is None:
                    break
                next_start = res.data.next_start_with

            key_list = [obj.name for obj in objects]
            return key_list
        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                raise StorageNoSuchKeyError(bucket_name, prefix)
            else:
                raise e
