import os
import logging
from datetime import datetime
from ibm_botocore.credentials import DefaultTokenManager
from pywren_ibm_cloud.utils import is_remote_cluster
from pywren_ibm_cloud.config import CONFIG_DIR, load_yaml_config, dump_yaml_config

logger = logging.getLogger(__name__)


def load_config(config_data=None):
    if 'ibm_cos' not in config_data:
        raise Exception("ibm_cos section is mandatory in the configuration")

    required_keys_1 = ('endpoint', 'api_key')
    required_keys_2 = ('endpoint', 'secret_key', 'access_key')
    required_keys_3 = ('endpoint', 'ibm:iam_api_key')

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data['ibm_cos'].update(config_data['ibm'])

    if not set(required_keys_1) <= set(config_data['ibm_cos']) and \
       not set(required_keys_2) <= set(config_data['ibm_cos']) and \
       ('endpoint' not in config_data['ibm_cos'] or 'iam_api_key' not in config_data['ibm_cos']
       or config_data['ibm_cos']['iam_api_key'] is None):
        raise Exception('You must provide {}, {} or {} to access to IBM COS'
                        .format(required_keys_1, required_keys_2, required_keys_3))

    if not set(required_keys_2) <= set(config_data['ibm_cos']):
        if 'api_key' in config_data['ibm_cos']:
            api_key = config_data['ibm_cos'].get('api_key')
            api_key_type = 'COS'

        elif 'iam_api_key' in config_data['ibm_cos']:
            api_key = config_data['ibm_cos'].get('iam_api_key')
            api_key_type = 'IAM'

        token_manager = DefaultTokenManager(api_key_id=api_key)
        token_filename = os.path.join(CONFIG_DIR, api_key_type+'_TOKEN')

        if 'token' not in config_data['ibm_cos']:
            if os.path.exists(token_filename):
                logger.debug("Using IBM {} API Key - Reusing token from local cache".format(api_key_type))
                token_data = load_yaml_config(token_filename)
                token_manager._token = token_data['token']
                token_manager._expiry_time = datetime.strptime(token_data['token_expiry_time'],
                                                               '%Y-%m-%d %H:%M:%S.%f%z')
        else:
            logger.debug("Using IBM {} API Key - Reusing token from config".format(api_key_type))
            token_manager._token = config_data['ibm_cos']['token']
            token_manager._expiry_time = datetime.strptime(config_data['ibm_cos']['token_expiry_time'],
                                                           '%Y-%m-%d %H:%M:%S.%f%z')

        if token_manager._is_expired() and not is_remote_cluster():
            logger.debug("Using IBM {} API Key - Requesting new token".format(api_key_type))
            token_manager.get_token()
            token_data = {}
            token_data['token'] = token_manager._token
            token_data['token_expiry_time'] = token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')
            dump_yaml_config(token_filename, token_data)

        config_data['ibm_cos']['token'] = token_manager._token
        config_data['ibm_cos']['token_expiry_time'] = token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')
