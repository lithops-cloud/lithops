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
import os

AVAILABLE_PY_RUNTIMES = {
    '3.6': 'docker.io/lithopscloud/ibmcf-python-v36',
    '3.7': 'docker.io/lithopscloud/ibmcf-python-v37',
    '3.8': 'docker.io/lithopscloud/ibmcf-python-v38',
    '3.9': 'docker.io/lithopscloud/ibmcf-python-v39',
    '3.10': 'docker.io/lithopscloud/ibmcf-python-v310',
    '3.11': 'docker.io/lithopscloud/ibmcf-python-v311'
}

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 600 seconds => 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 1200,
    'worker_processes': 1,
    'invoke_pool_threads': 500,
    'docker_server': 'docker.io'
}

UNIT_PRICE = 0.000017

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_ibmcf.zip')
CF_ENDPOINT = "https://{}.functions.cloud.ibm.com"
REGIONS = ["jp-tok", "au-syd", "eu-gb", "eu-de", "us-south", "us-east"]

REQ_PARAMS = ('iam_api_key',)


def load_config(config_data):

    if 'ibm' not in config_data or config_data['ibm'] is None:
        raise Exception("'ibm' section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['ibm']:
            msg = f'"{param}" is mandatory in the "ibm" section of the configuration'
            raise Exception(msg)

    if not config_data['ibm_cf']:
        config_data['ibm_cf'] = {}

    temp = copy.deepcopy(config_data['ibm_cf'])
    config_data['ibm_cf'].update(config_data['ibm'])
    config_data['ibm_cf'].update(temp)

    if "region" not in config_data['ibm_cf'] and "endpoint" not in config_data['ibm_cf']:
        msg = "'region' or 'endpoint' parameter is mandatory under 'ibm_cf' section of the configuration"
        raise Exception(msg)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['ibm_cf']:
            config_data['ibm_cf'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'runtime' in config_data['ibm_cf']:
        runtime = config_data['ibm_cf']['runtime']
        registry = config_data['ibm_cf']['docker_server']
        if runtime.count('/') == 1 and registry not in runtime:
            config_data['ibm_cf']['runtime'] = f'{registry}/{runtime}'

    if 'endpoint' in config_data['ibm_cf']:
        endpoint = config_data['ibm_cf']['endpoint']
        config_data['ibm_cf']['region'] = endpoint.split('//')[1].split('.')[0]

    elif "region" in config_data['ibm_cf']:
        region = config_data['ibm_cf']['region']
        if region not in REGIONS:
            msg = f"'region' conig parameter under 'ibm_cf' section must be one of {REGIONS}"
            raise Exception(msg)
        config_data['ibm_cf']['endpoint'] = CF_ENDPOINT.format(region)

    if 'region' not in config_data['ibm']:
        config_data['ibm']['region'] = config_data['ibm_cf']['region']
