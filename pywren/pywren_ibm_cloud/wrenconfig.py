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

    if res['ibm_cos']['endpoint'] == '<COS_API_ENDPOINT>':
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
    if 'storage_backend' not in config_data:
        config_data['storage_backend'] = DEFAULT_STORAGE_BACKEND
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
    storage_config['storage_backend'] = config['storage_backend']
    storage_config['storage_prefix'] = config['pywren']['storage_prefix']
    storage_config['storage_bucket'] = config['pywren']['storage_bucket']

    if storage_config['storage_backend'] == 'ibm_cos':
        storage_config['backend_config'] = {}

        if 'endpoint' in config['ibm_cos']:
            storage_config['backend_config']['cos_endpoint'] = config['ibm_cos']['endpoint']
        elif {'endpoints', 'region'} <= set(config['ibm_cos']):
            storage_config['backend_config']['cos_endpoints'] = config['ibm_cos']['endpoints']
            storage_config['backend_config']['cos_region'] = config['ibm_cos']['region']

        if {'api_key'} <= set(config['ibm_cos']):
            storage_config['backend_config']['cos_api_key'] = config['ibm_cos']['api_key']
        elif {'access_key', 'secret_key'} <= set(config['ibm_cos']):
            storage_config['backend_config']['cos_access_key'] = config['ibm_cos']['access_key']
            storage_config['backend_config']['cos_secret_key'] = config['ibm_cos']['secret_key']
        else:
            raise Exception('You must provide credentials to access to COS')

    if storage_config['storage_backend'] == 'swift':
        storage_config['backend_config'] = {}
        storage_config['backend_config']['swift_auth_url'] = config['swift']['auth_url']
        storage_config['backend_config']['swift_user_id'] = config['swift']['user_id']
        storage_config['backend_config']['swift_project_id'] = config['swift']['project_id']
        storage_config['backend_config']['swift_password'] = config['swift']['password']
        storage_config['backend_config']['swift_region'] = config['swift']['region']
    return storage_config
