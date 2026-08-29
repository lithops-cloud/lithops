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
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from ibm_botocore.credentials import DefaultTokenManager
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

from lithops.config import load_yaml_config, dump_yaml_config
from lithops.constants import CACHE_DIR

logger = logging.getLogger(__name__)

# The token will be considered expired 20 minutes before its expiration time
EXPIRY_MINUTES = 20

# How long an IBM Cloud token lasts, used only when the library does not tell
# us the real expiry time
DEFAULT_TOKEN_LIFETIME = 60 * 60


class IBMTokenManager:
    """
    Keeps an IBM Cloud token valid, caching it in a local file so that it can
    be reused across executions. Subclasses provide the token generation
    """

    TOKEN_FILE: Optional[str] = None
    TYPE: Optional[str] = None

    def __init__(
        self,
        ibm_api_key: str,
        token: Optional[str] = None,
        token_expiry_time: Optional[int] = None,
    ):
        self.ibm_api_key = ibm_api_key
        self.token = token
        self.expiry_time = token_expiry_time
        token_source = 'the configuration'

        if not self.token and self.TOKEN_FILE and os.path.exists(self.TOKEN_FILE):
            token_data = load_yaml_config(self.TOKEN_FILE)
            self.token = token_data.get('token')
            self.expiry_time = token_data.get('expiry_time')
            token_source = 'local cache'

        if not self._is_token_expired():
            logger.debug(f"Reusing {self.TYPE} token from {token_source}")
            self._log_remaining_time()

    def _is_token_expired(self) -> bool:
        """
        Checks whether the token is missing, expired, or about to expire
        """
        return self._get_token_minutes_left() < EXPIRY_MINUTES

    def _get_token_minutes_left(self) -> int:
        """Gets the minutes the current token is still valid for"""
        if not self.expiry_time:
            return 0
        expiry_time = datetime.fromtimestamp(self.expiry_time, tz=timezone.utc)
        remaining = (expiry_time - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining / 60.0))

    def _generate_new_token(self) -> None:
        """Requests a new token and stores it with its expiry time"""
        raise NotImplementedError()

    def _log_remaining_time(self) -> None:
        expiry_time = datetime.fromtimestamp(self.expiry_time, tz=timezone.utc)
        logger.debug(
            f"{self.TYPE} token expiry time: {expiry_time} - "
            f"Minutes left: {self._get_token_minutes_left()}"
        )

    def _dump_token_data(self) -> None:
        if not self.TOKEN_FILE:
            return
        token_data = {'token': self.token, 'expiry_time': self.expiry_time}
        dump_yaml_config(self.TOKEN_FILE, token_data)

    def refresh_token(self) -> Tuple[Optional[str], Optional[int]]:
        """Generates a new token, caches it, and returns it"""
        self._generate_new_token()
        self._dump_token_data()
        self._log_remaining_time()
        return self.token, self.expiry_time

    def get_token(self) -> Tuple[Optional[str], Optional[int]]:
        """Gets the current token, refreshing it first if it is expired"""
        if self._is_token_expired():
            self.refresh_token()
        return self.token, self.expiry_time


class COSTokenManager(IBMTokenManager):
    """Token manager for IBM Cloud Object Storage"""

    TOKEN_FILE = os.path.join(CACHE_DIR, 'ibm_cos', 'token')
    TYPE = 'COS'

    def _generate_new_token(self) -> None:
        logger.debug("Requesting new COS token")
        token_manager = DefaultTokenManager(api_key_id=self.ibm_api_key)
        self.token = token_manager.get_token()
        # ibm_botocore exposes the expiry time only as a private attribute, so
        # a library upgrade can take it away
        expiry_time = getattr(token_manager, '_expiry_time', None)
        if expiry_time is None:
            logger.warning(
                "ibm_botocore no longer reports the token expiry time, "
                f"assuming the standard {DEFAULT_TOKEN_LIFETIME // 60} "
                "minute lifetime"
            )
            self.expiry_time = int(time.time()) + DEFAULT_TOKEN_LIFETIME
        else:
            self.expiry_time = int(expiry_time.timestamp())


class IAMTokenManager(IBMTokenManager):
    """Token manager for IBM Cloud IAM"""

    TOKEN_FILE = os.path.join(CACHE_DIR, 'ibm_iam', 'token')
    TYPE = 'IAM'

    def _generate_new_token(self) -> None:
        logger.debug("Requesting new IAM token")
        auth = IAMAuthenticator(self.ibm_api_key)
        self.token = auth.token_manager.get_token()
        self.expiry_time = auth.token_manager.expire_time
