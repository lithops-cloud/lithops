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

import os
import json
from pywren_ibm_cloud.storage.backends.cos import COSBackend
from pywren_ibm_cloud.storage.backends.swift import SwiftBackend
from pywren_ibm_cloud.storage.exceptions import StorageNoSuchKeyError
from pywren_ibm_cloud.storage.storage_utils import create_status_key, create_output_key, status_key_suffix,\
    get_group_calls_ids


class InternalStorage:
    """
    An InternalStorage object is used by executors and other components to access underlying storage backend
    without exposing the the implementation details.
    """

    def __init__(self, config):
        self.storage_config = config
        self.backend_type = config['storage_backend']
        self.storage_bucket =  config['storage_bucket']
        self.prefix = config['storage_prefix']

        if self.backend_type == 'ibm_cos':
            self.backend_handler = COSBackend(config['ibm_cos'])
        elif self.backend_type == 'swift':
            self.backend_handler = SwiftBackend(config['swift'])
        else:
            raise NotImplementedError(("Using {} as internal storage backend is" +
                                       "not supported yet").format(self.backend_type))

    def get_storage_config(self):
        """
        Retrieves the configuration of this storage handler.
        :return: storage configuration
        """
        return self.storage_config   

    def put_data(self, key, data):
        """
        Put data object into storage.
        :param key: data key
        :param data: data content
        :return: None
        """
        return self.backend_handler.put_object(self.storage_bucket, key, data)

    def put_func(self, key, func):
        """
        Put serialized function into storage.
        :param key: function key
        :param func: serialized function
        :return: None
        """
        return self.backend_handler.put_object(self.storage_bucket, key, func)
    
    def get_data(self, key, stream=False, extra_get_args={}):
        """
        Get data object from storage.
        :param key: data key
        :return: data content
        """
        return self.backend_handler.get_object(self.storage_bucket, key, stream, extra_get_args)
        
    def get_func(self, key):
        """
        Get serialized function from storage.
        :param key: function key
        :return: serialized function
        """
        return self.backend_handler.get_object(self.storage_bucket, key)

    def get_callset_status(self, executor_id):
        """
        Get the status of a callset.
        :param executor_id: executor's ID
        :return: A list of call IDs that have updated status.
        """
        # TODO: a better API for this is to return status for all calls in the callset. We'll fix
        #  this in scheduler refactoring.
        callset_prefix = os.path.join(self.prefix, executor_id)
        keys = self.backend_handler.list_keys_with_prefix(self.storage_bucket, callset_prefix)
        suffix = status_key_suffix
        status_keys = [k for k in keys if suffix in k]
        call_ids = [tuple(k[len(callset_prefix)+1:].split("/")[:2]) for k in status_keys]
        return call_ids

    def get_call_status(self, executor_id, callgroup_id, call_id):
        """
        Get status of a call.
        :param executor_id: executor ID of the call
        :param call_id: call ID of the call
        :return: A dictionary containing call's status, or None if no updated status
        """
        status_key = create_status_key(self.prefix, executor_id, callgroup_id, call_id)
        try:
            data = self.backend_handler.get_object(self.storage_bucket, status_key)
            return json.loads(data.decode('ascii'))
        except StorageNoSuchKeyError:
            return None

    def get_call_output(self, executor_id, callgroup_id, call_id):
        """
        Get the output of a call.
        :param executor_id: executor ID of the call
        :param call_id: call ID of the call
        :return: Output of the call.
        """
        output_key = create_output_key(self.prefix, executor_id, callgroup_id, call_id)
        try:
            return self.backend_handler.get_object(self.storage_bucket, output_key)
        except StorageNoSuchKeyError:
            return None

    def get_callgroup_calls_ids(self, executor_id, callgroup_id):
        """
        Get list of all calls ids of a callgroup
        :param executor_id: executor ID of the call
        :return: list of all calls ids of a callgroup
        """
        prefix = os.path.join(self.prefix, executor_id, callgroup_id)
        group_keys = self.backend_handler.list_keys_with_prefix(self.storage_bucket, prefix)
        return get_group_calls_ids(group_keys)

    def get_runtime_info(self, runtime_name):
        """
        Get the metadata given a runtime name.
        :param runtime: name of the runtime
        :return: runtime metadata
        """
        key = os.path.join('runtimes', runtime_name+".meta.json")
        try:
            json_str = self.backend_handler.get_object(self.storage_bucket, key)
        except StorageNoSuchKeyError:
            raise Exception('The runtime {} is not installed.'.format(runtime_name))  
        runtime_meta = json.loads(json_str.decode("ascii"))
        
        return runtime_meta
    
    def put_runtime_info(self, runtime_name, runtime_meta):
        """
        Puit the metadata given a runtime config.
        :param runtime: name of the runtime
        :param runtime_meta metadata
        """
        key = os.path.join('runtimes', runtime_name+".meta.json")
        self.backend_handler.put_object(self.storage_bucket, key, json.dumps(runtime_meta))
        
    def list_temporal_data(self, executor_id):
        """
        List the temporal data used by PyWren.
        :param bucket: bucket key
        :param prefix: prefix to search for
        :return: list of objects
        """
        return self.backend_handler.list_keys_with_prefix(self.storage_bucket, executor_id)
    
    def delete_temporal_data(self, key_list):
        """
        Delete temporal data from PyWren.
        :param bucket: bucket name
        :param key: data key
        """
        return self.backend_handler.delete_objects(self.storage_bucket, key_list)
