#
# Copyright 2018 PyWren Team
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

import json
import os

from .exceptions import StorageNoSuchKeyError
from .cos_backend import COSBackend
from .swift_backend import SwiftBackend


class Storage(object):
    """
    A Storage object is used by executors and other components to access underlying storage backend
    without exposing the the implementation details.
    """

    def __init__(self, config):
        self.storage_config = config
        self.backend_type = config['storage_backend']
        self.storage_bucket =  config['storage_bucket']
        self.prefix = config['storage_prefix']

        if self.backend_type == 'ibm_cos':
            self.backend_handler = COSBackend(config['backend_config'])
        elif self.backend_type == 'swift':
            self.backend_handler = SwiftBackend(config['backend_config'])
        else:
            raise NotImplementedError(("Using {} as storage backend is" +
                                       "not supported yet").format(self.backend_type))

    def get_storage_config(self):
        """
        Retrieves the configuration of this storage handler.
        :return: storage configuration
        """
        return self.storage_config
    
    def put_object(self, bucket, key, data):
        """
        Generic method to Put an object into storage.
        :param bucket: bucket name
        :param key: data key
        :param data: data content
        :return: None
        """
        return self.backend_handler.put_object(bucket, key, data)
    
    def get_object(self, bucket, key, stream=False, extra_get_args={}):
        """
        Generic method to Get an object from storage.
        :param bucket: bucket name
        :param key: data key
        :return: data content
        """
        return self.backend_handler.get_object(bucket, key, stream, extra_get_args)
    
    def delete_object(self, bucket, key):
        """
        Generic method to delete an object from storage.
        :param bucket: bucket name
        :param key: data key
        """
        return self.backend_handler.delete_object(bucket, key)
    
    def delete_objects(self, bucket, key_list):
        """
        Generic method to delete a list of objects from storage.
        :param bucket: bucket name
        :param key: data key
        """
        return self.backend_handler.delete_objects(bucket, key_list)

    def get_metadata(self, bucket, key):
        """
        Get object metadata.
        :param key: function key
        :return: metadata dictionary
        """
        return self.backend_handler.head_object(bucket, key)
    
    def bucket_exists(self, bucket):
        """
        Get object metadata.
        :param key: function key
        :return: metadata dictionary
        """
        try:
            self.backend_handler.bucket_exists(bucket)
            return True
        except StorageNoSuchKeyError:
            return False
    
    def list_objects(self, bucket, prefix=''):
        """
        List the objects in a bucket.
        :param bucket: bucket key
        :param prefix: prefix to search for
        :return: list of objects
        """
        return self.backend_handler.list_objects(bucket, prefix)

    def object_exists(self, bucket, key):        
        """
        Get the status of a callset.
        :param key: function key
        :param bucket: container name
        :return: True if key exists, False if not exists
        """
        try:
            self.backend_handler.head_object(bucket, key)
            return True
        except StorageNoSuchKeyError:
            return False
        except Exception as e:
            raise e
    
    def get_runtime_info(self, runtime_name):
        """
        Get the metadata given a runtime config.
        :param runtime: name of the runtime
        :return: runtime metadata
        """
        key = os.path.join('runtimes', runtime_name+".meta.json")
        try:
            json_str = self.backend_handler.get_object(self.storage_bucket, key)
        except StorageNoSuchKeyError:
            raise Exception('The runtime {} is not installed.\nRun the command "./build_runtime create {}" to deploy it'.format(runtime_name, runtime_name))  
        runtime_meta = json.loads(json_str.decode("ascii"))
        
        return runtime_meta

    def get_list_paginator(self, bucket, prefix=''):
        return self.backend_handler.list_paginator(bucket, prefix)
