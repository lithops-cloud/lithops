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

import logging
import requests
from urllib.parse import urlencode

IBM_IAM_AUTH_ENDPOINT = 'https://iam.cloud.ibm.com/oidc/token'
logger = logging.getLogger(__name__)


class IBMIAMClient:

    def __init__(self, iam_api_key, cf_endpoint, cf_namespace):
        self.iam_api_key = iam_api_key
        self.cf_endpoint = cf_endpoint
        self.cf_namespace = cf_namespace

    def get_iam_token(self):
        data = urlencode({'grant_type': 'urn:ibm:params:oauth:grant-type:apikey', 'apikey': self.iam_api_key})
        headers = {
            'content-type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }
        res = requests.post(IBM_IAM_AUTH_ENDPOINT, data=data, headers=headers)

        if res.status_code != 200:
            raise RuntimeError("Error: http code {} while retrieving IAM token for API key.".format(res.status_code))

        bearer_response = res.json()
        logger.debug(bearer_response)
        bearer_token = bearer_response['access_token']
        logger.debug(bearer_token)

        return bearer_token

    def get_function_namespace_id(self, iam_token):
        logger.debug("Getting name space id for {}".format(self.cf_namespace))
        headers = {
            'content-type': 'application/json',
            'Accept': 'application/json',
            'Authorization': iam_token
        }
        url = '/'.join([self.cf_endpoint, 'api', 'v1', 'namespaces'])
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            raise RuntimeError("Error: http code {} while listing namespaces.".format(res.status_code))
        iam_response = res.json()
        logger.debug(iam_response)

        for ns in iam_response['namespaces']:
            if 'name' in ns and ns['name'] == self.cf_namespace:
                logger.debug("Found name space id {} for {}".format(ns['id'], self.cf_namespace))
                return ns['id']
            elif ns['id'] == self.cf_namespace:
                raise Exception('IBM Cloud Functions namespace "{}" is not IAM enabled'.format(self.cf_namespace))

        raise Exception('No IBM Cloud Functions namespace "{}" found'.format(self.cf_namespace))
