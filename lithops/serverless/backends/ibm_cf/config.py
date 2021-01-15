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

import os
import sys
from lithops.utils import version_str

RUNTIME_DEFAULT = {'3.5': 'lithopscloud/ibmcf-python-v35',
                   '3.6': 'lithopscloud/ibmcf-python-v36',
                   '3.7': 'lithopscloud/ibmcf-python-v37',
                   '3.8': 'lithopscloud/ibmcf-python-v38'}

RUNTIME_TIMEOUT_DEFAULT = 600  # Default: 600 seconds => 10 minutes
RUNTIME_MEMORY_DEFAULT = 256  # Default memory: 256 MB
MAX_CONCURRENT_WORKERS = 1200


FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_ibmcf.zip')


def load_config(config_data):
    if 'runtime_memory' not in config_data['serverless']:
        config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['serverless']:
        config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['serverless']:
        python_version = version_str(sys.version_info)
        try:
            config_data['serverless']['runtime'] = RUNTIME_DEFAULT[python_version]
        except KeyError:
            raise Exception('Unsupported Python version: {}'.format(python_version))

    if 'workers' not in config_data['lithops'] or \
       config_data['lithops']['workers'] > MAX_CONCURRENT_WORKERS:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS

    if 'ibm_cf' not in config_data:
        raise Exception("ibm_cf section is mandatory in the configuration")

    required_parameters_0 = ('endpoint', 'namespace')
    required_parameters_1 = ('endpoint', 'namespace', 'api_key')
    required_parameters_2 = ('endpoint', 'namespace', 'namespace_id', 'ibm:iam_api_key')

    # Check old format. Convert to new format
    if set(required_parameters_0) <= set(config_data['ibm_cf']):
        endpoint = config_data['ibm_cf'].pop('endpoint')

        if not endpoint.startswith('https'):
            raise Exception('IBM CF Endpoint must start with https://')

        namespace = config_data['ibm_cf'].pop('namespace')
        api_key = config_data['ibm_cf'].pop('api_key', None)
        namespace_id = config_data['ibm_cf'].pop('namespace_id', None)
        region = endpoint.split('//')[1].split('.')[0]

        for k in list(config_data['ibm_cf']):
            # Delete unnecessary keys
            del config_data['ibm_cf'][k]

        config_data['ibm_cf']['regions'] = {}
        config_data['serverless']['region'] = region
        config_data['ibm_cf']['regions'][region] = {'endpoint': endpoint, 'namespace': namespace}
        if api_key:
            config_data['ibm_cf']['regions'][region]['api_key'] = api_key
        if namespace_id:
            config_data['ibm_cf']['regions'][region]['namespace_id'] = namespace_id
    # -------------------

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data['ibm_cf'].update(config_data['ibm'])

    for region in config_data['ibm_cf']['regions']:
        if not set(required_parameters_1) <= set(config_data['ibm_cf']['regions'][region]) \
           and (not set(required_parameters_0) <= set(config_data['ibm_cf']['regions'][region])
           or 'namespace_id' not in config_data['ibm_cf']['regions'][region] or 'iam_api_key' not in config_data['ibm_cf']):
            raise Exception('You must provide {} or {} to access to IBM Cloud '
                            'Functions'.format(required_parameters_1, required_parameters_2))

    cbr = config_data['serverless'].get('region')
    if type(cbr) == list:
        for region in cbr:
            if region not in config_data['ibm_cf']['regions']:
                raise Exception('Invalid Compute backend region: {}'.format(region))
    else:
        if cbr is None:
            cbr = list(config_data['ibm_cf']['regions'].keys())[0]
            config_data['lithops']['compute_backend_region'] = cbr

        if cbr not in config_data['ibm_cf']['regions']:
            raise Exception('Invalid Compute backend region: {}'.format(cbr))
