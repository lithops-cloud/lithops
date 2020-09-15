#
# (C) Copyright IBM Corp. 2019
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
import requests
import json
import base64
from requests.auth import HTTPBasicAuth

from lithops.utils import is_lithops_function

logger = logging.getLogger(__name__)


class InfinispanBackend:
    """
    Infinispan backend
    """

    def __init__(self, infinispan_config, **kwargs):
        logger.debug("Creating Infinispan client")
        self.infinispan_config = infinispan_config
        self.is_lithops_function = is_lithops_function()
        self.basicAuth = HTTPBasicAuth(infinispan_config.get('username'),
                                       infinispan_config.get('password'))
        self.endpoint = infinispan_config.get('endpoint')
        self.cache_manager = infinispan_config.get('cache_manager', 'default')
        self.cache_name = self.__generate_cache_name(kwargs['bucket'], kwargs['executor_id'])
        self.infinispan_client = requests.session()

        self.__is_server_version_supported()

        res = self.infinispan_client.head(self.endpoint + '/rest/v2/caches/' + self.cache_name,
                                          auth=self.basicAuth)
        if res.status_code == 404:
            logger.debug('going to create new Infinispan cache {}'.format(self.cache_name))
            res = self.infinispan_client.post(self.endpoint + '/rest/v2/caches/' + self.cache_name + '?template=org.infinispan.DIST_SYNC')
            logger.debug('New Infinispan cache {} created with status {}'.format(self.cache_name, res.status_code))

        logger.debug("Infinispan client created successfully")

    def __generate_cache_name(self, bucket, executor_id):
        if executor_id == None and bucket == None:
            raise Exception ('at least one of bucket or executor_id should be non empty')
        if executor_id is not None and executor_id.find('/') > 0:
            executor_id = executor_id.replace('/','_')
        if bucket is not None:
            cache_name = bucket + '_' + executor_id
        else:
            cache_name = executor_id

        return cache_name

    def __key_url(self, key):
        urlSafeEncodedBytes = base64.urlsafe_b64encode(key.encode("utf-8"))
        urlSafeEncodedStr = str(urlSafeEncodedBytes, "utf-8")
        url = self.endpoint + '/rest/v2/caches/' + self.cache_name + '/' + urlSafeEncodedStr
        return url
    
    def __is_server_version_supported(self):
        res = self.infinispan_client.get(self.endpoint + '/rest/v2/cache-managers/' + self.cache_manager,
                                         auth=self.basicAuth)
        json_resp = json.loads(res.content.decode('utf-8'))
        server_version = json_resp['version'].split('.')
        if (int(server_version[0]) < 10 or (int(server_version[0]) == 10 and int(server_version[1]) < 1)):
            raise Exception('Infinispan versions 10.1 and up supported')

    def get_client(self):
        """
        Get infinispan client.
        :return: infinispan_client 
        """
        return self.infinispan_client

    def put_object(self, bucket_name, key, data):
        """
        Put an object in Infinispan. Override the object if the key already exists.
        :param key: key of the object.
        :param data: data of the object
        :type data: str/bytes
        :return: None
        """
        headers = {"Content-Type": "application/octet-stream",
                   'Key-Content-Type': "application/octet-stream;encoding=base64"}
        resp = self.infinispan_client.put(self.__key_url(key), data = data,
                auth=self.basicAuth, headers = headers )
        print (resp)

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        headers = {"Content-Type": "application/octet-stream",
                   'Key-Content-Type': "application/octet-stream;encoding=base64"}

        res = self.infinispan_client.get(self.__key_url(key), headers = headers,
                                         auth=self.basicAuth)
        data = res.content
        return data

    def head_object(self, bucket_name, key):
        """
        Head object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        res = self.infinispan_client.head(self.endpoint + '/rest/v2/caches/default/' + bucket_name + '/' + key,
                                   auth=self.basicAuth)
        return res.status_code

    def delete_object(self, bucket_name, key):
        """
        Delete an object from storage.
        :param bucket: bucket name
        :param key: data key
        """
        headers = {"Content-Type": "application/octet-stream"
                                              ,'Key-Content-Type': "application/octet-stream;encoding=base64"}

        return self.infinispan_client.delete(self.__key_url(key), headers = headers,
                                             auth=self.basicAuth)

    def delete_objects(self, bucket_name, key_list):
        """
        Delete a list of objects from storage.
        :param bucket: bucket name
        :param key_list: list of keys
        """
        result = []
        for key in key_list:
            self.delete_object(bucket_name, key)
        return result

    def bucket_exists(self, bucket_name):
        """
        Head bucket from COS with a name. Throws StorageNoSuchKeyError if the given bucket does not exist.
        :param bucket_name: name of the bucket
        """
        raise NotImplementedError

    def head_bucket(self, bucket_name):
        """
        Head bucket from COS with a name. Throws StorageNoSuchKeyError if the given bucket does not exist.
        :param bucket_name: name of the bucket
        :return: Metadata of the bucket
        :rtype: str/bytes
        """
        raise NotImplementedError

    def list_objects(self, bucket_name, prefix=None):
        """
        Return a list of objects for the given bucket and prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of objects in bucket that match the given prefix.
        :rtype: list of str
        """
        res = self.infinispan_client.get(self.endpoint + '/rest/v2/caches/' + self.cache_name + '?action=keys', auth=self.basicAuth)
        data = res.content
        return data
    
        
    def list_keys(self, bucket_name, prefix=None):
        """
        Return a list of keys for the given prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        """
        res = self.infinispan_client.get(self.endpoint + '/rest/v2/caches/' + self.cache_name + '?action=keys', auth=self.basicAuth)
        data = res.content
        return data
