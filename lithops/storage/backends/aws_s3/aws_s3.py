#
# Copyright Cloudlab URV 2020
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import logging
import boto3
import botocore
from ...utils import StorageNoSuchKeyError


logger = logging.getLogger(__name__)


class S3Backend:
    def __init__(self, s3_config, bucket=None, executor_id=None):
        service_endpoint = s3_config.get('endpoint').replace('http:', 'https:')

        logger.debug('Set AWS S3 Endpoint to {}'.format(service_endpoint))

        logger.debug('AWS S3 using access_key_id and secret_access_key')

        client_config = botocore.client.Config(max_pool_connections=128,
                                               user_agent_extra='cloudbutton',
                                               connect_timeout=1)

        self.s3_client = boto3.client('s3',
                                      aws_access_key_id=s3_config['access_key_id'],
                                      aws_secret_access_key=s3_config['secret_access_key'],
                                      config=client_config,
                                      endpoint_url=service_endpoint)

    def get_client(self):
        '''
        Get boto3 client.
        :return: boto3 client
        '''
        return self.s3_client

    def put_object(self, bucket_name, key, data):
        '''
        Put an object in COS. Override the object if the key already exists.
        :param key: key of the object.
        :param data: data of the object
        :type data: str/bytes
        :return: None
        '''
        try:
            res = self.s3_client.put_object(Bucket=bucket_name, Key=key, Body=data)
            status = 'OK' if res['ResponseMetadata']['HTTPStatusCode'] == 200 else 'Error'
            try:
                logger.debug('PUT Object {} - Size: {} - {}'.format(key, len(data), status))
            except Exception:
                logger.debug('PUT Object {} {}'.format(key, status))
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                raise StorageNoSuchKeyError(bucket_name, key)
            else:
                raise e

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        '''
        Get object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        '''
        try:
            r = self.s3_client.get_object(Bucket=bucket_name, Key=key, **extra_get_args)
            if stream:
                data = r['Body']
            else:
                data = r['Body'].read()
            return data
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                raise StorageNoSuchKeyError(bucket_name, key)
            else:
                raise e

    def head_object(self, bucket_name, key):
        '''
        Head object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        '''
        try:
            metadata = self.s3_client.head_object(Bucket=bucket_name, Key=key)
            return metadata['ResponseMetadata']['HTTPHeaders']
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(bucket_name, key)
            else:
                raise e

    def delete_object(self, bucket_name, key):
        '''
        Delete an object from storage.
        :param bucket: bucket name
        :param key: data key
        '''
        return self.s3_client.delete_object(Bucket=bucket_name, Key=key)

    def delete_objects(self, bucket_name, key_list):
        '''
        Delete a list of objects from storage.
        :param bucket: bucket name
        :param key_list: list of keys
        '''
        result = []
        max_keys_num = 1000
        for i in range(0, len(key_list), max_keys_num):
            delete_keys = {'Objects': []}
            delete_keys['Objects'] = [{'Key': k} for k in key_list[i:i+max_keys_num]]
            result.append(self.s3_client.delete_objects(Bucket=bucket_name, Delete=delete_keys))
        return result

    def bucket_exists(self, bucket_name):
        '''
        Head bucket from COS with a name. Throws StorageNoSuchKeyError if the given bucket does not exist.
        :param bucket_name: name of the bucket
        '''
        try:
            self.s3_client.head_bucket(Bucket=bucket_name)
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(bucket_name, '')
            else:
                raise e

    def head_bucket(self, bucket_name):
        '''
        Head bucket from COS with a name. Throws StorageNoSuchKeyError if the given bucket does not exist.
        :param bucket_name: name of the bucket
        :return: Metadata of the bucket
        :rtype: str/bytes
        '''
        try:
            return self.s3_client.head_bucket(Bucket=bucket_name)
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(bucket_name, '')
            else:
                raise e

    def list_objects(self, bucket_name, prefix=None):
        '''
        Return a list of objects for the given bucket and prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of objects in bucket that match the given prefix.
        :rtype: list of str
        '''
        try:
            prefix = '' if prefix is None else prefix
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

            object_list = []
            for page in page_iterator:
                if 'Contents' in page:
                    for item in page['Contents']:
                        object_list.append(item)
            return object_list
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(
                    bucket_name, '' if prefix is None else prefix)
            else:
                raise e

    def list_keys(self, bucket_name, prefix=None):
        '''
        Return a list of keys for the given prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        '''
        try:
            prefix = '' if prefix is None else prefix
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

            key_list = []
            for page in page_iterator:
                if 'Contents' in page:
                    for item in page['Contents']:
                        key_list.append(item['Key'])
            return key_list
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(bucket_name, prefix)
            else:
                raise e
