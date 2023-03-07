#
# (C) Copyright IBM Corp. 2023
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
import logging
from datetime import datetime, timezone
from ibm_botocore.credentials import DefaultTokenManager

from lithops.utils import is_lithops_worker
from lithops.config import load_yaml_config, dump_yaml_config
from lithops.constants import CACHE_DIR
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

logger = logging.getLogger(__name__)


class IBMTokenManager:

    def __init__(self, ibm_api_key, token=None, token_expiry_time=None):
        self.ibm_api_key = ibm_api_key
        self.token = token
        self.expiry_time = token_expiry_time
        self.is_lithops_worker = is_lithops_worker()

        self._init()

    def _init(self):
        pass

    def _is_token_expired(self):
        """
        Checks if a token already expired
        """
        return self._get_token_minutes_left() < 20

    def _get_token_minutes_left(self):
        """
        Gets the remaining minutes in which the current token is valid
        """
        if not self.expiry_time:
            return 0
        expiry_time = datetime.fromtimestamp(self.expiry_time, tz=timezone.utc)
        return max(0, int((expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0))

    def _generate_new_token(self):
        pass

    def _refresh_token(self):
        pass

    def get_token(self):
        """
        Gets the current token
        """
        minutes_left = self._get_token_minutes_left()
        expiry_time = datetime.fromtimestamp(self.expiry_time)
        logger.debug(f"Token expiry time: {expiry_time} - Minutes left: {minutes_left}")
        return self.token, self.expiry_time

    def refresh_token(self):
        """
        Refresh the IAM token
        """
        if self._is_token_expired() and not self.is_lithops_worker:
            self._refresh_token()
            minutes_left = self._get_token_minutes_left()
            expiry_time = datetime.fromtimestamp(self.expiry_time)
            logger.debug(f"Token expiry time: {expiry_time} - Minutes left: {minutes_left}")

        return self.token, self.expiry_time


class COSTokenManager(IBMTokenManager):

    TOEKN_FILE = os.path.join(CACHE_DIR, 'ibm_cos', 'token')

    def _generate_new_token(self):
        """
        generates a new token
        """
        logger.debug("Requesting new COS token")
        token_manager = DefaultTokenManager(api_key_id=self.ibm_api_key)
        self.token = token_manager.get_token()
        self.expiry_time = int(token_manager._expiry_time.timestamp())

    def _init(self):
        """
        Inits the COS token
        """
        if not self.token and os.path.exists(self.TOEKN_FILE):
            token_cache = load_yaml_config(self.TOEKN_FILE)
            self.token = token_cache.get('token')
            self.expiry_time = token_cache.get('expiry_time')

        if self._is_token_expired() and not self.is_lithops_worker:
            self._generate_new_token()
            token_data = {'token': self.token, 'expiry_time': self.expiry_time}
            dump_yaml_config(self.TOEKN_FILE, token_data)
        else:
            logger.debug("Reusing COS token from local cache")

    def _refresh_token(self):
        """
        Force refresh the current COS token
        """
        self._generate_new_token()
        token_data = {'token': self.token, 'expiry_time': self.expiry_time}
        dump_yaml_config(self.TOEKN_FILE, token_data)

        return self.token, self.expiry_time


class IAMTokenManager(IBMTokenManager):

    TOEKN_FILE = os.path.join(CACHE_DIR, 'ibm_iam', 'token')

    def _generate_new_token(self):
        """
        Generates a new IAM token
        """
        logger.debug("Requesting new IAM token")
        auth = IAMAuthenticator(self.ibm_api_key)
        self.token = auth.token_manager.get_token()
        self.expiry_time = auth.token_manager.expire_time

    def _init(self):
        if not self.token and os.path.exists(self.TOEKN_FILE):
            token_cache = load_yaml_config(self.TOEKN_FILE)
            self.token = token_cache.get('token')
            self.expiry_time = token_cache.get('expiry_time')

        if self._is_token_expired() and not self.is_lithops_worker:
            self._generate_new_token()
            token_data = {'token': self.token, 'expiry_time': self.expiry_time}
            dump_yaml_config(self.TOEKN_FILE, token_data)
        else:
            logger.debug("Reusing IAM token from local cache")

    def _refresh_token(self):
        """
        Force refresh the current IAM token
        """
        self._generate_new_token()
        token_data = {'token': self.token, 'expiry_time': self.expiry_time}
        dump_yaml_config(self.TOEKN_FILE, token_data)

        return self.token, self.expiry_time
