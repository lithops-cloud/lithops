# (C) Copyright Cloudlab URV 2023
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
import copy


CONNECTION_POOL_SIZE = 300

REQ_PARAMS_1 = ('compartment_id', 'user', 'key_file', 'region', 'tenancy', 'fingerprint')


def load_config(config_data=None):

    if 'oracle' not in config_data:
        raise Exception("'oracle' section is mandatory in the configuration")

    if 'oracle_oss' not in config_data:
        config_data['oracle_oss'] = {}

    for param in REQ_PARAMS_1:
        if param not in config_data['oracle']:
            msg = f'"{param}" is mandatory under "oracle" section of the configuration'
            raise Exception(msg)

    temp = copy.deepcopy(config_data['oracle_oss'])
    config_data['oracle_oss'].update(config_data['oracle'])
    config_data['oracle_oss'].update(temp)

    if 'storage_bucket' not in config_data['oracle_oss']:
        user = config_data['oracle_oss']['user']
        region = config_data['oracle_oss']['region']
        config_data['oracle_oss']['storage_bucket'] = f'lithops-{region}-{user[-8:-1].lower()}'
