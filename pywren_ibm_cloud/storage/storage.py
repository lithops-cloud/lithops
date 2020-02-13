import os
import json
import pickle
import logging
import importlib
from pywren_ibm_cloud.version import __version__
from pywren_ibm_cloud.config import CACHE_DIR, RUNTIMES_PREFIX, JOBS_PREFIX
from pywren_ibm_cloud.utils import is_pywren_function
from pywren_ibm_cloud.storage.utils import create_status_key, create_output_key, \
    status_key_suffix, init_key_suffix, CloudObject, StorageNoSuchKeyError

logger = logging.getLogger(__name__)


class Storage:
    """
    An Storage object is used by partitioner and other components to access
    underlying storage backend without exposing the the implementation details.
    """
    def __init__(self, pywren_config, storage_backend):
        self.pywren_config = pywren_config
        self.backend = storage_backend

        try:
            module_location = 'pywren_ibm_cloud.storage.backends.{}'.format(self.backend)
            sb_module = importlib.import_module(module_location)
            storage_config = self.pywren_config[self.backend]
            storage_config['user_agent'] = 'pywren-ibm-cloud/{}'.format(__version__)
            StorageBackend = getattr(sb_module, 'StorageBackend')
            self.storage_handler = StorageBackend(storage_config)
        except Exception as e:
            raise NotImplementedError("An exception was produced trying to create the "
                                      "'{}' storage backend: {}".format(self.backend, e))

    def get_storage_handler(self):
        return self.storage_handler

    def get_client(self):
        return self.storage_handler.get_client()


