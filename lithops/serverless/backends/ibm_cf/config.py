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
import shutil
from lithops.utils import version_str

DOCKER_PATH = shutil.which('docker')

RUNTIME_DEFAULT = {
    '3.5': 'lithopscloud/ibmcf-python-v35',
    '3.6': 'lithopscloud/ibmcf-python-v36',
    '3.7': 'lithopscloud/ibmcf-python-v37',
    '3.8': 'lithopscloud/ibmcf-python-v38',
    '3.9': 'lithopscloud/ibmcf-python-v39',
    '3.10': 'lithopscloud/ibmcf-python-v310'
}

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 600 seconds => 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 1200,
    'worker_processes': 1,
    'invoke_pool_threads': 500,
}

UNIT_PRICE = 0.000017

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_ibmcf.zip')

REQ_PARAMS = ['endpoint', 'namespace']
OPT_PARAMS_1 = ['api_key']
OPT_PARAMS_2 = ['namespace_id', 'iam_api_key']


def load_config(config_data):
    for param in REQ_PARAMS:
        if param not in config_data['ibm_cf']:
            msg = "{} is mandatory in 'ibm_cf' section of the configuration".format(REQ_PARAMS)
            raise Exception(msg)

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data['ibm_cf'].update(config_data['ibm'])

    if not all(elem in config_data['ibm_cf'] for elem in OPT_PARAMS_1) and \
       not all(elem in config_data['ibm_cf'] for elem in OPT_PARAMS_2):
        raise Exception('You must provide either {}, or {} in {} section of the configuration'
                        .format(OPT_PARAMS_1, OPT_PARAMS_2, 'ibm_cf'))

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['ibm_cf']:
            config_data['ibm_cf'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'runtime' not in config_data['ibm_cf']:
        python_version = version_str(sys.version_info)
        try:
            config_data['ibm_cf']['runtime'] = RUNTIME_DEFAULT[python_version]
        except KeyError:
            raise Exception('Unsupported Python version: {}'.format(python_version))
