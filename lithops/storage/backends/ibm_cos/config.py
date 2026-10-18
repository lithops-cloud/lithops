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

# Compute backends that reach IBM COS through a private endpoint: the word
# that endpoint must hold, its default for a region, and what the error says
# when the endpoint given does not hold the word
PRIVATE_ENDPOINTS = {
    'ibm_cf': ('private', PRIVATE_ENDPOINT, ''),
    'code_engine': ('direct', DIRECT_ENDPOINT, ''),
    'ibm_vpc': ('direct', DIRECT_ENDPOINT, '. You must use the "direct" endpoint'),
}


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

        if compute_backend in PRIVATE_ENDPOINTS:
            _, private_endpoint, _ = PRIVATE_ENDPOINTS[compute_backend]
            config_data['ibm_cos']['private_endpoint'] = private_endpoint.format(region)

    if compute_backend in PRIVATE_ENDPOINTS:
        endpoint_kind, _, invalid_hint = PRIVATE_ENDPOINTS[compute_backend]
        if 'private_endpoint' not in config_data['ibm_cos']:
            raise Exception('You must provide the private_endpoint to access to IBM COS')
        elif endpoint_kind not in config_data['ibm_cos']['private_endpoint']:
            raise Exception('The private_endpoint you provided to access to IBM COS is not valid' + invalid_hint)
        if not config_data['ibm_cos']['private_endpoint'].startswith('http'):
            raise Exception('IBM COS Private Endpoint must start with http:// or https://')

    elif 'private_endpoint' in config_data['ibm_cos']:
        del config_data['ibm_cos']['private_endpoint']

    if not config_data['ibm_cos']['endpoint'].startswith('http'):
        raise Exception('IBM COS Endpoint must start with http:// or https://')

    if 'region' not in config_data['ibm_cos']:
        endpoint = config_data['ibm_cos']['endpoint']
        config_data['ibm_cos']['region'] = endpoint.split('//')[1].split('.')[1]

    if ('service_instance_id' not in config_data['ibm_cos']
            and {'access_key_id', 'secret_access_key'}.isdisjoint(config_data['ibm_cos'])):
        raise Exception('You must provide the service_instance_id or the (access_key_id,secret_access_key) to '
                        'access to IBM COS')