class InternalStorage:
    """
    An InternalStorage object is used by executors and other components to access
    underlying storage backend without exposing the the implementation details.
    """

    def __init__(self, storage_config, executor_id = None):
        self.config = storage_config
        self.backend = self.config['backend']
        self.bucket = self.config['bucket']
        self.executor_id = executor_id
        self.tmp_obj_count = 0

        try:
            module_location = 'pywren_ibm_cloud.storage.backends.{}'.format(self.backend)
            sb_module = importlib.import_module(module_location)
            StorageBackend = getattr(sb_module, 'StorageBackend')
            self.storage_handler = StorageBackend(self.config[self.backend], self.bucket, self.executor_id)
        except Exception as e:
            raise NotImplementedError("An exception was produced trying to create the "
                                      "'{}' storage backend: {}".format(self.backend, e))

    def get_storage_config(self):
        """
        Retrieves the configuration of this storage handler.
        :return: storage configuration
        """
        return self.config

    def put_data(self, key, data):
        """
        Put data object into storage.
        :param key: data key
        :param data: data content
        :return: None
        """
        return self.storage_handler.put_object(self.bucket, key, data)

    def put_func(self, key, func):
        """
        Put serialized function into storage.
        :param key: function key
        :param func: serialized function
        :return: None
        """
        return self.storage_handler.put_object(self.bucket, key, func)

    def get_data(self, key, stream=False, extra_get_args={}):
        """
        Get data object from storage.
        :param key: data key
        :return: data content
        """
        return self.storage_handler.get_object(self.bucket, key, stream, extra_get_args)

    def get_func(self, key):
        """
        Get serialized function from storage.
        :param key: function key
        :return: serialized function
        """
        return self.storage_handler.get_object(self.bucket, key)

    def put_object(self, content, bucket=None, key=None):
        """
        Put temporal data object into storage.
        :param key: data key
        :param data: data content
        :return: CloudObject instance
        """
        prefix = self.tmp_obj_prefix or 'tmp'
        key = key or 'cloudobject_{}'.format(self.tmp_obj_count)
        key = '/'.join([prefix, key])
        bucket = bucket or self.bucket
        self.storage_handler.put_object(bucket, key, content)
        self.tmp_obj_count += 1

        return CloudObject(self.backend, bucket, key)

    def get_object(self, cloudobject: CloudObject=None, bucket: str=None, key: str=None):
        """
        get temporal data object from storage.
        :param cloudobject: CloudObject instance
        :param key: data bucket
        :param key: data key
        :return: body text
        """
        if cloudobject:
            if cloudobject.storage_backend == self.backend:
                bucket = cloudobject.bucket
                key = cloudobject.key
                return self.storage_handler.get_object(bucket, key)
            else:
                raise Exception("CloudObject: Invalid Storage backend")
        elif (bucket and key) or key:
            bucket = bucket or self.bucket
            return self.storage_handler.get_object(bucket, key)
        else:
            return None

    def get_job_status(self, executor_id, job_id):
        """
        Get the status of a callset.
        :param executor_id: executor's ID
        :return: A list of call IDs that have updated status.
        """
        callset_prefix = '/'.join([JOBS_PREFIX, executor_id, job_id])
        keys = self.storage_handler.list_keys(self.bucket, callset_prefix)

        running_keys = [k[len(JOBS_PREFIX)+1:-len(init_key_suffix)].rsplit("/", 3)
                        for k in keys if init_key_suffix in k]
        running_callids = [((k[0], k[1], k[2]), k[3]) for k in running_keys]

        done_keys = [k for k in keys if status_key_suffix in k]
        done_callids = [tuple(k[len(JOBS_PREFIX)+1:].rsplit("/", 3)[:3]) for k in done_keys]

        return set(running_callids), set(done_callids)

    def get_call_status(self, executor_id, job_id, call_id):
        """
        Get status of a call.
        :param executor_id: executor ID of the call
        :param call_id: call ID of the call
        :return: A dictionary containing call's status, or None if no updated status
        """
        status_key = create_status_key(JOBS_PREFIX, executor_id, job_id, call_id)
        try:
            data = self.storage_handler.get_object(self.bucket, status_key)
            return json.loads(data.decode('ascii'))
        except StorageNoSuchKeyError:
            return None

    def get_call_output(self, executor_id, job_id, call_id):
        """
        Get the output of a call.
        :param executor_id: executor ID of the call
        :param call_id: call ID of the call
        :return: Output of the call.
        """
        output_key = create_output_key(JOBS_PREFIX, executor_id, job_id, call_id)
        try:
            return self.storage_handler.get_object(self.bucket, output_key)
        except StorageNoSuchKeyError:
            return None

    def get_runtime_meta(self, key):
        """
        Get the metadata given a runtime name.
        :param runtime: name of the runtime
        :return: runtime metadata
        """
        path = [RUNTIMES_PREFIX, __version__,  key+".meta.json"]
        filename_local_path = os.path.join(CACHE_DIR, *path)

        if os.path.exists(filename_local_path) and not is_pywren_function():
            logger.debug("Runtime metadata found in local cache")
            with open(filename_local_path, "r") as f:
                runtime_meta = json.loads(f.read())
            return runtime_meta
        else:
            logger.debug("Runtime metadata not found in local cache. Retrieving it from storage")
            try:
                obj_key = '/'.join(path).replace('\\', '/')
                json_str = self.storage_handler.get_object(self.bucket, obj_key)
                runtime_meta = json.loads(json_str.decode("ascii"))
                # Save runtime meta to cache
                if not os.path.exists(os.path.dirname(filename_local_path)):
                    os.makedirs(os.path.dirname(filename_local_path))

                with open(filename_local_path, "w") as f:
                    f.write(json.dumps(runtime_meta))

                return runtime_meta
            except StorageNoSuchKeyError:
                raise Exception('The runtime {} is not installed.'.format(obj_key))

    def put_runtime_meta(self, key, runtime_meta):
        """
        Puit the metadata given a runtime config.
        :param runtime: name of the runtime
        :param runtime_meta metadata
        """
        path = [RUNTIMES_PREFIX, __version__,  key+".meta.json"]
        obj_key = '/'.join(path).replace('\\', '/')
        logger.debug("Uploading runtime metadata to: /{}/{}".format(self.bucket, obj_key))
        self.storage_handler.put_object(self.bucket, obj_key, json.dumps(runtime_meta))

        if not is_pywren_function():
            filename_local_path = os.path.join(CACHE_DIR, *path)
            logger.debug("Storing runtime metadata into local cache: {}".format(filename_local_path))

            if not os.path.exists(os.path.dirname(filename_local_path)):
                os.makedirs(os.path.dirname(filename_local_path))

            with open(filename_local_path, "w") as f:
                f.write(json.dumps(runtime_meta))

    def delete_runtime_meta(self, key):
        """
        Puit the metadata given a runtime config.
        :param runtime: name of the runtime
        :param runtime_meta metadata
        """
        path = [RUNTIMES_PREFIX, __version__,  key+".meta.json"]
        obj_key = '/'.join(path).replace('\\', '/')
        filename_local_path = os.path.join(CACHE_DIR, *path)
        if os.path.exists(filename_local_path):
            os.remove(filename_local_path)
        self.storage_handler.delete_object(self.bucket, obj_key)

    def list_tmp_data(self, prefix):
        """
        List the temporal data used by PyWren.
        :param bucket: bucket key
        :param prefix: prefix to search for
        :return: list of objects
        """
        return self.storage_handler.list_keys(self.bucket, prefix)

    def delete_temporal_data(self, key_list):
        """
        Delete temporal data from PyWren.
        :param bucket: bucket name
        :param key: data key
        """
        return self.storage_handler.delete_objects(self.bucket, key_list)
