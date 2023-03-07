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
        self.token_expiry_time = token_expiry_time

    def _is_token_expired(self):
        """
        Checks if a token already expired
        """
        return self._get_token_minutes_left() < 20

    def _get_token_minutes_left(self):
        """
        Gets the remaining minutes in which the current token is valid
        """
        if not self.token_expiry_time:
            return 0
        expiry_time = datetime.fromtimestamp(self.token_expiry_time, tz=timezone.utc)
        return max(0, int((expiry_time - datetime.now(timezone.utc)).total_seconds() / 60.0))

    def get_token(self):
        """
        Gets a new token
        """
        self._generate_new_token()
        minutes_left = self._get_token_minutes_left()
        expiry_time = datetime.fromtimestamp(self.token_expiry_time)
        logger.debug(f"Token expiry time: {expiry_time} - Minutes left: {minutes_left}")
        return self.token, self.token_expiry_time


class COSTokenManager(IBMTokenManager):

    def _generate_new_token(self):
        """
        Generates a new COS token
        """
        token_filename = os.path.join(CACHE_DIR, 'ibm_cos', 'token')

        if not self.token and os.path.exists(token_filename):
            token_cache = load_yaml_config(token_filename)
            self.token = token_cache['token']
            self.token_expiry_time = token_cache['token_expiry_time']

        if self._is_token_expired() and not is_lithops_worker():
            logger.debug("Requesting new COS token")
            token_manager = DefaultTokenManager(api_key_id=self.ibm_api_key)
            self.token = token_manager.get_token()
            self.token_expiry_time = int(token_manager._expiry_time.timestamp())
        else:
            logger.debug("Reusing COS token from local cache")

        token_data = {}
        token_data['token'] = self.token
        token_data['token_expiry_time'] = self.token_expiry_time

        token_filename = os.path.join(CACHE_DIR, 'ibm_cos', 'token')

        if not is_lithops_worker():
            dump_yaml_config(token_filename, token_data)


class IAMTokenManager(IBMTokenManager):

    def _generate_new_token(self):
        """
        Generates a new IAM token
        """
        token_filename = os.path.join(CACHE_DIR, 'ibm_iam', 'token')

        if not self.token and os.path.exists(token_filename):
            token_cache = load_yaml_config(token_filename)
            self.token = token_cache['token']
            self.token_expiry_time = token_cache['token_expiry_time']

        if self._is_token_expired() and not is_lithops_worker():
            logger.debug("Requesting new IAM token")
            auth = IAMAuthenticator(self.ibm_api_key)
            self.token = auth.token_manager.get_token()
            self.token_expiry_time = auth.token_manager.expire_time
        else:
            logger.debug("Reusing IAM token from local cache")

        token_data = {}
        token_data['token'] = self.token
        token_data['token_expiry_time'] = self.token_expiry_time

        if not is_lithops_worker():
            dump_yaml_config(token_filename, token_data)
