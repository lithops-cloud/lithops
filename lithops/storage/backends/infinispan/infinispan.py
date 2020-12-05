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
from lithops.constants import STORAGE_CLI_MSG

logger = logging.getLogger(__name__)


class InfinispanBackend:
    """
    Infinispan backend
    """

    def __init__(self, infinispan_config):
        logger.debug("Creating Infinispan storage client")
        self.infinispan_config = infinispan_config
        self.basicAuth = HTTPBasicAuth(infinispan_config.get('username'),
                                       infinispan_config.get('password'))
        self.endpoint = infinispan_config.get('endpoint')
        self.cache_name = infinispan_config.get('cache_name', 'default')
        self.cache_type = infinispan_config.get('cache_type', 'org.infinispan.DIST_SYNC')
        self.infinispan_client = requests.session()

        self.__is_server_version_supported()
        self.__create_cache(self.cache_name, self.cache_type)

        self.headers = {"Content-Type": "application/octet-stream",
                        "Key-Content-Type": "application/octet-stream;encoding=base64"}

        msg = STORAGE_CLI_MSG.format('Infinispan')
        logger.info("{} - Endpoint: {}".format(msg, self.endpoint))

    def __create_cache(self, cache_name, cache_type):
        url = self.endpoint + '/rest/v2/caches/' + cache_name
        res = self.infinispan_client.head(url, auth=self.basicAuth)

        if res.status_code == 404:
            logger.debug('going to create new Infinispan cache {}'.format(cache_name))
            url = self.endpoint+'/rest/v2/caches/'+cache_name+'?template='+cache_type
            res = self.infinispan_client.post(url)
            logger.debug('New Infinispan cache {} created with '
                         'status {}'.format(cache_name, res.status_code))

    def __key_url(self, bucket_name, key):
        data_key = '{}_{}'.format(bucket_name, key)
        urlSafeEncodedBytes = base64.urlsafe_b64encode(data_key.encode("utf-8"))
        urlSafeEncodedStr = str(urlSafeEncodedBytes, "utf-8")
        url = self.endpoint + '/rest/v2/caches/' + self.cache_name + '/' + urlSafeEncodedStr
        return url

    def __is_server_version_supported(self):
        url = self.endpoint + '/rest/v2/cache-managers/default'
        res = self.infinispan_client.get(url, auth=self.basicAuth)
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
        url = self.__key_url(bucket_name, key)
        resp = self.infinispan_client.put(url, data=data,
                                          auth=self.basicAuth,
                                          headers=self.headers)
        logger.debug(resp)

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        url = self.__key_url(bucket_name, key)
        res = self.infinispan_client.get(url, headers=self.headers, auth=self.basicAuth)
        data = res.content
        return data

    def head_object(self, bucket_name, key):
        """
        Head object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        url = self.__key_url(bucket_name, key)
        res = self.infinispan_client.head(url, headers=self.headers, auth=self.basicAuth)
        return res.status_code

    def delete_object(self, bucket_name, key):
        """
        Delete an object from storage.
        :param bucket: bucket name
        :param key: data key
        """
        url = self.__key_url(bucket_name, key)
        return self.infinispan_client.delete(url, headers=self.headers, auth=self.basicAuth)

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
        url = self.endpoint + '/rest/v2/caches/' + self.cache_name + '?action=keys'
        res = self.infinispan_client.get(url, auth=self.basicAuth)
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
        url = self.endpoint + '/rest/v2/caches/' + self.cache_name + '?action=keys'
        res = self.infinispan_client.get(url, auth=self.basicAuth)
        data = res.content
        return data
