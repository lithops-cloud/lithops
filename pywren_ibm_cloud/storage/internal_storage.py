import os
import json
import logging
from ..version import __version__
from .backends.ibm_cos import IbmCosStorageBackend
from .backends.swift import SwiftStorageBackend
from .exceptions import StorageNoSuchKeyError
from .storage_utils import create_status_key, create_output_key, status_key_suffix


LOCAL_HOME_DIR = os.path.expanduser('~')
logger = logging.getLogger(__name__)


class InternalStorage:
    """
    An InternalStorage object is used by executors and other components to access underlying storage backend
    without exposing the the implementation details.
    """

    def __init__(self, storage_config):

        self.storage_config = storage_config
        self.storage_backend = self.storage_config['storage_backend']
        self.storage_bucket = self.storage_config['storage_bucket']
        self.prefix = self.storage_config['storage_prefix']

        if self.storage_backend == 'ibm_cos':
            self.storage_handler = IbmCosStorageBackend(self.storage_config['ibm_cos'])
        elif self.storage_backend == 'swift':
            self.storage_handler = SwiftStorageBackend(self.storage_config['swift'])
        else:
            raise NotImplementedError(("Using {} as internal storage backend is" +
                                       "not supported yet").format(self.storage_backend))

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
        return self.storage_handler.put_object(self.storage_bucket, key, data)

    def put_func(self, key, func):
        """
        Put serialized function into storage.
        :param key: function key
        :param func: serialized function
        :return: None
        """
        return self.storage_handler.put_object(self.storage_bucket, key, func)

    def get_data(self, key, stream=False, extra_get_args={}):
        """
        Get data object from storage.
        :param key: data key
        :return: data content
        """
        return self.storage_handler.get_object(self.storage_bucket, key, stream, extra_get_args)

    def get_func(self, key):
        """
        Get serialized function from storage.
        :param key: function key
        :return: serialized function
        """
        return self.storage_handler.get_object(self.storage_bucket, key)

    def get_callset_status(self, executor_id):
        """
        Get the status of a callset.
        :param executor_id: executor's ID
        :return: A list of call IDs that have updated status.
        """
        # TODO: a better API for this is to return status for all calls in the callset. We'll fix
        #  this in scheduler refactoring.
        callset_prefix = '/'.join([self.prefix, executor_id])
        keys = self.storage_handler.list_keys_with_prefix(self.storage_bucket, callset_prefix)
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
            data = self.storage_handler.get_object(self.storage_bucket, status_key)
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
            return self.storage_handler.get_object(self.storage_bucket, output_key)
        except StorageNoSuchKeyError:
            return None

    def get_runtime_info(self, key):
        """
        Get the metadata given a runtime name.
        :param runtime: name of the runtime
        :return: runtime metadata
        """
        path = ['runtimes', __version__,  key+".meta.json"]
        filename_local_path = os.path.join(LOCAL_HOME_DIR, '.pywren', *path)

        if os.path.exists(filename_local_path):
            logger.debug("Runtime metadata found in local cache")
            with open(filename_local_path, "r") as f:
                runtime_meta = json.loads(f.read())
            return runtime_meta
        else:
            logger.debug("Runtime metadata not found in local cache. Retrieving it from storage")
            try:
                obj_key = '/'.join(path).replace('\\', '/')
                json_str = self.storage_handler.get_object(self.storage_bucket, obj_key)
                runtime_meta = json.loads(json_str.decode("ascii"))
                # Save runtime meta to cache
                if not os.path.exists(os.path.dirname(filename_local_path)):
                    os.makedirs(os.path.dirname(filename_local_path))

                with open(filename_local_path, "w") as f:
                    f.write(json.dumps(runtime_meta))

                return runtime_meta
            except StorageNoSuchKeyError:
                raise Exception('The runtime {} is not installed.'.format(obj_key))

    def put_runtime_info(self, key, runtime_meta):
        """
        Puit the metadata given a runtime config.
        :param runtime: name of the runtime
        :param runtime_meta metadata
        """
        path = ['runtimes', __version__,  key+".meta.json"]
        obj_key = '/'.join(path).replace('\\', '/')
        # logger.debug("Uploading Runtime metadata to: {}/{}".format(self.storage_bucket, obj_key))
        self.storage_handler.put_object(self.storage_bucket, obj_key, json.dumps(runtime_meta))

        filename_local_path = os.path.join(LOCAL_HOME_DIR, '.pywren', *path)
        # logger.debug("Saving runtime metadata in local cache: {}".format(filename_local_path))

        if not os.path.exists(os.path.dirname(filename_local_path)):
            os.makedirs(os.path.dirname(filename_local_path))

        with open(filename_local_path, "w") as f:
            f.write(json.dumps(runtime_meta))

    def delete_runtime_info(self, key):
        """
        Puit the metadata given a runtime config.
        :param runtime: name of the runtime
        :param runtime_meta metadata
        """
        path = ['runtimes', __version__,  key+".meta.json"]
        obj_key = '/'.join(path).replace('\\', '/')
        filename_local_path = os.path.join(LOCAL_HOME_DIR, '.pywren', *path)
        if os.path.exists(filename_local_path):
            os.remove(filename_local_path)
        self.storage_handler.delete_object(self.storage_bucket, obj_key)

    def list_tmp_data(self, prefix):
        """
        List the temporal data used by PyWren.
        :param bucket: bucket key
        :param prefix: prefix to search for
        :return: list of objects
        """
        return self.storage_handler.list_keys_with_prefix(self.storage_bucket, prefix)

    def delete_temporal_data(self, key_list):
        """
        Delete temporal data from PyWren.
        :param bucket: bucket name
        :param key: data key
        """
        return self.storage_handler.delete_objects(self.storage_bucket, key_list)
