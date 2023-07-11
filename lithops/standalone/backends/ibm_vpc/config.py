#
# (C) Copyright Cloudlab URV 2020
# (C) Copyright IBM Corp. 2023
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

MANDATORY_PARAMETERS_1 = ('instance_id',
                          'floating_ip',
                          'iam_api_key')

MANDATORY_PARAMETERS_2 = ('resource_group_id',
                          'iam_api_key')

DEFAULT_CONFIG_KEYS = {
    'master_profile_name': 'cx2-2x4',
    'worker_profile_name': 'cx2-2x4',
    'boot_volume_profile': 'general-purpose',
    'ssh_username': 'root',
    'ssh_password': str(uuid.uuid4()),
    'ssh_key_filename': '~/.ssh/id_rsa',
    'delete_on_dismantle': True,
    'max_workers': 100,
    'worker_processes': 2,
    'boot_volume_capacity': 100
}

VPC_ENDPOINT = "https://{}.iaas.cloud.ibm.com"

REGIONS = ["jp-tok", "jp-osa", "au-syd", "eu-gb", "eu-de", "eu-es", "us-south", "us-east", "br-sao", "ca-tor"]

def load_config(config_data):

    if 'ibm' in config_data and config_data['ibm'] is not None:
        temp = copy.deepcopy(config_data['ibm_vpc'])
        config_data['ibm_vpc'].update(config_data['ibm'])
        config_data['ibm_vpc'].update(temp)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['ibm_vpc']:
            config_data['ibm_vpc'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'standalone' not in config_data or config_data['standalone'] is None:
        config_data['standalone'] = {}

    for key in SA_DEFAULT_CONFIG_KEYS:
        if key in config_data['ibm_vpc']:
            config_data['standalone'][key] = config_data['ibm_vpc'].pop(key)
        elif key not in config_data['standalone']:
            config_data['standalone'][key] = SA_DEFAULT_CONFIG_KEYS[key]

    if config_data['standalone']['exec_mode'] == 'consume':
        params_to_check = MANDATORY_PARAMETERS_1
        config_data['ibm_vpc']['max_workers'] = 1
    else:
        params_to_check = MANDATORY_PARAMETERS_2

    for param in params_to_check:
        if param not in config_data['ibm_vpc']:
            msg = f"'{param}' is mandatory in 'ibm_vpc' section of the configuration"
            raise Exception(msg)

    if "profile_name" in config_data['ibm_vpc']:
        config_data['ibm_vpc']['worker_profile_name'] = config_data['ibm_vpc']['profile_name']

    if "region" not in config_data['ibm_vpc'] and "endpoint" not in config_data['ibm_vpc']:
        msg = "'region' or 'endpoint' parameter is mandatory in 'ibm_vpc' section of the configuration"
        raise Exception(msg)

    if 'endpoint' in config_data['ibm_vpc']:
        endpoint = config_data['ibm_vpc']['endpoint']
        config_data['ibm_vpc']['region'] = endpoint.split('//')[1].split('.')[0]

    elif "region" in config_data['ibm_vpc']:
        region = config_data['ibm_vpc']['region']
        if region not in REGIONS:
            msg = f"'region' conig parameter in 'ibm_vpc' section must be one of {REGIONS}"
            raise Exception(msg)
        config_data['ibm_vpc']['endpoint'] = VPC_ENDPOINT.format(region)

    config_data['ibm_vpc']['endpoint'] = config_data['ibm_vpc']['endpoint'].replace('/v1', '')

    if 'ibm' not in config_data or config_data['ibm'] is None:
        config_data['ibm'] = {}

    if 'region' not in config_data['ibm']:
        config_data['ibm']['region'] = config_data['ibm_vpc']['region']
