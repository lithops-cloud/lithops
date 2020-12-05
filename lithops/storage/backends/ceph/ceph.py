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

import logging
import ibm_boto3
import ibm_botocore
from lithops.storage.utils import StorageNoSuchKeyError
from lithops.utils import sizeof_fmt
from lithops.constants import STORAGE_CLI_MSG

logger = logging.getLogger(__name__)

OBJ_REQ_RETRIES = 5
CONN_READ_TIMEOUT = 10


class CephStorageBackend:
    """
    A wrap-up around Ceph boto3 APIs.
    """

    def __init__(self, ceph_config):
        logger.debug("Creating Ceph client")
        self.ceph_config = ceph_config
        user_agent = ceph_config['user_agent']

        service_endpoint = ceph_config.get('endpoint')

        logger.debug("Seting Ceph endpoint to {}".format(service_endpoint))
        logger.debug("Using access_key and secret_key")

        access_key = ceph_config.get('access_key')
        secret_key = ceph_config.get('secret_key')
        client_config = ibm_botocore.client.Config(max_pool_connections=128,
                                                   user_agent_extra=user_agent,
                                                   connect_timeout=CONN_READ_TIMEOUT,
                                                   read_timeout=CONN_READ_TIMEOUT,
                                                   retries={'max_attempts': OBJ_REQ_RETRIES})

        self.cos_client = ibm_boto3.client('s3',
                                           aws_access_key_id=access_key,
                                           aws_secret_access_key=secret_key,
                                           config=client_config,
                                           endpoint_url=service_endpoint)

        msg = STORAGE_CLI_MSG.format('Ceph')
        logger.info("{} - Endpoint: {}".format(msg, service_endpoint))

    def get_client(self):
        """
        Get ibm_boto3 client.
        :return: ibm_boto3 client
        """
        return self.cos_client

    def put_object(self, bucket_name, key, data):
        """
        Put an object in COS. Override the object if the key already exists.
        :param key: key of the object.
        :param data: data of the object
        :type data: str/bytes
        :return: None
        """
        retries = 0
        status = None
        while status is None:
            try:
                res = self.cos_client.put_object(Bucket=bucket_name, Key=key, Body=data)
                status = 'OK' if res['ResponseMetadata']['HTTPStatusCode'] == 200 else 'Error'
                try:
                    logger.debug('PUT Object {} - Size: {} - {}'.format(key, sizeof_fmt(len(data)), status))
                except Exception:
                    logger.debug('PUT Object {} {}'.format(key, status))
            except ibm_botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == "NoSuchKey":
                    raise StorageNoSuchKeyError(bucket_name, key)
                else:
                    raise e
            except ibm_botocore.exceptions.ReadTimeoutError as e:
                if retries == OBJ_REQ_RETRIES:
                    raise e
                logger.debug('PUT Object timeout. Retrying request')
                retries += 1
        return True

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from Ceph with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        data = None
        retries = 0
        while data is None:
            try:
                r = self.cos_client.get_object(Bucket=bucket_name, Key=key, **extra_get_args)
                if stream:
                    data = r['Body']
                else:
                    data = r['Body'].read()
            except ibm_botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == "NoSuchKey":
                    raise StorageNoSuchKeyError(bucket_name, key)
                else:
                    raise e
            except ibm_botocore.exceptions.ReadTimeoutError as e:
                if retries == OBJ_REQ_RETRIES:
                    raise e
                logger.debug('GET Object timeout. Retrying request')
                retries += 1
        return data

    def head_object(self, bucket_name, key):
        """
        Head object from Ceph with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        metadata = None
        retries = 0
        while metadata is None:
            try:
                metadata = self.cos_client.head_object(Bucket=bucket_name, Key=key)
            except ibm_botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == '404':
                    raise StorageNoSuchKeyError(bucket_name, key)
                else:
                    raise e
            except ibm_botocore.exceptions.ReadTimeoutError as e:
                if retries == OBJ_REQ_RETRIES:
                    raise e
                logger.debug('HEAD Object timeout. Retrying request')
                retries += 1
        return metadata['ResponseMetadata']['HTTPHeaders']

    def delete_object(self, bucket_name, key):
        """
        Delete an object from storage.
        :param bucket: bucket name
        :param key: data key
        """
        return self.cos_client.delete_object(Bucket=bucket_name, Key=key)

    def delete_objects(self, bucket_name, key_list):
        """
        Delete a list of objects from storage.
        :param bucket: bucket name
        :param key_list: list of keys
        """
        result = []
        max_keys_num = 1000
        for i in range(0, len(key_list), max_keys_num):
            delete_keys = {'Objects': []}
            delete_keys['Objects'] = [{'Key': k} for k in key_list[i:i+max_keys_num]]
            result.append(self.cos_client.delete_objects(Bucket=bucket_name, Delete=delete_keys))
        return result

    def head_bucket(self, bucket_name):
        """
        Head bucket from Ceph with a name. Throws StorageNoSuchKeyError if the given bucket does not exist.
        :param bucket_name: name of the bucket
        :return: Metadata of the bucket
        :rtype: str/bytes
        """
        try:
            return self.cos_client.head_bucket(Bucket=bucket_name)
        except ibm_botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(bucket_name, '')
            else:
                raise e

    def list_objects(self, bucket_name, prefix=None):
        """
        Return a list of objects for the given bucket and prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of objects in bucket that match the given prefix.
        :rtype: list of str
        """
        try:
            prefix = '' if prefix is None else prefix
            paginator = self.cos_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

            object_list = []
            for page in page_iterator:
                if 'Contents' in page:
                    for item in page['Contents']:
                        object_list.append(item)
            return object_list
        except ibm_botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(bucket_name, '' if prefix is None else prefix)
            else:
                raise e

    def list_keys(self, bucket_name, prefix=None):
        """
        Return a list of keys for the given prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        """
        try:
            prefix = '' if prefix is None else prefix
            paginator = self.cos_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

            key_list = []
            for page in page_iterator:
                if 'Contents' in page:
                    for item in page['Contents']:
                        key_list.append(item['Key'])
            return key_list
        except ibm_botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(bucket_name, prefix)
            else:
                raise e
