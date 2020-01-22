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

import os
import logging
import requests
import base64
from requests.auth import HTTPBasicAuth

from datetime import datetime, timezone

from pywren_ibm_cloud.storage.utils import StorageNoSuchKeyError
from pywren_ibm_cloud.utils import sizeof_fmt, is_pywren_function
from pywren_ibm_cloud.config import CACHE_DIR, load_yaml_config, dump_yaml_config


logger = logging.getLogger(__name__)


class InfinispanBackend:
    """
    Infinispan backend
    """

    def __init__(self, infinispan_config):
        logger.debug("Creating Infinispan client")
        self.infinispan_config = infinispan_config
        self.is_pywren_function = is_pywren_function()
        self.basicAuth=HTTPBasicAuth(infinispan_config.get('username'), 
                                infinispan_config.get('password'))
        self.endpoint = infinispan_config.get('endpoint')
        self.cache_name = infinispan_config.get('cache','default')
                                        
        self.infinispan_client = requests.session()
        logger.debug("Infinispan client created successfully")

    def key_url(self, bucket_name, key):
        if (bucket_name is not None and key is not None):
            targetKey = bucket_name + '/' + key
        elif (bucket_name is not None and key is None):
            targetKey = bucket_name
        else:
            targetKey = key

        urlSafeEncodedBytes = base64.urlsafe_b64encode(targetKey.encode("utf-8"))
        urlSafeEncodedStr = str(urlSafeEncodedBytes, "utf-8")
        url = self.endpoint + '/rest/v2/caches/' + self.cache_name + '/' + urlSafeEncodedStr
        return url
    
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
        headers = {"Content-Type": "application/octet-stream"
                                              ,'Key-Content-Type': "application/octet-stream;encoding=base64"}
        resp = self.infinispan_client.put(self.key_url(bucket_name, key), data = data,
                auth=self.basicAuth, headers = headers )
        print (resp)

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from COS with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        data = None

        res = self.infinispan_client.get(self.key_url(bucket_name, key),
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
        metadata = None
        metadata = self.infinispan_client.head(self.endpoint + '/rest/v2/caches/default/' + bucket_name + '/' + key,
                                   auth=self.basicAuth)
        return metadata['ResponseMetadata']['HTTPHeaders']

    def delete_object(self, bucket_name, key):
        """
        Delete an object from storage.
        :param bucket: bucket name
        :param key: data key
        """
        return self.infinispan_client.delet(self.endpoint + '/rest/v2/caches/default/' + bucket_name + '/' + key,
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
        pass;
    
        
    def list_keys(self, bucket_name, prefix=None):
        """
        Return a list of keys for the given prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        """
        pass;
