#
# (C) Copyright IBM Corp. 2018
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
from datetime import datetime
from pywren_ibm_cloud.wrenutil import sizeof_fmt
import pywren_ibm_cloud.wrenconfig as wrenconfig
from ibm_botocore.credentials import DefaultTokenManager
from pywren_ibm_cloud.storage.exceptions import StorageNoSuchKeyError

logging.getLogger('ibm_boto3').setLevel(logging.CRITICAL)
logging.getLogger('ibm_botocore').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


class COSBackend:
    """
    A wrap-up around COS ibm_boto3 APIs.
    """

    def __init__(self, cos_config):
        service_endpoint = cos_config.get('endpoint').replace('http:', 'https:')
        ibm_auth_endpoint = cos_config['ibm_auth_endpoint']
        logger.debug("Set IBM COS Endpoint to {}".format(service_endpoint))
        logger.debug("Set IBM COS Auth Endpoint to {}".format(ibm_auth_endpoint))

        if 'api_key' in cos_config:
            client_config = ibm_botocore.client.Config(signature_version='oauth',
                                                       max_pool_connections=200,
                                                       user_agent_extra='pywren-ibm-cloud')
            api_key = cos_config.get('api_key')
            token_manager = DefaultTokenManager(api_key_id=api_key)

            if 'token' in cos_config:
                token_manager._token = cos_config['token']
                expiry_time = cos_config['token_expiry_time']
                token_manager._expiry_time = datetime.strptime(expiry_time, '%Y-%m-%d %H:%M:%S.%f%z')

            self.cos_client = ibm_boto3.client('s3',
                                               token_manager=token_manager,
                                               config=client_config,
                                               ibm_auth_endpoint=ibm_auth_endpoint,
                                               endpoint_url=service_endpoint)
            if 'token' not in cos_config:
                cos_config['token'] = token_manager.get_token()
                cos_config['token_expiry_time'] = token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')

        elif {'secret_key', 'access_key'} <= set(cos_config):
            secret_key = cos_config.get('secret_key')
            access_key = cos_config.get('access_key')
            client_config = ibm_botocore.client.Config(max_pool_connections=200,
                                                       user_agent_extra='pywren-ibm-cloud')
            self.cos_client = ibm_boto3.client('s3',
                                               aws_access_key_id=access_key,
                                               aws_secret_access_key=secret_key,
                                               config=client_config,
                                               ibm_auth_endpoint=ibm_auth_endpoint,
                                               endpoint_url=service_endpoint)

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
        try:
            res = self.cos_client.put_object(Bucket=bucket_name, Key=key, Body=data)
            status = 'OK' if res['ResponseMetadata']['HTTPStatusCode'] == 200 else 'Error'
            try:
                logger.info('PUT Object {} - Size: {} - {}'.format(key, sizeof_fmt(len(data)), status))
            except:
                logger.info('PUT Object {} {}'.format(key, status))
        except ibm_botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == "NoSuchKey":
                raise StorageNoSuchKeyError(key)
            else:
                raise e

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        try:
            r = self.cos_client.get_object(Bucket=bucket_name, Key=key, **extra_get_args)
            if stream:
                data = r['Body']
            else:
                data = r['Body'].read()
            return data
        except ibm_botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == "NoSuchKey":
                raise StorageNoSuchKeyError(key)
            else:
                raise e

    def head_object(self, bucket_name, key):
        """
        Head object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        try:
            metadata = self.cos_client.head_object(Bucket=bucket_name, Key=key)
            return metadata['ResponseMetadata']['HTTPHeaders']
        except ibm_botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(key)
            else:
                raise e

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

    def bucket_exists(self, bucket_name):
        """
        Head bucket from COS with a name. Throws StorageNoSuchKeyError if the given bucket does not exist.
        :param bucket_name: name of the bucket
        :return: Data of the object
        :rtype: str/bytes
        """
        try:
            self.cos_client.head_bucket(Bucket=bucket_name)
        except ibm_botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(bucket_name)
            else:
                raise e

    def list_objects(self, bucket_name, prefix=None):
        paginator = self.cos_client.get_paginator('list_objects_v2')
        try:
            if (prefix is not None):
                page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
            else:
                page_iterator = paginator.paginate(Bucket=bucket_name)

            object_list = []
            for page in page_iterator:
                if 'Contents' in page:
                    for item in page['Contents']:
                        object_list.append(item)
            return object_list
        except ibm_botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise StorageNoSuchKeyError(bucket_name)
            else:
                raise e

    def list_keys_with_prefix(self, bucket_name, prefix):
        """
        Return a list of keys for the given prefix.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        """
        if not prefix:
            prefix = ''
        paginator = self.cos_client.get_paginator('list_objects')
        operation_parameters = {'Bucket': bucket_name,
                                'Prefix': prefix}
        page_iterator = paginator.paginate(**operation_parameters)

        key_list = []
        for page in page_iterator:
            if 'Contents' in page:
                for item in page['Contents']:
                    key_list.append(item['Key'])

        return key_list
