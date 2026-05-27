#
# Copyright Cloudlab URV 2021
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
import os
import uuid

from lithops.constants import SA_DEFAULT_CONFIG_KEYS


DEFAULT_CONFIG_KEYS = {
    'master_instance_type': 'e2-small',
    'worker_instance_type': 'e2-standard-2',
    'boot_disk_size': 50,
    'boot_disk_type': 'pd-standard',
    'network_cidr': '10.0.0.0/16',
    'subnet_cidr': '10.0.0.0/24',
    'source_image': 'projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64',
    'ssh_username': 'ubuntu',
    'ssh_password': str(uuid.uuid4()),
    'delete_on_dismantle': True,
    'max_workers': 100,
    'request_spot_instances': False,
    'worker_processes': 'AUTO'
}

MANDATORY_PARAMETERS_1 = ('project_name', 'zone', 'instance_name')
MANDATORY_PARAMETERS_2 = ('project_name', 'zone')


def load_config(config_data):
    if not config_data['gcp_compute_engine']:
        raise Exception("'gcp_compute_engine' section is mandatory in the configuration")

    if 'gcp' not in config_data:
        config_data['gcp'] = {}

    temp = copy.deepcopy(config_data['gcp_compute_engine'])
    config_data['gcp_compute_engine'].update(config_data['gcp'])
    config_data['gcp_compute_engine'].update(temp)

    if 'credentials_path' in config_data['gcp_compute_engine']:
        config_data['gcp_compute_engine']['credentials_path'] = os.path.expanduser(
            config_data['gcp_compute_engine']['credentials_path']
        )

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['gcp_compute_engine']:
            config_data['gcp_compute_engine'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'standalone' not in config_data or config_data['standalone'] is None:
        config_data['standalone'] = {}

    for key in SA_DEFAULT_CONFIG_KEYS:
        if key in config_data['gcp_compute_engine']:
            config_data['standalone'][key] = config_data['gcp_compute_engine'].pop(key)
        elif key not in config_data['standalone']:
            config_data['standalone'][key] = SA_DEFAULT_CONFIG_KEYS[key]

    if config_data['standalone']['exec_mode'] == 'consume':
        params_to_check = MANDATORY_PARAMETERS_1
        config_data['gcp_compute_engine']['max_workers'] = 1
    else:
        params_to_check = MANDATORY_PARAMETERS_2

    for param in params_to_check:
        if param not in config_data['gcp_compute_engine']:
            msg = f"'{param}' is mandatory in the 'gcp_compute_engine' or 'gcp' section of the configuration"
            raise Exception(msg)

    if 'region' not in config_data['gcp_compute_engine']:
        zone = config_data['gcp_compute_engine']['zone']
        config_data['gcp_compute_engine']['region'] = '-'.join(zone.split('-')[:-1])

    if 'region' not in config_data['gcp'] and 'region' in config_data['gcp_compute_engine']:
        config_data['gcp']['region'] = config_data['gcp_compute_engine']['region']
