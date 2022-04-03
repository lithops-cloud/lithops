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
        raise Exception("ibm_cos section is mandatory in the configuration")

    compute_backend = config_data['lithops'].get('backend')

    if 'region' in config_data['ibm_cos']:
        region = config_data['ibm_cos']['region']
        config_data['ibm_cos']['endpoint'] = PUBLIC_ENDPOINT.format(region)

        if compute_backend == 'ibm_cf':
            config_data['ibm_cos']['private_endpoint'] = PRIVATE_ENDPOINT.format(region)

        elif compute_backend == 'code_engine':
            config_data['ibm_cos']['private_endpoint'] = DIRECT_ENDPOINT.format(region)

        elif compute_backend == 'ibm_vpc':
            config_data['ibm_cos']['private_endpoint'] = DIRECT_ENDPOINT.format(region)

    if compute_backend == 'ibm_cf':
        # Private endpoint is mandatory when using IBM CF
        if 'private_endpoint' not in config_data['ibm_cos']:
            raise Exception('You must provide the private_endpoint to access to IBM COS')
        elif 'private' not in config_data['ibm_cos']['private_endpoint']:
            raise Exception('The private_endpoint you provided to access to IBM COS is not valid')
        if not config_data['ibm_cos']['private_endpoint'].startswith('http'):
            raise Exception('IBM COS Private Endpoint must start with http:// or https://')

    elif compute_backend == 'code_engine':
        # Private endpoint is mandatory when using IBM CF
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
            raise Exception('The private_endpoint you provided to access to IBM COS is not valid')
        if not config_data['ibm_cos']['private_endpoint'].startswith('http'):
            raise Exception('IBM COS Private Endpoint must start with http:// or https://')

    elif 'private_endpoint' in config_data['ibm_cos']:
        del config_data['ibm_cos']['private_endpoint']

    required_keys_1 = ('endpoint', 'api_key')
    required_keys_2 = ('endpoint', 'secret_key', 'access_key')
    required_keys_3 = ('endpoint', 'ibm:iam_api_key')

    if 'ibm' in config_data and config_data['ibm'] is not None:
        # in order to support sepparate api keys for cos and for compute
        temp = copy.deepcopy(config_data['ibm_cos'])
        config_data['ibm_cos'].update(config_data['ibm'])
        config_data['ibm_cos'].update(temp)

    if not set(required_keys_1) <= set(config_data['ibm_cos']) and \
       not set(required_keys_2) <= set(config_data['ibm_cos']) and \
       ('endpoint' not in config_data['ibm_cos'] or 'iam_api_key' not in config_data['ibm_cos']
       or config_data['ibm_cos']['iam_api_key'] is None):
        raise Exception('You must provide {}, {} or {} to access to IBM COS'
                        .format(required_keys_1, required_keys_2, required_keys_3))

    if not config_data['ibm_cos']['endpoint'].startswith('http'):
        raise Exception('IBM COS Endpoint must start with http:// or https://')

    if 'region' not in config_data['ibm_cos']:
        endpoint = config_data['ibm_cos']['endpoint']
        config_data['ibm_cos']['region'] = endpoint.split('//')[1].split('.')[1]

    if 'storage_bucket' in config_data['ibm_cos']:
        config_data['lithops']['storage_bucket'] = config_data['ibm_cos']['storage_bucket']
