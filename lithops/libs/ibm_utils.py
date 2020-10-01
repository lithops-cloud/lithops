import os
import logging
from datetime import datetime, timezone
from ibm_botocore.credentials import DefaultTokenManager

from lithops.utils import is_lithops_worker
from lithops.config import CACHE_DIR, load_yaml_config, dump_yaml_config

logger = logging.getLogger(__name__)


class IBMIAMAPIKeyManager:
    def __init__(self, component_name, iam_api_key, token=None, token_expiry_time=None):
        self.component_name = component_name
        self.iam_api_key = iam_api_key

        self._token_manager = DefaultTokenManager(api_key_id=self.iam_api_key)
        self._token_filename = os.path.join(CACHE_DIR, self.component_name, 'iam_token')

        if token:
            logger.debug("Using IBM IAM API Key - Reusing Token from config")
            self._token_manager._token = token
            self._token_manager._expiry_time = datetime.strptime(token_expiry_time, '%Y-%m-%d %H:%M:%S.%f%z')
            logger.debug("Token expiry time: {} - Minutes left: {}".format(self._token_manager._expiry_time, self._get_token_minutes_diff()))
        elif os.path.exists(self._token_filename):
            logger.debug("Using IBM IAM API Key - Reusing Token from local cache")
            token_data = load_yaml_config(self._token_filename)
            self._token_manager._token = token_data['token']
            self._token_manager._expiry_time = datetime.strptime(token_data['token_expiry_time'], '%Y-%m-%d %H:%M:%S.%f%z')
            logger.debug("Token expiry time: {} - Minutes left: {}".format(self._token_manager._expiry_time, self._get_token_minutes_diff()))

    def _get_token_minutes_diff(self):
        return int((self._token_manager._expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0)

    def _generate_new_token(self):
        self._token_manager._token = None
        self._token_manager.get_token()
        token_data = {}
        token_data['token'] = self._token_manager._token
        token_data['token_expiry_time'] = self._token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')
        dump_yaml_config(self._token_filename, token_data)

    def get_token(self):
        if (self._token_manager._is_expired() or self._get_token_minutes_diff() < 11) and not is_lithops_worker():
            logger.debug("Using IBM IAM API Key - Token expired. Requesting new token")
            self._generate_new_token()

        token = self._token_manager._token
        token_expiry_time = self._token_manager._expiry_time.strftime('%Y-%m-%d %H:%M:%S.%f%z')

        return token, token_expiry_time
