#
# Copyright IBM Corp. 2023
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

import copy
import uuid

from lithops.constants import SA_DEFAULT_CONFIG_KEYS

DEFAULT_CONFIG_KEYS = {
    'master_instance_type': 'Standard_B1s',
    'worker_instance_type': 'Standard_B2s',
    'ssh_username': 'ubuntu',
    'ssh_password': str(uuid.uuid4()),
    'request_spot_instances': True,
    'delete_on_dismantle': False,
    'max_workers': 100,
    'worker_processes': 2
}

REQ_PARAMS_1 = ('resource_group', 'subscription_id', 'region')
REQ_PARAMS_2 = ('instance_name',)


def load_config(config_data):

    if 'azure' in config_data and config_data['azure'] is not None:
        temp = copy.deepcopy(config_data['azure_vms'])
        config_data['azure_vms'].update(config_data['azure'])
        config_data['azure_vms'].update(temp)

    if not config_data['azure_vms']:
        raise Exception("'azure_vms' section is mandatory in the configuration")

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['azure_vms']:
            config_data['azure_vms'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'standalone' not in config_data or config_data['standalone'] is None:
        config_data['standalone'] = {}

    for key in SA_DEFAULT_CONFIG_KEYS:
        if key in config_data['azure_vms']:
            config_data['standalone'][key] = config_data['azure_vms'].pop(key)
        elif key not in config_data['standalone']:
            config_data['standalone'][key] = SA_DEFAULT_CONFIG_KEYS[key]

    if 'location' in config_data['azure_vms']:
        config_data['azure_vms']['region'] = config_data['azure_vms'].pop('location')

    for param in REQ_PARAMS_1:
        if param not in config_data['azure_vms']:
            msg = f"'{param}' is mandatory in the 'azure' or 'azure_vms' section of the configuration"
            raise Exception(msg)

    if config_data['standalone']['exec_mode'] == 'consume':
        config_data['azure_vms']['max_workers'] = 1
        for param in REQ_PARAMS_2:
            if param not in config_data['azure_vms']:
                msg = f"'{param}' is mandatory in the 'azure_vms' section of the configuration"
                raise Exception(msg)
