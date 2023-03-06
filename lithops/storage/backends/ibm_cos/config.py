#
# (C) Copyright IBM Corp. 2020
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

PUBLIC_ENDPOINT = 'https://s3.{}.cloud-object-storage.appdomain.cloud'
PRIVATE_ENDPOINT = 'https://s3.private.{}.cloud-object-storage.appdomain.cloud'
DIRECT_ENDPOINT = 'https://s3.direct.{}.cloud-object-storage.appdomain.cloud'


def load_config(config_data):

    if 'ibm_cos' not in config_data:
        config_data['ibm_cos'] = {}

    if 'ibm' in config_data and config_data['ibm'] is not None:
        temp = copy.deepcopy(config_data['ibm_cos'])
        config_data['ibm_cos'].update(config_data['ibm'])
        config_data['ibm_cos'].update(temp)

    compute_backend = config_data['lithops'].get('backend')

    if 'endpoint' not in config_data['ibm_cos'] and 'region' in config_data['ibm_cos']:
        region = config_data['ibm_cos']['region']
        config_data['ibm_cos']['endpoint'] = PUBLIC_ENDPOINT.format(region)

        if compute_backend == 'ibm_cf':
            config_data['ibm_cos']['private_endpoint'] = PRIVATE_ENDPOINT.format(region)

        elif compute_backend == 'code_engine':
            config_data['ibm_cos']['private_endpoint'] = DIRECT_ENDPOINT.format(region)

        elif compute_backend == 'ibm_vpc':
            config_data['ibm_cos']['private_endpoint'] = DIRECT_ENDPOINT.format(region)

    if compute_backend == 'ibm_cf':
        if 'private_endpoint' not in config_data['ibm_cos']:
            raise Exception('You must provide the private_endpoint to access to IBM COS')
        elif 'private' not in config_data['ibm_cos']['private_endpoint']:
            raise Exception('The private_endpoint you provided to access to IBM COS is not valid')
        if not config_data['ibm_cos']['private_endpoint'].startswith('http'):
            raise Exception('IBM COS Private Endpoint must start with http:// or https://')

    elif compute_backend == 'code_engine':
        if 'private_endpoint' not in config_data['ibm_cos']:
            raise Exception('You must provide the private_endpoint to access to IBM COS')
        elif 'direct' not in config_data['ibm_cos']['private_endpoint']:
            raise Exception('The private_endpoint you provided to access to IBM COS is not valid')
        if not config_data['ibm_cos']['private_endpoint'].startswith('http'):
            raise Exception('IBM COS Private Endpoint must start with http:// or https://')

    elif compute_backend == 'ibm_vpc':
        if 'private_endpoint' not in config_data['ibm_cos']:
            raise Exception('You must provide the private_endpoint to access to IBM COS')
        elif 'direct' not in config_data['ibm_cos']['private_endpoint']:
            raise Exception('The private_endpoint you provided to access to IBM COS is not valid. You must use the "direct" endpoint')
        if not config_data['ibm_cos']['private_endpoint'].startswith('http'):
            raise Exception('IBM COS Private Endpoint must start with http:// or https://')

    elif 'private_endpoint' in config_data['ibm_cos']:
        del config_data['ibm_cos']['private_endpoint']

    if not config_data['ibm_cos']['endpoint'].startswith('http'):
        raise Exception('IBM COS Endpoint must start with http:// or https://')

    if 'region' not in config_data['ibm_cos']:
        endpoint = config_data['ibm_cos']['endpoint']
        config_data['ibm_cos']['region'] = endpoint.split('//')[1].split('.')[1]

    if 'access_key' in config_data['ibm_cos']:
        config_data['ibm_cos']['access_key_id'] = config_data['ibm_cos'].pop('access_key')
    if 'secret_key' in config_data['ibm_cos']:
        config_data['ibm_cos']['secret_access_key'] = config_data['ibm_cos'].pop('secret_key')

    if 'storage_bucket' not in config_data['ibm_cos']:
        if not {'access_key_id', 'secret_access_key'}.issubset(config_data['ibm_cos']):
            msg = "'storage_bucket' parameter not found in config. "
            msg += "You must provide HMAC Credentials if you want the bucket to be automatically created"
            raise Exception(msg)
        cosc = config_data['ibm_cos']
        key = cosc.get('access_key_id') or cosc.get('api_key') or cosc.get('iam_api_key')
        region = config_data['ibm_cos']['region']
        config_data['ibm_cos']['storage_bucket'] = f'lithops-{region}-{key[:6].lower()}'
