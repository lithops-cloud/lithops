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

import datetime
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


IMAGE_ID_DEFAULT = 'r014-b7da49af-b46a-4099-99a4-c183d2d40ea8'  # ubuntu 20.04
PROFILE_NAME_DEFAULT = 'cx2-2x4'
BOOT_VOLUME_PROFILE_DEFAULT = 'general-purpose'
BOOT_VOLUME_CAPACITY_DEFAULT = 100  # GB
BOOT_VOLUME_CAPACITY_CUSTOM = 10  # GB
VM_USER_DEFAULT = 'root'
MAX_WORKERS = 100


CLOUD_CONFIG = """
#cloud-config
bootcmd:
    - echo '{0}:{1}' | chpasswd
    - sed -i '/PasswordAuthentication no/c\PasswordAuthentication yes' /etc/ssh/sshd_config
    - echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
runcmd:
    - systemctl restart sshd
"""


def load_config(config_data):
    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data['ibm_vpc'].update(config_data['ibm'])

    if 'exec_mode' in config_data['standalone'] \
       and config_data['standalone']['exec_mode'] in ['create', 'reuse']:
        params_to_check = MANDATORY_PARAMETERS_2
    else:
        params_to_check = MANDATORY_PARAMETERS_3

    for param in params_to_check:
        if param not in config_data['ibm_vpc']:
            msg = "{} is mandatory in 'ibm_vpc' section of the configuration".format(param)
            raise Exception(msg)

    config_data['ibm_vpc']['endpoint'] = config_data['ibm_vpc']['endpoint'].replace('/v1', '')

    if 'version' not in config_data:
        # it is not safe to use version as today() due to timezone differences. may fail at midnight. better use yesterday
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        config_data['ibm_vpc']['version'] = yesterday.strftime('%Y-%m-%d')

    if 'ssh_username' not in config_data['ibm_vpc']:
        config_data['ibm_vpc']['ssh_username'] = VM_USER_DEFAULT

    if 'ssh_password' not in config_data['ibm_vpc']:
        config_data['ibm_vpc']['ssh_password'] = str(uuid.uuid4())

    if 'image_id' not in config_data['ibm_vpc']:
        config_data['ibm_vpc']['image_id'] = IMAGE_ID_DEFAULT

    if 'boot_volume_profile' not in config_data['ibm_vpc']:
        config_data['ibm_vpc']['boot_volume_profile'] = BOOT_VOLUME_PROFILE_DEFAULT

    if 'boot_volume_capacity' not in config_data['ibm_vpc']:
        if config_data['ibm_vpc']['image_id'] == IMAGE_ID_DEFAULT:
            config_data['ibm_vpc']['boot_volume_capacity'] = BOOT_VOLUME_CAPACITY_DEFAULT
        else:
            # Image built by the lithops script has 10GB boot device
            config_data['ibm_vpc']['boot_volume_capacity'] = BOOT_VOLUME_CAPACITY_CUSTOM

    if 'profile_name' not in config_data['ibm_vpc']:
        config_data['ibm_vpc']['profile_name'] = PROFILE_NAME_DEFAULT

    if 'master_profile_name' not in config_data['ibm_vpc']:
        config_data['ibm_vpc']['master_profile_name'] = PROFILE_NAME_DEFAULT

    region = config_data['ibm_vpc']['endpoint'].split('//')[1].split('.')[0]
    if 'zone_name' not in config_data['ibm_vpc']:
        config_data['ibm_vpc']['zone_name'] = '{}-2'.format(region)

    if 'delete_on_dismantle' not in config_data['ibm_vpc']:
        config_data['ibm_vpc']['delete_on_dismantle'] = True

    if 'workers' not in config_data['lithops'] or \
       config_data['lithops']['workers'] > MAX_WORKERS:
        config_data['lithops']['workers'] = MAX_WORKERS
