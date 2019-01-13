#
# (C) Copyright IBM Corp. 2018
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

import requests
import base64
import os
import json
import ssl
from urllib.parse import urlparse
import http.client
import logging
import time

logger = logging.getLogger(__name__)


class CloudFunctions:

    def __init__(self, config):
        """
        Constructor
        """
        self.api_key = str.encode(config['api_key'])
        self.endpoint = config['endpoint'].replace('http:', 'https:')
        self.namespace = config['namespace']
        self.runtime = config['action_name']
        self.memory = int(config['action_memory'])
        self.timeout = int(config['action_timeout'])
        self.is_cf_cluster = config['is_cf_cluster']

        auth = base64.encodebytes(self.api_key).replace(b'\n', b'')
        self.headers = {
            'content-type': 'application/json',
            'Authorization': 'Basic %s' % auth.decode('UTF-8')
        }

        self.session = requests.session()
        self.session.headers.update(self.headers)
        adapter = requests.adapters.HTTPAdapter()
        self.session.mount('https://', adapter)

        msg = 'IBM Cloud Functions init for'
        logger.info('{} namespace: {} host {}'.format(msg, self.namespace, self.endpoint))
        if logger.getEffectiveLevel() == logging.DEBUG:
            print("{} namespace: {} and host: {}".format(msg, self.namespace,
                                                         self.endpoint))

    def create_action(self, action_name, code=None, kind='blackbox',
                      image='ibmfunctions/action-python-v3.6', is_binary=True, overwrite=True):
        """
        Create an IBM Cloud Function
        """
        logger.debug('I am about to create a new cloud function action')
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.namespace, 'actions',
                           action_name + "?overwrite=" + str(overwrite))

        data = {}
        limits = {}
        cfexec = {}

        limits['timeout'] = self.timeout
        limits['memory'] = self.memory
            
        if limits['timeout'] and limits['memory']:
            data['limits'] = limits

        cfexec['kind'] = kind
        if kind == 'blackbox':
            cfexec['image'] = image
        cfexec['binary'] = is_binary
        cfexec['code'] = base64.b64encode(code).decode("utf-8") if is_binary else code
        data['exec'] = cfexec

        res = self.session.put(url, json=data)

        if res.status_code != 200:
            print('An error occurred updating action {}'.format(action_name))
        else:
            print("OK --> Updated action {}".format(action_name))

    def get_action(self, action_name):
        """
        Get an IBM Cloud Function
        """
        logger.debug("I am about to get a cloud function action: {}".format(action_name))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.namespace, 'actions', action_name)
        res = self.session.get(url)
        return res.json()

    def delete_action(self, action_name):
        """
        Delete an IBM Cloud Function
        """
        if logger.getEffectiveLevel() == logging.DEBUG:
            print("Delete cloud function action: {}".format(action_name))

        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.namespace, 'actions', action_name)
        res = self.session.delete(url)

        if res.status_code != 200:
            print('An error occurred deleting action {}'.format(action_name))

    def invoke(self, action_name, payload):
        """
        Wrapper around actual invocation methods
        """
        if self.is_cf_cluster:
            return self.internal_invoke(action_name, payload)
        else:
            return self.remote_invoke(action_name, payload)

    def remote_invoke(self, action_name, payload):
        """
        Invoke an IBM Cloud Function. Better from a remote network.
        """
        exec_id = payload['executor_id']
        call_id = payload['call_id']
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.namespace, 'actions', action_name)

        try:
            resp = self.session.post(url, json=payload)
            data = resp.json()
            resp_time = format(round(resp.elapsed.total_seconds(), 3), '.3f')
            if 'activationId' in data:
                log_msg = ('Executor ID {} Function {} - Activation ID: '
                           '{} - Time: {} seconds'.format(exec_id, call_id,
                                                          data["activationId"],
                                                          resp_time))
                logger.debug(log_msg)
                if logger.getEffectiveLevel() == logging.WARNING:
                    print(log_msg)
                return data["activationId"]
            else:
                logger.debug(data)
                return None
        except:
            return self.remote_invoke(action_name, payload)

    def internal_invoke(self, action_name, payload):
        """
        Invoke an IBM Cloud Function. Better from a cloud function.
        """
        exec_id = payload['executor_id']
        call_id = payload['call_id']

        url = urlparse(os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                                    self.namespace, 'actions', action_name))
        ctx = ssl._create_unverified_context()
        conn = http.client.HTTPSConnection(url.netloc, context=ctx)

        try:
            start = time.time()
            conn.request("POST", url.geturl(),
                         body=json.dumps(payload),
                         headers=self.headers)
            resp = conn.getresponse()
            data = resp.read()
            roundtrip = time.time() - start
            resp_time = format(round(roundtrip, 3), '.3f')
            data = json.loads(data.decode("utf-8"))
            conn.close()

            if 'activationId' in data:
                log_msg = ('Executor ID {} Function {} - Activation ID: '
                           '{} - Time: {} seconds'.format(exec_id, call_id,
                                                          data["activationId"],
                                                          resp_time))
                logger.debug(log_msg)
                if logger.getEffectiveLevel() == logging.WARNING:
                    print(log_msg)
                return data["activationId"]
            else:
                logger.debug(data)
                return None
        except:
            conn.close()
            return self.internal_invoke(action_name, payload)

    def invoke_with_result(self, action_name, payload={}):
        """
        Invoke an IBM Cloud Function waiting for the result.
        """
        url = os.path.join(self.endpoint, 'api', 'v1',
                           'namespaces', self.namespace, 'actions',
                           action_name + "?blocking=true&result=true")
        resp = self.session.post(url, json=payload)
        result = resp.json()

        return result
