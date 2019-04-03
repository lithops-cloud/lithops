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
from pywren_ibm_cloud.version import __version__

logger = logging.getLogger(__name__)


class CloudFunctions:

    def __init__(self, config):
        """
        Constructor
        """
        self.api_key = str.encode(config['api_key'])
        self.endpoint = config['endpoint'].replace('http:', 'https:')
        self.namespace = config['namespace']
        self.default_runtime_memory = int(config['runtime_memory'])
        self.default_runtime_timeout = int(config['runtime_timeout'])
        self.is_cf_cluster = config['is_cf_cluster']
        self.package = 'pywren_v'+__version__

        auth = base64.encodebytes(self.api_key).replace(b'\n', b'')
        self.session = requests.session()
        default_user_agent = self.session.headers['User-Agent']
        self.headers = {
            'content-type': 'application/json',
            'Authorization': 'Basic %s' % auth.decode('UTF-8'),
            'User-Agent': default_user_agent + ' pywren-ibm-cloud'
        }

        self.session.headers.update(self.headers)
        adapter = requests.adapters.HTTPAdapter()
        self.session.mount('https://', adapter)

        msg = 'IBM Cloud Functions init for'
        logger.info('{} namespace: {}'.format(msg, self.namespace))
        logger.info('{} host: {}'.format(msg, self.endpoint))
        logger.debug("CF user agent set to: {}".format(self.session.headers['User-Agent']))

        if logger.getEffectiveLevel() == logging.WARNING:
            print("{} Namespace: {}".format(msg, self.namespace))
            print("{} Host: {}".format(msg, self.endpoint))

    def create_action(self, action_name, image_name, code=None, memory=None, kind='blackbox',
                      is_binary=True, overwrite=True):
        """
        Create an IBM Cloud Function
        """
        data = {}
        limits = {}
        cfexec = {}
        limits['memory'] = self.default_runtime_memory if not memory else memory
        limits['timeout'] = self.default_runtime_timeout
        data['limits'] = limits

        cfexec['kind'] = kind
        if kind == 'blackbox':
            cfexec['image'] = image_name
        cfexec['binary'] = is_binary
        cfexec['code'] = base64.b64encode(code).decode("utf-8") if is_binary else code
        data['exec'] = cfexec

        logger.debug('I am about to create a new cloud function action')
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.namespace, 'actions', self.package,
                           action_name + "?overwrite=" + str(overwrite)).replace("\\", "/")
        res = self.session.put(url, json=data)

        if res.status_code != 200:
            print('An error occurred updating action {}: {}'.format(action_name, res.text))
        else:
            print("OK --> Created action {}".format(action_name))

    def get_action(self, action_name):
        """
        Get an IBM Cloud Function
        """
        logger.debug("I am about to get a cloud function action: {}".format(action_name))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.namespace, 'actions', self.package, action_name).replace("\\", "/")
        res = self.session.get(url)
        return res.json()

    def delete_action(self, action_name):
        """
        Delete an IBM Cloud Function
        """
        logger.debug("Delete cloud function action: {}".format(action_name))

        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.namespace, 'actions', self.package, action_name).replace("\\", "/")
        res = self.session.delete(url)

        if res.status_code != 200:
            logger.debug('An error occurred deleting action {}: {}'.format(action_name, res.text))

    def update_memory(self, action_name, memory):
        logger.debug('I am about to update the memory of the {} action to {}'.format(action_name, memory))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.namespace, 'actions', self.package,
                           action_name + "?overwrite=True").replace("\\", "/")

        data = {"limits": {"memory": memory}}
        res = self.session.put(url, json=data)

        if res.status_code != 200:
            logger.debug('An error occurred updating action {}: {}'.format(action_name, res.text))
        else:
            logger.debug("OK --> Updated action memory {}".format(action_name))

    def create_package(self):
        logger.debug('I am about to crate the package {}'.format(self.package))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.namespace, 'packages',
                           self.package + "?overwrite=False").replace("\\", "/")

        data = {"name": self.package}
        res = self.session.put(url, json=data)

        if res.status_code != 200:
            logger.debug('An error occurred creating the package {}: Already exists'.format(self.package, res.text))
        else:
            logger.debug("OK --> Created package {}".format(self.package))

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
                           self.namespace, 'actions', self.package, action_name).replace("\\", "/")

        try:
            resp = self.session.post(url, json=payload)
            data = resp.json()
            resp_time = format(round(resp.elapsed.total_seconds(), 3), '.3f')
        except Exception:
            return self.remote_invoke(action_name, payload)

        if 'activationId' in data:
            log_msg = ('Executor ID {} Function {} - Activation ID: '
                       '{} - Time: {} seconds'.format(exec_id, call_id,
                                                      data["activationId"],
                                                      resp_time))
            logger.debug(log_msg)
            return data["activationId"]
        else:
            logger.debug(data)
            return None

    def internal_invoke(self, action_name, payload):
        """
        Invoke an IBM Cloud Function. Better from a cloud function.
        """
        exec_id = payload['executor_id']
        call_id = payload['call_id']

        url = urlparse(os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                                    self.namespace, 'actions', self.package, action_name))
        ctx = ssl._create_unverified_context()

        try:
            start = time.time()
            conn = http.client.HTTPSConnection(url.netloc, context=ctx)
            conn.request("POST", url.geturl(),
                         body=json.dumps(payload),
                         headers=self.headers)
            resp = conn.getresponse()
            data = resp.read()
            roundtrip = time.time() - start
            resp_time = format(round(roundtrip, 3), '.3f')
            data = json.loads(data.decode("utf-8"))
            conn.close()
        except Exception:
            conn.close()
            return self.internal_invoke(action_name, payload)

        if 'activationId' in data:
            log_msg = ('Executor ID {} Function {} - Activation ID: '
                       '{} - Time: {} seconds'.format(exec_id, call_id,
                                                      data["activationId"],
                                                      resp_time))
            logger.debug(log_msg)
            return data["activationId"]
        else:
            logger.debug(data)
            return None

    def invoke_with_result(self, action_name, payload={}):
        """
        Invoke an IBM Cloud Function waiting for the result.
        """
        url = os.path.join(self.endpoint, 'api', 'v1',
                           'namespaces', self.namespace, 'actions', self.package,
                           action_name + "?blocking=true&result=true").replace("\\", "/")
        resp = self.session.post(url, json=payload)
        result = resp.json()

        return result
