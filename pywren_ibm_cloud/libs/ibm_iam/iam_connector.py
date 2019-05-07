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

import urllib
import os
from tornado.escape import json_decode
from tornado.httpclient import HTTPClient, HTTPError
from tornado.httputil import HTTPHeaders

import logging

logger = logging.getLogger(__name__)

class IAM():


    def __init__(self, iam_config, cf_endpoint, cf_namespace):
        self.iam_api_key = None
        if 'api_key' in iam_config:
            self.iam_api_key = iam_config['api_key']
        self.iam_auth_endpoint = iam_config['ibm_auth_endpoint']
        self.cf_endpoint = cf_endpoint
        self.cf_namespace = cf_namespace
        logger.debug("init method for {} namespace {}".format(*self.cf_endpoint,self.cf_namespace))
        
    def is_IAM_access(self):
        return self.iam_api_key is not None
    
    def get_iam_token(self):
        data = urllib.parse.urlencode({'grant_type': 'urn:ibm:params:oauth:grant-type:apikey', 'apikey': self.iam_api_key})
        request_headers_xml_content = HTTPHeaders({'Content-Type': 'application/x-www-form-urlencoded'})
        request_headers_xml_content.add('Accept', 'application/json')
    
        client = HTTPClient()
        response = client.fetch(
            self.iam_auth_endpoint,
            method='POST',
            headers=request_headers_xml_content,
            validate_cert=False,
            body=data)
    
        if response.code != 200:
            raise RuntimeError("Error: http code {} while retrieving IAM token for API key.".format(response.code))
            
        bearer_response = json_decode(response.body)
        bearer_token = 'Bearer ' + bearer_response['access_token']
        return bearer_token
    
    def get_function_namespace_id(self, iam_token):
        logger.debug("Getting name space id for {}".format(self.cf_namespace))
        request_headers = HTTPHeaders({'Content-Type': 'application/json'})
        request_headers.add('accept', 'application/json')
        request_headers.add('authorization', iam_token)
    
        client = HTTPClient()
        url = os.path.join(self.cf_endpoint, 'api', 'v1', 'namespaces?limit=0&offset=0').replace("\\", "/")
        response = client.fetch(
            url,
            method='GET',
            headers=request_headers,
            validate_cert=False)
        if response.code != 200:
            raise RuntimeError("Error: http code {} while listing namespaces.".format(response.code))
        namespaces = json_decode(response.body)
    
        for current_namespace in namespaces['namespaces']:
            if 'name' in current_namespace and current_namespace['name'] == self.cf_namespace:
                logger.debug("Found name space id {} for {}".format(current_namespace['id'], self.cf_namespace))
                return current_namespace['id']
    
        raise RuntimeError("Error: No CF namespace \"{}\" found.".format(self.cf_namespace))