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

from pywren_ibm_cloud.storage.exceptions import StorageConfigMismatchError

func_key_suffix = "func.pickle"
agg_data_key_suffix = "aggdata.pickle"
data_key_suffix = "data.pickle"
output_key_suffix = "output.pickle"
status_key_suffix = "status.json"

def create_func_key(prefix, executor_id, callgroup_id):
    """
    Create function key
    :param prefix: prefix
    :param executor_id: callset's ID
    :return: function key
    """
    func_key = os.path.join(prefix, executor_id, callgroup_id, func_key_suffix)
    return func_key


def create_agg_data_key(prefix, executor_id, callgroup_id):
    """
    Create aggregate data key
    :param prefix: prefix
    :param executor_id: callset's ID
    :return: a key for aggregate data
    """
    agg_data_key = os.path.join(prefix, executor_id, callgroup_id, agg_data_key_suffix)
    return agg_data_key


def create_data_key(prefix, executor_id, callgroup_id, call_id):
    """
    Create data key
    :param prefix: prefix
    :param executor_id: callset's ID
    :param call_id: call's ID
    :return: data key
    """
    return os.path.join(prefix, executor_id, callgroup_id, call_id, data_key_suffix)


def create_output_key(prefix, executor_id, callgroup_id, call_id):
    """
    Create output key
    :param prefix: prefix
    :param executor_id: callset's ID
    :param call_id: call's ID
    :return: output key
    """
    return os.path.join(prefix, executor_id, callgroup_id, call_id, output_key_suffix)


def create_group_prefix(prefix, executor_id, callgroup_id):
    """
    Create callgroup prefix key
    :param prefix: prefix
    :param executor_id: callset's ID
    :param callgroup_id: call's ID
    :return: callgroup prefix key
    """
    return os.path.join(prefix, executor_id, callgroup_id)


def get_group_calls_ids(group_keys):
    """
    Get list of all calls ids of a callgroup
    :param group_keys: list of all keys of a callgroup
    :return: calls ids of a callgroup
    """
    calls_ids = []
    for key in group_keys:
        if os.path.split(key)[1] == output_key_suffix:
            key_without_suffix = os.path.split(key)[0]
            calls_ids.append(os.path.split(key_without_suffix)[1])

    return calls_ids


def create_status_key(prefix, executor_id, callgroup_id, call_id):
    """
    Create status key
    :param prefix: prefix
    :param executor_id: callset's ID
    :param call_id: call's ID
    :return: status key
    """
    return os.path.join(prefix, executor_id, callgroup_id, call_id, status_key_suffix)


def create_keys(prefix, executor_id, callgroup_id, call_id):
    """
    Create keys for data, output and status given callset and call IDs.
    :param prefix: prefix
    :param executor_id: callset's ID
    :param call_id: call's ID
    :return: data_key, output_key, status_key
    """
    data_key = create_data_key(prefix, executor_id, callgroup_id, call_id)
    output_key = create_output_key(prefix, executor_id, callgroup_id, call_id)
    status_key = create_status_key(prefix, executor_id, callgroup_id, call_id)
    return data_key, output_key, status_key


def get_storage_path(storage_config):
    storage_bucket = storage_config['storage_bucket']
    storage_prefix = storage_config['storage_prefix']
    storage_backend = storage_config['storage_backend']
    
    if storage_backend != 'ibm_cos' and storage_backend != 'swift':
        raise NotImplementedError(
            ("Using {} as storage backend is not supported yet").format(
             storage_backend))

    return [storage_backend, storage_bucket, storage_prefix]


def check_storage_path(config, prev_path):
    current_path = get_storage_path(config)
    if current_path != prev_path:
        raise StorageConfigMismatchError(current_path, prev_path)
