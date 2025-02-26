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
import uuid

from lithops.constants import SA_DEFAULT_CONFIG_KEYS

DEFAULT_CONFIG_KEYS = {
    'master_instance_type': 't3.micro',
    'worker_instance_type': 't3.medium',
    'ssh_username': 'ubuntu',
    'ssh_password': str(uuid.uuid4()),
    'ssh_key_filename': '~/.ssh/id_rsa',
    'request_spot_instances': True,
    'delete_on_dismantle': True,
    'max_workers': 100,
    'worker_processes': 'AUTO',
    'public_subnet_cidr_block': '10.0.1.0/24'
}

REQ_PARAMS_1 = ('instance_id',)
REQ_PARAMS_2 = ('instance_role',)


def load_config(config_data):

    if not config_data['aws_ec2']:
        raise Exception("'aws_ec2' section is mandatory in the configuration")

    if 'aws' not in config_data:
        config_data['aws'] = {}

    temp = copy.deepcopy(config_data['aws_ec2'])
    config_data['aws_ec2'].update(config_data['aws'])
    config_data['aws_ec2'].update(temp)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['aws_ec2']:
            config_data['aws_ec2'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'standalone' not in config_data or config_data['standalone'] is None:
        config_data['standalone'] = {}

    for key in SA_DEFAULT_CONFIG_KEYS:
        if key in config_data['aws_ec2']:
            config_data['standalone'][key] = config_data['aws_ec2'].pop(key)
        elif key not in config_data['standalone']:
            config_data['standalone'][key] = SA_DEFAULT_CONFIG_KEYS[key]

    if config_data['standalone']['exec_mode'] == 'consume':
        params_to_check = REQ_PARAMS_1
        config_data['aws_ec2']['max_workers'] = 1
    else:
        params_to_check = REQ_PARAMS_2

    # iam_role is deprectaded. To be removed in a future release
    if 'iam_role' in config_data['aws_ec2']:
        config_data['aws_ec2']['instance_role'] = config_data['aws_ec2'].pop('iam_role')

    for param in params_to_check:
        if param not in config_data['aws_ec2']:
            msg = f"'{param}' is mandatory in the 'aws_ec2' section of the configuration"
            raise Exception(msg)

    if 'region_name' in config_data['aws_ec2']:
        config_data['aws_ec2']['region'] = config_data['aws_ec2'].pop('region_name')

    if 'region' not in config_data['aws_ec2']:
        raise Exception('"region" is mandatory under the "aws_ec2" or "aws" section of the configuration')
    elif 'region' not in config_data['aws']:
        config_data['aws']['region'] = config_data['aws_ec2']['region']
