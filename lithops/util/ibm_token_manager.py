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

from lithops.config import load_yaml_config, dump_yaml_config
from lithops.constants import CACHE_DIR
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

logger = logging.getLogger(__name__)


# The token will be considered expired 20 minutes before its actual expiration time
EXPIRY_MINUTES = 20


class IBMTokenManager:

    TOEKN_FILE = None
    TYPE = None

    def __init__(self, ibm_api_key, token=None, token_expiry_time=None):
        self.ibm_api_key = ibm_api_key
        self.token = token
        self.expiry_time = token_expiry_time

        if not self.token and os.path.exists(self.TOEKN_FILE):
            token_data = load_yaml_config(self.TOEKN_FILE)
            self.token = token_data.get('token')
            self.expiry_time = token_data.get('expiry_time')

        if not self._is_token_expired():
            logger.debug(f"Reusing {self.TYPE} token from local cache")
            self._log_remaining_time()

    def _is_token_expired(self):
        """
        Checks if a token already expired
        """
        return self._get_token_minutes_left() < EXPIRY_MINUTES

    def _get_token_minutes_left(self):
        """
        Gets the remaining minutes in which the current token is valid
        """
        if not self.expiry_time:
            return 0
        expiry_time = datetime.fromtimestamp(self.expiry_time, tz=timezone.utc)
        return max(0, int((expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0))

    def _generate_new_token(self):
        """
        Generates a new token
        """
        raise NotImplementedError()

    def _log_remaining_time(self):
        """
        Logs the remaining time of the token
        """
        minutes_left = self._get_token_minutes_left()
        expiry_time = datetime.fromtimestamp(self.expiry_time)
        logger.debug(f"{self.TYPE} token expiry time: {expiry_time} - Minutes left: {minutes_left}")

    def _dump_token_data(self):
        """
        Dumps the token into a local cache file
        """
        token_data = {'token': self.token, 'expiry_time': self.expiry_time}
        dump_yaml_config(self.TOEKN_FILE, token_data)

    def refresh_token(self):
        """
        Forces to create a new token
        """
        self._generate_new_token()
        self._dump_token_data()
        self._log_remaining_time()

        return self.token, self.expiry_time

    def get_token(self):
        """
        Gets the current token or creates a new one if expired
        """
        if self._is_token_expired():
            self.refresh_token()

        return self.token, self.expiry_time


class COSTokenManager(IBMTokenManager):

    TOEKN_FILE = os.path.join(CACHE_DIR, 'ibm_cos', 'token')
    TYPE = 'COS'

    def _generate_new_token(self):
        """
        Generates a new COS token
        """
        logger.debug("Requesting new COS token")
        token_manager = DefaultTokenManager(api_key_id=self.ibm_api_key)
        self.token = token_manager.get_token()
        self.expiry_time = int(token_manager._expiry_time.timestamp())


class IAMTokenManager(IBMTokenManager):

    TOEKN_FILE = os.path.join(CACHE_DIR, 'ibm_iam', 'token')
    TYPE = 'IAM'

    def _generate_new_token(self):
        """
        Generates a new IAM token
        """
        logger.debug("Requesting new IAM token")
        auth = IAMAuthenticator(self.ibm_api_key)
        self.token = auth.token_manager.get_token()
        self.expiry_time = auth.token_manager.expire_time
