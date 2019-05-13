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

import os
import ssl
import json
import time
import base64
import logging
import requests
import http.client
from urllib.parse import urlparse
from pywren_ibm_cloud.version import __version__
from pywren_ibm_cloud.utils import is_cf_cluster
from pywren_ibm_cloud.libs.ibm_iam.iam_connector import IAM

logger = logging.getLogger(__name__)


class CloudFunctions:

    def __init__(self, config):
        """
        Constructor
        """
        self.endpoint = config['endpoint'].replace('http:', 'https:')
        self.namespace = config['namespace']
        self.default_runtime_memory = int(config['runtime_memory'])
        self.default_runtime_timeout = int(config['runtime_timeout'])
        self.is_cf_cluster = is_cf_cluster()
        self.package = 'pywren_v'+__version__

        self.iam_connector = IAM(config['ibm_iam'], self.endpoint, self.namespace)
        if not self.iam_connector.is_IAM_access():
            self.api_key = str.encode(config['api_key'])

        if not self.iam_connector.is_IAM_access():
            auth_token = base64.encodebytes(self.api_key).replace(b'\n', b'')
            auth = 'Basic %s' % auth_token.decode('UTF-8')
            self.effective_namespace = self.namespace
        else:
            auth = self.iam_connector.get_iam_token()
            self.namespace_id = self.iam_connector.get_function_namespace_id(auth)
            self.effective_namespace = self.namespace_id
        self.session = requests.session()
        default_user_agent = self.session.headers['User-Agent']

        self.headers = {
            'content-type': 'application/json',
            'Authorization': auth,
            'User-Agent': default_user_agent + ' pywren-ibm-cloud/{}'.format(__version__)
        }

        self.session.headers.update(self.headers)
        adapter = requests.adapters.HTTPAdapter()
        self.session.mount('https://', adapter)

        msg = 'IBM Cloud Functions init for'
        logger.debug('{} namespace: {}'.format(msg, self.namespace))
        logger.debug('{} host: {}'.format(msg, self.endpoint))
        logger.debug("CF user agent set to: {}".format(self.session.headers['User-Agent']))

    def create_action(self, action_name, image_name, code=None, memory=None, kind='blackbox',
                      is_binary=True, overwrite=True):
        """
        Create an IBM Cloud Functions action
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

        logger.debug('I am about to create a new cloud function action: {}'.format(action_name))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces',
                           self.effective_namespace, 'actions', self.package,
                           action_name + "?overwrite=" + str(overwrite)).replace("\\", "/")
        res = self.session.put(url, json=data)
        resp_text = res.json()

        if res.status_code == 200:
            logger.debug("OK --> Created action {}".format(action_name))
        else:
            msg = 'An error occurred creating/updating action {}: {}'.format(action_name, resp_text['error'])
            raise Exception(msg)

    def get_action(self, action_name):
        """
        Get an IBM Cloud Functions action
        """
        logger.debug("I am about to get a cloud function action: {}".format(action_name))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces', self.effective_namespace,
                           'actions', self.package, action_name).replace("\\", "/")
        res = self.session.get(url)
        return res.json()

    def list_actions(self, package):
        """
        List all IBM Cloud Functions actions in a package
        """
        logger.debug("I am about to list all actions from: {}".format(package))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces', self.effective_namespace,
                           'actions', self.package, '').replace("\\", "/")
        res = self.session.get(url)
        return res.json()

    def delete_action(self, action_name):
        """
        Delete an IBM Cloud Function
        """
        logger.debug("Delete cloud function action: {}".format(action_name))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces', self.effective_namespace,
                           'actions', self.package, action_name).replace("\\", "/")
        res = self.session.delete(url)
        resp_text = res.json()

        if res.status_code != 200:
            logger.debug('An error occurred deleting action {}: {}'.format(action_name, resp_text['error']))

    def update_memory(self, action_name, memory):
        logger.debug('I am about to update the memory of the {} action to {}'.format(action_name, memory))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces', self.effective_namespace,
                           'actions', self.package, action_name + "?overwrite=True").replace("\\", "/")

        data = {"limits": {"memory": memory}}
        res = self.session.put(url, json=data)
        resp_text = res.json()

        if res.status_code != 200:
            logger.debug('An error occurred updating action {}: {}'.format(action_name, resp_text['error']))
        else:
            logger.debug("OK --> Updated action memory {}".format(action_name))

    def create_package(self, package):
        logger.debug('I am about to crate the package {}'.format(package))
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces', self.effective_namespace,
                           'packages', package + "?overwrite=False").replace("\\", "/")

        data = {"name": package}
        res = self.session.put(url, json=data)
        resp_text = res.json()

        if res.status_code != 200:
            logger.debug('Package {}: {}'.format(package, resp_text['error']))
        else:
            logger.debug("OK --> Created package {}".format(package))

    def invoke(self, action_name, payload):
        """
        Wrapper around actual invocation methods
        """
        if self.is_cf_cluster:
            return self.request_invoke(action_name, payload)
        else:
            return self.request_invoke(action_name, payload)

    def session_invoke(self, action_name, payload):
        """
        Invoke an IBM Cloud Function by using session.
        """
        exec_id = payload['executor_id']
        call_id = payload['call_id']
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces', self.effective_namespace,
                           'actions', self.package, action_name).replace("\\", "/")
        try:
            resp = self.session.post(url, json=payload)
            data = resp.json()
            resp_time = format(round(resp.elapsed.total_seconds(), 3), '.3f')
        except Exception as e:
            logger.debug(str(e))
            return self.session_invoke(action_name, payload)

        if 'activationId' in data:
            log_msg = ('Executor ID {} Function {} invocation done! ({}s) - Activation ID: '
                       '{}'.format(exec_id, call_id, resp_time, data["activationId"]))
            logger.debug(log_msg)
            return data["activationId"]
        else:
            logger.debug(data)
            if resp.status_code == 401:
                raise Exception('Unauthorized - Invalid API Key')
            elif resp.status_code == 404:
                raise Exception('PyWren Runtime: {} not deployed'.format(action_name))
            elif resp.status_code == 429:
                # Too many concurrent requests in flight
                return None
            else:
                raise Exception(data['error'])

    def request_invoke(self, action_name, payload):
        """
        Invoke an IBM Cloud Function by using new request.
        """
        exec_id = payload['executor_id']
        call_id = payload['call_id']
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces', self.effective_namespace,
                           'actions', self.package, action_name).replace("\\", "/")
        url = urlparse(url)
        start = time.time()
        try:
            ctx = ssl._create_unverified_context()
            conn = http.client.HTTPSConnection(url.netloc, context=ctx)
            conn.request("POST", url.geturl(),
                         body=json.dumps(payload),
                         headers=self.headers)
            resp = conn.getresponse()
            data = resp.read()
        except Exception as e:
            conn.close()
            logger.debug(str(e))
            return self.request_invoke(action_name, payload)

        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')
        data = json.loads(data.decode("utf-8"))
        conn.close()

        if resp.status == 202 and 'activationId' in data:
            log_msg = ('Executor ID {} Function {} invocation done! ({}s) - Activation ID: '
                       '{}'.format(exec_id, call_id, resp_time, data["activationId"]))
            logger.debug(log_msg)
            return data["activationId"]
        else:
            logger.debug(data)
            if resp.status == 401:
                raise Exception('Unauthorized - Invalid API Key')
            elif resp.status == 404:
                raise Exception('PyWren Runtime: {} not deployed'.format(action_name))
            elif resp.status == 429:
                # Too many concurrent requests in flight
                return None
            else:
                raise Exception(data['error'])

    def invoke_with_result(self, action_name, payload={}):
        """
        Invoke an IBM Cloud Function waiting for the result.
        """
        url = os.path.join(self.endpoint, 'api', 'v1', 'namespaces', self.effective_namespace, 'actions',
                           self.package, action_name + "?blocking=true&result=true").replace("\\", "/")
        resp = self.session.post(url, json=payload)
        result = resp.json()

        return result
