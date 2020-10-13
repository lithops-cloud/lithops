#
# Copyright 2018 PyWren Team
# Copyright IBM Corp. 2020
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
import sys
import time
import tempfile
import pickle
import logging
import textwrap


logger = logging.getLogger(__name__)


func_key_suffix = "func.pickle"
agg_data_key_suffix = "aggdata.pickle"
data_key_suffix = "data.pickle"
output_key_suffix = "output.pickle"
status_key_suffix = "status.json"
init_key_suffix = ".init"


class StorageNoSuchKeyError(Exception):
    def __init__(self, bucket, key):
        msg = "No such key /{}/{} found in storage.".format(bucket, key)
        super(StorageNoSuchKeyError, self).__init__(msg)


class StorageConfigMismatchError(Exception):
    def __init__(self, current_path, prev_path):
        msg = "The data is stored at {}, but current storage is configured at {}.".format(
            prev_path, current_path)
        super(StorageConfigMismatchError, self).__init__(msg)


class CloudObject:
    def __init__(self, backend, bucket, key):
        self.backend = backend
        self.bucket = bucket
        self.key = key


class CloudObjectUrl:
    def __init__(self, url_path):
        self.path = url_path


def clean_bucket(storage, bucket, prefix, sleep=5, log=True):
    """
    Deletes all the files from COS. These files include the function,
    the data serialization and the function invocation results.
    """
    msg = "Going to delete all objects from bucket '{}'".format(bucket)
    msg = msg + " and prefix '{}'".format(prefix) if prefix else msg
    if log:
        logger.debug(msg)
    total_objects = 0
    objects_to_delete = storage.list_keys(bucket, prefix)

    while objects_to_delete:
        total_objects = total_objects + len(objects_to_delete)
        storage.delete_objects(bucket, objects_to_delete)
        time.sleep(sleep)
        objects_to_delete = storage.list_keys(bucket, prefix)
    if log:
        logger.debug('Finished deleting objects, total found: {}'.format(total_objects))


def delete_cloudobject(co_to_clean, storage_config):
    """
    Deletes cloudobjects from storage
    """
    co_to_delete = []
    for co in co_to_clean:
        co_to_delete.append((co.backend, co.bucket, co.key))

    with tempfile.NamedTemporaryFile(delete=False) as temp:
        pickle.dump(co_to_delete, temp)
        cobjs_path = temp.name

    script = """
    from lithops.storage import InternalStorage
    import pickle
    import os

    storage_config = {}
    cobjs_path = '{}'

    with open(cobjs_path, 'rb') as pk:
        co_to_delete = pickle.load(pk)

    internal_storage = InternalStorage(storage_config)

    for backend, bucket, key in co_to_delete:
        if backend == internal_storage.backend:
            internal_storage.storage.delete_object(bucket, key)

    if os.path.exists(cobjs_path):
        os.remove(cobjs_path)
    """.format(storage_config, cobjs_path)

    cmdstr = '{} -c "{}"'.format(sys.executable, textwrap.dedent(script))
    os.popen(cmdstr)

def create_runtime_meta_key(prefix, activation_id):
    """
    Create function key
    :param prefix: prefix
    :param executor_id: callset's ID
    :return: function key
    """
    func_key = '/'.join([prefix, activation_id, 'runtime_metadata'])
    return func_key


def create_func_key(prefix, executor_id, job_id):
    """
    Create function key
    :param prefix: prefix
    :param executor_id: callset's ID
    :return: function key
    """
    func_key = '/'.join([prefix, executor_id, job_id, func_key_suffix])
    return func_key


def create_agg_data_key(prefix, executor_id, job_id):
    """
    Create aggregate data key
    :param prefix: prefix
    :param executor_id: callset's ID
    :return: a key for aggregate data
    """
    return '/'.join([prefix, executor_id, job_id, agg_data_key_suffix])


def create_data_key(prefix, executor_id, job_id, call_id):
    """
    Create data key
    :param prefix: prefix
    :param executor_id: callset's ID
    :param call_id: call's ID
    :return: data key
    """
    return '/'.join([prefix, executor_id, job_id, call_id, data_key_suffix])


def create_output_key(prefix, executor_id, job_id, call_id):
    """
    Create output key
    :param prefix: prefix
    :param executor_id: callset's ID
    :param call_id: call's ID
    :return: output key
    """
    return '/'.join([prefix, executor_id, job_id, call_id, output_key_suffix])


def create_status_key(prefix, executor_id, job_id, call_id):
    """
    Create status key
    :param prefix: prefix
    :param executor_id: callset's ID
    :param call_id: call's ID
    :return: status key
    """
    return '/'.join([prefix, executor_id, job_id, call_id, status_key_suffix])


def create_init_key(prefix, executor_id, job_id, call_id, act_id):
    """
    Create init key
    :param prefix: prefix
    :param executor_id: callset's ID
    :param call_id: call's ID
    :return: output key
    """
    return '/'.join([prefix, executor_id, job_id, call_id,
                     '{}{}'.format(act_id, init_key_suffix)])


def create_keys(prefix, executor_id, job_id, call_id):
    """
    Create keys for data, output and status given callset and call IDs.
    :param prefix: prefix
    :param executor_id: callset's ID
    :param call_id: call's ID
    :return: data_key, output_key, status_key
    """
    data_key = create_data_key(prefix, executor_id, job_id, call_id)
    output_key = create_output_key(prefix, executor_id, job_id, call_id)
    status_key = create_status_key(prefix, executor_id, job_id, call_id)
    return data_key, output_key, status_key


def get_storage_path(storage_config):
    storage_bucket = storage_config['bucket']
    storage_backend = storage_config['backend']

    return [storage_backend, storage_bucket]


def check_storage_path(config, prev_path):
    current_path = get_storage_path(config)
    if current_path != prev_path:
        raise StorageConfigMismatchError(current_path, prev_path)
