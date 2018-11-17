#
# Copyright 2018 PyWren Team
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
import json
from pywren_ibm_cloud.wrenutil import is_cf_cluster


DEFAULT_STORAGE_BACKEND = 'ibm_cos'
COS_BUCKET_DEFAULT = "pywren.data"
COS_PREFIX_DEFAULT = "pywren.jobs"
CF_ACTION_NAME_DEFAULT = 'pywren_3.6'
CF_RUNTIME_TIMEOUT = 600  # Default: 10 minutes
DATA_CLEANER_DEFAULT = False
MAX_AGG_DATA_SIZE = 4e6


def load(config_filename):
    import yaml
    res = yaml.safe_load(open(config_filename, 'r'))

    if 'pywren' in res and res['pywren']['storage_bucket'] == '<BUCKET_NAME>':
        raise Exception(
            "{} has bucket name as {} -- make sure you change the default container".format(
                config_filename, res['pywren']['storage_bucket']))

    if res['ibm_cf']['endpoint'] == '<CF_API_ENDPOINT>':
        raise Exception(
            "{} has CF API endpoint as {} -- make sure you change the default CF API endpoint".format(
                config_filename, res['ibm_cf']['endpoint']))
    if res['ibm_cf']['namespace'] == '<CF_NAMESPACE>':
        raise Exception(
            "{} has namespace as {} -- make sure you change the default namespace".format(
                config_filename, res['ibm_cf']['namespace']))
    if res['ibm_cf']['api_key'] == '<CF_API_KEY>':
        raise Exception(
            "{} has CF API key as {} -- make sure you change the default CF API key".format(
                config_filename, res['ibm_cf']['api_key']))

    if 'ibm_cos' in res:
        if 'endpoint' in res['ibm_cos'] and res['ibm_cos']['endpoint'] == '<COS_API_ENDPOINT>':
            raise Exception(
                "{} has CF API endpoint as {} -- make sure you change the default COS API endpoint".format(
                    config_filename, res['ibm_cos']['endpoint']))
        if 'api_key' in res['ibm_cos'] and res['ibm_cos']['api_key'] == '<COS_API_KEY>':
            raise Exception(
                "{} has CF API key as {} -- make sure you change the default COS API key".format(
                    config_filename, res['ibm_cos']['api_key']))

    return res


def get_default_home_filename():
    default_home_filename = os.path.join(os.path.expanduser("~/.pywren_config"))
    return default_home_filename


def get_default_config_filename():
    """
    First checks .pywren_config
    then checks PYWREN_CONFIG_FILE environment variable
    then ~/.pywren_config
    """
    if 'PYWREN_CONFIG_FILE' in os.environ:
        config_filename = os.environ['PYWREN_CONFIG_FILE']
        # FIXME log this

    elif os.path.exists(".pywren_config"):
        config_filename = os.path.abspath('.pywren_config')

    else:
        config_filename = get_default_home_filename()

    return config_filename


def default(config_data=None):
    """
    First checks .pywren_config
    then checks PYWREN_CONFIG_FILE environment variable
    then ~/.pywren_config
    """
    if not config_data:
        if 'PYWREN_CONFIG' in os.environ:
            config_data = json.loads(os.environ.get('PYWREN_CONFIG'))
        else:
            config_filename = get_default_config_filename()
            if config_filename is None:
                raise ValueError("could not find configuration file")

            config_data = load(config_filename)

    # Apply default values
    if 'internal_storage_backend' not in config_data:
        config_data['internal_storage_backend'] = DEFAULT_STORAGE_BACKEND
    if 'function_storage_backend' not in config_data:
        config_data['function_storage_backend'] = DEFAULT_STORAGE_BACKEND
    if 'pywren' not in config_data:
        config_data['pywren'] = dict()
        config_data['pywren']['storage_bucket'] = COS_BUCKET_DEFAULT
        config_data['pywren']['storage_prefix'] = COS_PREFIX_DEFAULT
        config_data['pywren']['data_cleaner'] = DATA_CLEANER_DEFAULT
    else:
        if 'storage_bucket' not in config_data['pywren']:
            config_data['pywren']['storage_bucket'] = COS_BUCKET_DEFAULT
        if 'storage_prefix' not in config_data['pywren']:
            config_data['pywren']['storage_prefix'] = COS_PREFIX_DEFAULT
        if 'data_cleaner' not in config_data['pywren']:
            config_data['pywren']['data_cleaner'] = DATA_CLEANER_DEFAULT

    if 'action_name' not in config_data['ibm_cf']:
        config_data['ibm_cf']['action_name'] = CF_ACTION_NAME_DEFAULT

    # True or False depending on whether this code is executed within CF cluster or not
    config_data['ibm_cf']['is_cf_cluster'] = is_cf_cluster()

    return config_data


def extract_storage_config(config):
    storage_config = dict()

    storage_config['function_storage_backend'] = config['function_storage_backend']
    storage_config['internal_storage_backend'] = config['internal_storage_backend']
    storage_config['storage_prefix'] = config['pywren']['storage_prefix']
    storage_config['storage_bucket'] = config['pywren']['storage_bucket']

    if storage_config['function_storage_backend'] == 'ibm_cos' or \
       storage_config['internal_storage_backend'] == 'ibm_cos':
        
        required_parameters_1 = ('endpoint', 'api_key')
        required_parameters_2 = ('endpoint', 'secret_key', 'access_key')
        
        if set(required_parameters_1) <= set(config['ibm_cos']) or \
           set(required_parameters_2) <= set(config['ibm_cos']):
            storage_config['ibm_cos'] = config['ibm_cos']
        else:
            raise Exception('You must provide {} or {} to access to IBM COS'.format(required_parameters_1,
                                                                                    required_parameters_2))

    if storage_config['function_storage_backend'] == 'swift' or \
       storage_config['internal_storage_backend'] == 'swift':
        
        required_parameters = ('auth_url', 'user_id', 'project_id', 'password', 'region')
        
        if set(required_parameters) in set(config['swift']):
            storage_config['swift'] = config['swift']
        else:
            raise Exception('You must provide {} to access to Swift'.format(required_parameters))
    
    return storage_config
