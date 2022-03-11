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

DEFAULT_CONFIG_KEYS = {
    'master_instance_type': 't2.micro',
    'worker_instance_type': 't2.medium',
    'ssh_username': 'ubuntu',
    'ssh_password': str(uuid.uuid4()),
    'ssh_key_filename': '~/.ssh/id_rsa',
    'request_spot_instances': True,
    'delete_on_dismantle': True,
    'max_workers': 100,
    'worker_processes': 2
}


REQ_PARAMS_1 = ('instance_id', 'region_name')
REQ_PARAMS_2 = ('region_name', 'vpc_id', 'iam_role', 'key_name', 'security_group_id')


def load_config(config_data):

    if 'aws' not in config_data:
        raise Exception("'aws' section are mandatory in the configuration")

    if not {'access_key_id', 'secret_access_key'}.issubset(set(config_data['aws'])):
        raise Exception("'access_key_id' and 'secret_access_key' are mandatory under 'aws' section")

    if 'exec_mode' not in config_data['standalone'] \
       or config_data['standalone']['exec_mode'] == 'consume':
        params_to_check = REQ_PARAMS_1
        config_data['aws_ec2']['max_workers'] = 1
    else:
        params_to_check = REQ_PARAMS_2

    for param in params_to_check:
        if param not in config_data['aws_ec2']:
            msg = "'{}' is mandatory in 'aws_ec2' section of the configuration".format(param)
            raise Exception(msg)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['aws_ec2']:
            config_data['aws_ec2'][key] = DEFAULT_CONFIG_KEYS[key]

    config_data['aws_ec2'].update(config_data['aws'])
