import os
import logging
import requests
from datetime import datetime, timezone
from ibm_botocore.credentials import DefaultTokenManager

from pywren_ibm_cloud.utils import is_pywren_function
from pywren_ibm_cloud.config import CACHE_DIR, load_yaml_config, dump_yaml_config

logger = logging.getLogger(__name__)


class IBMVPCInstanceClient:

    def __init__(self, gen2_config, insecure=False, user_agent=None):
        self.gen2_config = gen2_config
        self.gen2_config['version'] = '2020-08-17'
        self.gen2_config['generation'] = 2

        self.session = requests.session()

        if insecure:
            self.session.verify = False

        token_manager = DefaultTokenManager(api_key_id=self.gen2_config['iam_api_key'])
        token_filename = os.path.join(CACHE_DIR, 'docker', 'iam_token')

        if 'token' in self.gen2_config:
            logger.debug("Using IBM IAM API Key - Reusing Token from config")
            token_manager._token = self.gen2_config['token']
            token_manager._expiry_time = datetime.strptime(self.gen2_config['token_expiry_time'],
                                                           '%Y-%m-%d %H:%M:%S.%f%z')
            token_minutes_diff = int((token_manager._expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0)
            logger.debug(
                "Token expiry time: {} - Minutes left: {}".format(token_manager._expiry_time, token_minutes_diff))

        elif os.path.exists(token_filename):
            logger.debug("Using IBM IAM API Key - Reusing Token from local cache")
            token_data = load_yaml_config(token_filename)
            token_manager._token = token_data['token']
            token_manager._expiry_time = datetime.strptime(token_data['token_expiry_time'],
                                                           '%Y-%m-%d %H:%M:%S.%f%z')
            token_minutes_diff = int((token_manager._expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0)
            logger.debug(
                "Token expiry time: {} - Minutes left: {}".format(token_manager._expiry_time, token_minutes_diff))

        if (token_manager._is_expired() or token_minutes_diff < 11) and not is_pywren_function():
            logger.debug("Using IBM IAM API Key - Token expired. Requesting new token")
            token_manager._token = None
            token_manager.get_token()
            token_data = {}
            token_data['token'] = token_manager._token
            token_data['token_expiry_time'] = token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')
            dump_yaml_config(token_filename, token_data)

        gen2_config['token'] = token_manager._token
        gen2_config['token_expiry_time'] = token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')

        auth_token = token_manager._token
        auth = 'Bearer ' + auth_token

        self.headers = {
            'content-type': 'application/json',
            'Authorization': auth,
        }

        if user_agent:
            default_user_agent = self.session.headers['User-Agent']
            self.headers['User-Agent'] = default_user_agent + ' {}'.format(user_agent)

        self.session.headers.update(self.headers)
        adapter = requests.adapters.HTTPAdapter()
        self.session.mount('https://', adapter)

    def get_instance(self):
        url = '/'.join([self.gen2_config['endpoint'], 'v1', 'instances', self.gen2_config['gen2_config']
                        + f'?version={self.gen2_config["version"]}&generation={self.gen2_config["generation"]}'])
        res = self.session.get(url)
        return res.json()

    def create_instance_action(self, type):
        if type == 'start':
            expected_status = 'starting'
        elif type == 'stop':
            expected_status = 'stopping'
        elif type == 'reboot':
            expected_status = 'restarting'
        else:
            msg = 'An error occurred cant create instance action \"{}\"'.format(type)
            raise Exception(msg)

        url = '/'.join([self.gen2_config['endpoint'], 'v1', 'instances', self.gen2_config['instance_id'],
                        f'actions?version={self.gen2_config["version"]}&generation={self.gen2_config["generation"]}'])
        data = {'type': type, 'force': True}
        res = self.session.put(url, json=data)
        resp_text = res.json()

        if res.status_code != 200:
            msg = 'An error occurred creating instance action {}: {}'.format(type, resp_text['error'])
            raise Exception(msg)

        instance = self.get_instance()
        if instance['status'] != expected_status:
            msg = 'An error occurred instance status \"{}\" does not match with expected status \"{}\"'.format(
                instance['status'], expected_status)
            raise Exception(msg)

        logger.debug("Created instance action {} successfully".format(type))
