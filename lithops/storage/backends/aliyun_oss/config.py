#
# (C) Copyright Cloudlab URV 2020
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
import hashlib


CONNECTION_POOL_SIZE = 300

REQ_PARAMS_1 = ('access_key_id', 'access_key_secret')

PUBLIC_ENDPOINT = "oss-{}.aliyuncs.com"
INTERNAL_ENDPOINT = "oss-{}-internal.aliyuncs.com"


def load_config(config_data=None):
    if 'aliyun' not in config_data:
        raise Exception("'aliyun' section is mandatory in the configuration")

    if 'aliyun_oss' not in config_data:
        config_data['aliyun_oss'] = {}

    for param in REQ_PARAMS_1:
        if param not in config_data['aliyun']:
            msg = f'"{param}" is mandatory under "aliyun" section of the configuration'
            raise Exception(msg)

    temp = copy.deepcopy(config_data['aliyun_oss'])
    config_data['aliyun_oss'].update(config_data['aliyun'])
    config_data['aliyun_oss'].update(temp)

    if 'region' not in config_data['aliyun_oss']:
        raise Exception('"region" is mandatory under the "aliyun_oss" or "aliyun" section of the configuration')

    region = config_data['aliyun_oss']['region']
    config_data['aliyun_oss']['public_endpoint'] = PUBLIC_ENDPOINT.format(region)
    config_data['aliyun_oss']['internal_endpoint'] = INTERNAL_ENDPOINT.format(region)

    if 'storage_bucket' not in config_data['aliyun_oss']:
        ossc = config_data['aliyun_oss']
        key = ossc['access_key_id']
        endpoint = hashlib.sha1(ossc['public_endpoint'].encode()).hexdigest()[:6]
        config_data['aliyun_oss']['storage_bucket'] = f'lithops-{endpoint}-{key[:6].lower()}'
