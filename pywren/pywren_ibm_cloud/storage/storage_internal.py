import os
import json
from .cos_backend import COSBackend
from .exceptions import StorageNoSuchKeyError
from .storage_utils import create_status_key, create_output_key, status_key_suffix

class Storage(object):
    """
    A Storage object is used by executors and other components to access underlying storage backend
    without exposing the the implementation details.
    """

    def __init__(self, config):
        self.storage_config = config
        self.backend_type = self.storage_config['storage_backend']
        self.storage_bucket =  self.storage_config['storage_bucket']
        self.prefix = self.storage_config['storage_prefix']

        if self.backend_type == 'ibm_cos':
            self.backend_handler = COSBackend(self.storage_config['backend_config'])
        else:
            raise NotImplementedError(("Using {} as storage backend is" +
                                       "not supported yet").format(self.backend_type))

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

    def get_storage_config(self):
        """
        Retrieves the configuration of this storage handler.
        :return: storage configuration
        """
        return self.storage_config

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