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

import ssl
import json
import base64
import urllib3
import logging
import requests
import http.client
from urllib.parse import urlparse
from urllib3.exceptions import InsecureRequestWarning


urllib3.disable_warnings(InsecureRequestWarning)
logger = logging.getLogger(__name__)


class OpenWhiskClient:

    def __init__(self, endpoint, namespace, api_key=None, auth=None, insecure=False, user_agent=None):
        """
        OpenWhiskClient Constructor

        :param endpoint: OpenWhisk endpoint.
        :param namespace: User namespace.
        :param api_key: User AUTH Key.  HTTP Basic authentication.
        :param auth: Authorization token string "Basic eyJraWQiOiIyMDE5MDcyNCIsImFsZ...".
        :param insecure: Insecure backend. Disable cert verification.
        :param user_agent: User agent on requests.
        """
        self.endpoint = endpoint.replace('http:', 'https:')
        self.url = f'{self.endpoint}/api/v1/namespaces'
        self.namespace = namespace
        self.api_key = api_key
        self.auth = auth

        if self.api_key:
            api_key = str.encode(self.api_key)
            auth_token = base64.encodebytes(api_key).replace(b'\n', b'')
            self.auth = 'Basic %s' % auth_token.decode('UTF-8')

        self.session = requests.session()

        if insecure:
            self.session.verify = False

        self.headers = {
            'content-type': 'application/json',
            'Authorization': self.auth,
        }

        if user_agent:
            default_user_agent = self.session.headers['User-Agent']
            self.headers['User-Agent'] = default_user_agent + f' {user_agent}'

        self.session.headers.update(self.headers)
        adapter = requests.adapters.HTTPAdapter()
        self.session.mount('https://', adapter)

    def create_namespace(self, namespace, resource_group_id):
        """
        Create a WSK namespace
        """
        data = {}

        if resource_group_id:
            data = {"name": namespace, "description": "Auto-created Lithops namespace",
                    "resource_group_id": resource_group_id, "resource_plan_id": "functions-base-plan"}

        res = self.session.post(self.url, json=data)
        resp_text = res.json()

        if res.status_code == 201:
            logger.debug(f"OK --> Namespace created {namespace}")
            self.namespace = resp_text['id']
            return resp_text['id']
        else:
            msg = f"An error occurred creating the namsepace {namespace}: {resp_text['message']}"
            raise Exception(msg)

    def delete_namespace(self, namespace):
        """
        Delete a WSK namespace
        """
        res = self.session.delete(f'{self.url}/{namespace}')

        if res.status_code == 200:
            logger.debug(f"OK --> Namespace deleted {namespace}")
        elif res.status_code == 404:
            pass
        else:
            resp_text = res.json()
            msg = f"An error occurred deleting the namsepace {namespace}: {resp_text['message']}"
            raise Exception(msg)

    def list_namespaces(self, resource_group_id):
        """
        List WSK namespaces
        """
        data = {}

        if resource_group_id:
            data = {"resource_group_id": resource_group_id, "resource_plan_id": "functions-base-plan"}

        res = self.session.get(self.url, json=data)
        resp_text = res.json()

        if res.status_code == 200:
            return resp_text
        else:
            msg = f"An error occurred listing the namespaces: {resp_text['message']}"
            raise Exception(msg)

    def create_action(self, package, action_name, image_name=None, code=None, memory=None,
                      timeout=30000, kind='blackbox', is_binary=True, overwrite=True):
        """
        Create an WSK action
        """
        data = {}
        limits = {}
        cfexec = {}
        limits['memory'] = memory
        limits['timeout'] = timeout
        data['limits'] = limits

        cfexec['kind'] = kind
        if kind == 'blackbox':
            cfexec['image'] = image_name
        cfexec['binary'] = is_binary
        cfexec['code'] = base64.b64encode(code).decode("utf-8") if is_binary else code
        data['exec'] = cfexec

        logger.debug(f'Creating function action: {action_name}')
        url = '/'.join([self.url, self.namespace, 'actions', package,
                        action_name + "?overwrite=" + str(overwrite)])

        res = self.session.put(url, json=data)
        resp_text = res.json()

        if res.status_code == 200:
            logger.debug(f"OK --> Created action {action_name}")
        else:
            msg = f'An error occurred creating/updating action {action_name}: {resp_text["error"]}'
            raise Exception(msg)

    def get_action(self, package, action_name):
        """
        Get an WSK action
        """
        logger.debug(f"Getting cloud function action: {action_name}")
        url = '/'.join([self.url, self.namespace, 'actions', package, action_name])
        res = self.session.get(url)
        return res.json()

    def list_actions(self, package):
        """
        List all WSK actions in a package
        """
        logger.debug(f"Listing all actions from: {package}")
        url = '/'.join([self.url, self.namespace, 'actions', package, ''])
        res = self.session.get(url)
        if res.status_code == 200:
            return res.json()
        else:
            return []

    def delete_action(self, package, action_name):
        """
        Delete an WSK function
        """
        logger.debug(f"Deleting cloud function action: {action_name}")
        url = '/'.join([self.url, self.namespace, 'actions', package, action_name])
        res = self.session.delete(url)
        resp_text = res.json()

        if res.status_code != 200:
            logger.debug(f'An error occurred deleting action {action_name}: {resp_text["error"]}')

    def update_memory(self, package, action_name, memory):
        logger.debug(f'Updating memory of the {action_name} action to {memory}')
        url = '/'.join([self.url, self.namespace, 'actions', package, action_name + "?overwrite=True"])

        data = {"limits": {"memory": memory}}
        res = self.session.put(url, json=data)
        resp_text = res.json()

        if res.status_code != 200:
            logger.debug(f'An error occurred updating action {action_name}: {resp_text["error"]}')
        else:
            logger.debug(f"OK --> Updated action memory {action_name}")

    def list_packages(self):
        """
        List all WSK packages
        """
        logger.debug('Listing function packages')
        url = '/'.join([self.url, self.namespace, 'packages'])

        res = self.session.get(url)

        if res.status_code == 200:
            return res.json()
        else:
            return []

    def delete_package(self, package):
        """
        Delete an WSK package
        """
        logger.debug(f"Deleting functions package: {package}")
        url = '/'.join([self.url, self.namespace, 'packages', package])
        res = self.session.delete(url)
        resp_text = res.json()

        if res.status_code == 200:
            return resp_text
        else:
            logger.debug(f'An error occurred deleting the package {package}: {resp_text["error"]}')

    def create_package(self, package):
        """
        Create a WSK package
        """
        logger.debug(f'Creating functions package {package}')
        url = '/'.join([self.url, self.namespace, 'packages', package + "?overwrite=False"])

        data = {"name": package}
        res = self.session.put(url, json=data)
        resp_text = res.json()

        if res.status_code != 200:
            logger.debug(f'Package {package}: {resp_text["error"]}')
        else:
            logger.debug(f"OK --> Created package {package}")

    def invoke(self, package, action_name, payload={}, is_ow_action=False, self_invoked=False):
        """
        Invoke an WSK function by using new request.
        """
        url = '/'.join([self.url, self.namespace, 'actions', package, action_name])
        parsed_url = urlparse(url)

        try:
            if is_ow_action:
                resp = self.session.post(url, data=json.dumps(payload, default=str), verify=False)
                resp_status = resp.status_code
                data = resp.json()
            else:
                ctx = ssl._create_unverified_context()
                conn = http.client.HTTPSConnection(parsed_url.netloc, context=ctx)
                conn.request("POST", parsed_url.geturl(),
                             body=json.dumps(payload, default=str),
                             headers=self.headers)
                resp = conn.getresponse()
                resp_status = resp.status
                data = json.loads(resp.read().decode("utf-8"))
                conn.close()
        except Exception as e:
            logger.debug(f'Invocation Failed: {str(e)}. Doing reinvocation')
            if not is_ow_action:
                conn.close()
            if self_invoked:
                return None
            return self.invoke(package, action_name, payload, is_ow_action=is_ow_action, self_invoked=True)

        if resp_status == 202 and 'activationId' in data:
            return data["activationId"]
        elif resp_status == 429:
            return None  # "Too many concurrent requests in flight"
        else:
            if resp_status == 401:
                # unauthorized. Probably token expired if using IAM auth
                return resp_status
            elif resp_status == 404:
                # Runtime is not deployed
                return resp_status
            else:
                logger.debug(data)
                raise Exception(data['error'])

    def invoke_with_result(self, package, action_name, payload={}):
        """
        Invoke a WSK function waiting for the result.
        """
        url = '/'.join([self.url, self.namespace, 'actions', package, action_name + "?blocking=true&result=true"])
        resp = self.session.post(url, json=payload)
        result = resp.json()

        return result
