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

import uuid

MANDATORY_PARAMETERS_1 = ('endpoint',
                          'vpc_name',
                          'resource_group_id',
                          'key_id',
                          'iam_api_key')

MANDATORY_PARAMETERS_2 = ('endpoint',
                          'vpc_id',
                          'resource_group_id',
                          'key_id',
                          'subnet_id',
                          'security_group_id',
                          'iam_api_key')


MANDATORY_PARAMETERS_3 = ('endpoint',
                          'instance_id',
                          'ip_address',
                          'iam_api_key')

BOOT_VOLUME_CAPACITY_DEFAULT = 100  # GB
BOOT_VOLUME_CAPACITY_CUSTOM = 10  # GB

DEFAULT_CONFIG_KEYS = {
    'image_id': 'r014-b7da49af-b46a-4099-99a4-c183d2d40ea8',  # ubuntu 20.04
    'master_profile_name': 'cx2-2x4',
    'profile_name': 'cx2-2x4',
    'boot_volume_profile': 'general-purpose',
    'ssh_username': 'root',
    'ssh_password': str(uuid.uuid4()),
    'ssh_key_filename': '~/.ssh/id_rsa',
    'delete_on_dismantle': True,
    'max_workers': 100,
    'worker_processes': 2
}


def load_config(config_data):
    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data['ibm_vpc'].update(config_data['ibm'])

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['ibm_vpc']:
            config_data['ibm_vpc'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'exec_mode' in config_data['standalone'] \
       and config_data['standalone']['exec_mode'] in ['create', 'reuse']:
        params_to_check = MANDATORY_PARAMETERS_2
    else:
        params_to_check = MANDATORY_PARAMETERS_3
        config_data['ibm_vpc']['max_workers'] = 1

    for param in params_to_check:
        if param not in config_data['ibm_vpc']:
            msg = "'{}' is mandatory in 'ibm_vpc' section of the configuration".format(param)
            raise Exception(msg)

    config_data['ibm_vpc']['endpoint'] = config_data['ibm_vpc']['endpoint'].replace('/v1', '')

    if not config_data['ibm_vpc'].get('boot_volume_capacity'):
        if config_data['ibm_vpc']['image_id'] == DEFAULT_CONFIG_KEYS['image_id']:
            config_data['ibm_vpc']['boot_volume_capacity'] = BOOT_VOLUME_CAPACITY_DEFAULT
        else:
            # The image built by lithops script has 10GB boot device
            config_data['ibm_vpc']['boot_volume_capacity'] = BOOT_VOLUME_CAPACITY_CUSTOM

    region = config_data['ibm_vpc']['endpoint'].split('//')[1].split('.')[0]
    if 'zone_name' not in config_data['ibm_vpc']:
        config_data['ibm_vpc']['zone_name'] = '{}-2'.format(region)
