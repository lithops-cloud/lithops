#
# (C) Copyright IBM Corp. 2019
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
import requests
from urllib.parse import urlencode


logger = logging.getLogger(__name__)


class IAM:

    def __init__(self, iam_config, cf_endpoint, cf_namespace):
        self.iam_api_key = iam_config.get('api_key', None)
        self.iam_auth_endpoint = iam_config['ibm_auth_endpoint']
        self.cf_endpoint = cf_endpoint
        self.cf_namespace = cf_namespace
        logger.debug("init method for {} namespace {}".format(*self.cf_endpoint, self.cf_namespace))

    def is_IAM_access(self):
        return self.iam_api_key is not None

    def get_iam_token(self):
        data = urlencode({'grant_type': 'urn:ibm:params:oauth:grant-type:apikey', 'apikey': self.iam_api_key})
        headers = {
            'content-type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }
        res = requests.post(self.iam_auth_endpoint, data=data, headers=headers)

        if res.status_code != 200:
            raise RuntimeError("Error: http code {} while retrieving IAM token for API key.".format(res.status_code))

        bearer_response = res.json()
        bearer_token = 'Bearer ' + bearer_response['access_token']
        logger.debug(bearer_token)

        return bearer_token

    def get_function_namespace_id(self, iam_token):
        logger.debug("Getting name space id for {}".format(self.cf_namespace))
        headers = {
            'content-type': 'application/json',
            'Accept': 'application/json',
            'Authorization': iam_token
        }
        url = os.path.join(self.cf_endpoint, 'api', 'v1', 'namespaces').replace("\\", "/")
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            raise RuntimeError("Error: http code {} while listing namespaces.".format(res.status_code))
        namespaces = res.json()

        for current_namespace in namespaces['namespaces']:
            if 'name' in current_namespace and current_namespace['name'] == self.cf_namespace:
                logger.debug("Found name space id {} for {}".format(current_namespace['id'], self.cf_namespace))
                return current_namespace['id']

        raise RuntimeError("Error: No CF namespace \"{}\" found.".format(self.cf_namespace))
