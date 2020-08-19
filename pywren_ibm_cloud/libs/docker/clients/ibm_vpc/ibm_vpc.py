import os
import logging
import requests
from datetime import datetime, timezone
from ibm_botocore.credentials import DefaultTokenManager

from pywren_ibm_cloud.utils import is_pywren_function
from pywren_ibm_cloud.config import CACHE_DIR, load_yaml_config, dump_yaml_config

logger = logging.getLogger(__name__)


class IBMVPCInstanceClient:

    def __init__(self, ibm_vpc_config, insecure=False, user_agent=None):
        self.config = ibm_vpc_config

        self.session = requests.session()
        if insecure:
            self.session.verify = False

        self._token_manager = DefaultTokenManager(api_key_id=self.config['iam_api_key'])
        self._token_filename = os.path.join(CACHE_DIR, 'docker', 'iam_token')

        if 'token' in self.config:
            logger.debug("Using IBM IAM API Key - Reusing Token from config")
            self._token_manager._token = self.config['token']
            self._token_manager._expiry_time = datetime.strptime(self.config['token_expiry_time'], '%Y-%m-%d %H:%M:%S.%f%z')
            token_minutes_diff = int((self._token_manager._expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0)
            logger.debug("Token expiry time: {} - Minutes left: {}".format(self._token_manager._expiry_time, token_minutes_diff))

        elif os.path.exists(self._token_filename):
            logger.debug("Using IBM IAM API Key - Reusing Token from local cache")
            token_data = load_yaml_config(self._token_filename)
            self._token_manager._token = token_data['token']
            self._token_manager._expiry_time = datetime.strptime(token_data['token_expiry_time'], '%Y-%m-%d %H:%M:%S.%f%z')
            token_minutes_diff = int((self._token_manager._expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0)
            logger.debug("Token expiry time: {} - Minutes left: {}".format(self._token_manager._expiry_time, token_minutes_diff))

        if self._iam_token_expired(): self._generate_new_iam_token()
        self.config['token'] = self._token_manager._token
        self.config['token_expiry_time'] = self._token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')

        auth_token = self._token_manager._token
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

    def _iam_token_expired(self):
        token_minutes_diff = int((self._token_manager._expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0)
        return (self._token_manager._is_expired() or token_minutes_diff < 11) and not is_pywren_function()

    def _generate_new_iam_token(self):
        logger.debug("Using IBM IAM API Key - Token expired. Requesting new token")
        self._token_manager._token = None
        self._token_manager.get_token()
        token_data = {}
        token_data['token'] = self._token_manager._token
        token_data['token_expiry_time'] = self._token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')
        dump_yaml_config(self._token_filename, token_data)

    def get_instance(self):
        if self._iam_token_expired(): self._generate_new_iam_token()

        url = '/'.join([self.config['endpoint'], 'v1', 'instances', self.config['instance_id']
                        + f'?version={self.config["version"]}&generation={self.config["generation"]}'])
        res = self.session.get(url)
        return res.json()

    def create_instance_action(self, type):
        if self._iam_token_expired(): self._generate_new_iam_token()

        if type == 'start':
            expected_status = 'starting'
        elif type == 'stop':
            expected_status = 'stopping'
        elif type == 'reboot':
            expected_status = 'restarting'
        else:
            msg = 'An error occurred cant create instance action \"{}\"'.format(type)
            raise Exception(msg)

        url = '/'.join([self.config['endpoint'], 'v1', 'instances', self.config['instance_id'],
                        f'actions?version={self.config["version"]}&generation={self.config["generation"]}'])
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
