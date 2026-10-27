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
import time
import json
import base64
import logging
import requests
import urllib3
import http.client
from urllib.parse import quote, urlparse
from urllib3.exceptions import InsecureRequestWarning


logger = logging.getLogger(__name__)

# OpenWhisk returns at most this many entities per list request. Asking for
# less silently stops at the server default, which is 30
_LIST_LIMIT = 200


def _normalize_endpoint(endpoint):
    """
    Keeps the scheme the caller configured. OpenWhisk standalone serves plain
    http; a host without a scheme is taken as https
    """
    endpoint = endpoint.strip().rstrip('/')
    if '://' not in endpoint:
        endpoint = 'https://' + endpoint
    return endpoint


class OpenWhiskClient:
    """
    Client for the OpenWhisk REST API, api/v1, as served by OpenWhisk 2.x
    (tested against the standalone build openwhisk/standalone:nightly)
    """

    def __init__(self, endpoint, namespace, api_key=None, auth=None, insecure=False,
                 user_agent=None, pool_maxsize=64):
        """
        :param endpoint: OpenWhisk endpoint, including its scheme.
        :param namespace: User namespace.
        :param api_key: HTTP Basic credentials, "uuid:secret".
        :param auth: Authorization header value, "Basic ..." or "Bearer ...".
        :param insecure: Disable TLS certificate verification.
        :param user_agent: Value appended to the User-Agent header.
        :param pool_maxsize: Connections kept per host. The invoker calls
            invoke() from a pool of this many threads.
        """
        self.endpoint = _normalize_endpoint(endpoint)
        self.namespace = namespace
        self.api_key = api_key
        self.auth = auth

        if self.api_key:
            token = base64.b64encode(self.api_key.encode()).decode('ascii')
            self.auth = f'Basic {token}'

        self.session = requests.Session()
        self.session.verify = not insecure
        if insecure:
            urllib3.disable_warnings(InsecureRequestWarning)

        self.session.headers['content-type'] = 'application/json'
        if self.auth:
            self.session.headers['Authorization'] = self.auth
        if user_agent:
            current = self.session.headers.get('User-Agent', 'python-requests')
            self.session.headers['User-Agent'] = f'{current} {user_agent}'

        adapter = requests.adapters.HTTPAdapter(
            pool_connections=pool_maxsize, pool_maxsize=pool_maxsize
        )
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def _url(self, *parts):
        path = '/'.join(quote(str(part), safe='') for part in parts)
        return f'{self.endpoint}/api/v1/{path}'

    def _request(self, method, url, params=None, body=None, timeout=60):
        return self.session.request(method, url, params=params, json=body, timeout=timeout)

    @staticmethod
    def _body(response):
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def _raise(self, response, what):
        body = self._body(response)
        if isinstance(body, dict):
            detail = body.get('error') or body.get('message') or body
        else:
            detail = response.text
        raise Exception(f'An error occurred {what}: {detail}')

    def _list(self, url):
        """Reads a whole collection. A missing one is an empty list"""
        items = []
        skip = 0
        while True:
            response = self._request(method='GET', url=url, params={'limit': _LIST_LIMIT, 'skip': skip})
            if response.status_code == 404:
                return []
            if response.status_code != 200:
                self._raise(response, f'listing {url}')
            page = self._body(response) or []
            items.extend(page)
            if len(page) < _LIST_LIMIT:
                return items
            skip += _LIST_LIMIT

    def create_namespace(self, namespace, resource_group_id):
        """Creates a namespace and returns its id"""
        data = {}
        if resource_group_id:
            data = {
                "name": namespace,
                "description": "Auto-created Lithops namespace",
                "resource_group_id": resource_group_id,
                "resource_plan_id": "functions-base-plan",
            }
        res = self._request('POST', self._url('namespaces'), body=data)
        resp_text = self._body(res) or {}
        if res.status_code == 201:
            logger.debug(f"OK --> Namespace created {namespace}")
            self.namespace = resp_text['id']
            return resp_text['id']
        msg = f"An error occurred creating the namsepace {namespace}: {resp_text.get('message')}"
        raise Exception(msg)

    def delete_namespace(self, namespace):
        """Deletes a namespace. A missing one is not an error"""
        res = self._request('DELETE', self._url('namespaces', namespace))
        if res.status_code == 200:
            logger.debug("OK --> Namespace deleted")
        elif res.status_code == 404:
            pass
        else:
            resp_text = self._body(res) or {}
            msg = f"An error occurred deleting the namsepace: {resp_text.get('message')}"
            raise Exception(msg)

    def list_namespaces(self, resource_group_id):
        """Lists namespaces. The filter is sent in the request body"""
        data = {}
        if resource_group_id:
            data = {"resource_group_id": resource_group_id, "resource_plan_id": "functions-base-plan"}
        res = self._request('GET', self._url('namespaces'), body=data or None)
        resp_text = self._body(res) or {}
        if res.status_code == 200:
            return resp_text
        msg = f"An error occurred listing the namespaces: {resp_text.get('message')}"
        raise Exception(msg)

    def create_action(self, package, action_name, image_name=None, code=None, memory=None,
                      timeout=30000, kind='blackbox', is_binary=True, overwrite=True):
        """
        Creates or replaces an action. `timeout` is milliseconds, `memory` megabytes,
        as the API requires. A blackbox action is a Docker image; the image may carry
        its own code, or `code` is injected into it at init
        """
        limits = {}
        if memory is not None:
            limits['memory'] = memory
        if timeout is not None:
            limits['timeout'] = timeout

        action_exec = {'kind': kind}
        if kind == 'blackbox':
            if not image_name:
                raise ValueError(f'Action {action_name} is a Docker action and needs an image')
            action_exec['image'] = image_name
        if code is not None:
            action_exec['binary'] = is_binary
            if is_binary:
                raw = code.encode() if isinstance(code, str) else code
                action_exec['code'] = base64.b64encode(raw).decode('ascii')
            else:
                action_exec['code'] = code

        data = {'exec': action_exec}
        if limits:
            data['limits'] = limits

        logger.debug(f'Creating action: {action_name}')
        url = self._url('namespaces', self.namespace, 'actions', package, action_name)
        res = self._request(
            'PUT', url, params={'overwrite': 'true' if overwrite else 'false'}, body=data
        )

        if res.status_code in (200, 201):
            logger.debug(f"OK --> Created action {action_name}")
            return
        self._raise(res, f'creating/updating action {action_name}')

    def get_action(self, package, action_name):
        """Returns one action, or None when it does not exist"""
        url = self._url('namespaces', self.namespace, 'actions', package, action_name)
        res = self._request('GET', url)
        if res.status_code == 200:
            return self._body(res)
        if res.status_code == 404:
            return None
        self._raise(res, f'getting action {action_name}')

    def list_actions(self, package):
        """Lists every action in a package, following the server's pages"""
        logger.debug(f"Listing all actions from: {package}")
        # The trailing slash asks for the actions inside the package
        return self._list(self._url('namespaces', self.namespace, 'actions', package, ''))

    def delete_action(self, package, action_name):
        """Deletes an action. One that is already gone is not an error"""
        logger.debug(f"Deleting action: {action_name}")
        url = self._url('namespaces', self.namespace, 'actions', package, action_name)
        res = self._request('DELETE', url)
        if res.status_code in (200, 404):
            return
        self._raise(res, f'deleting action {action_name}')

    def list_packages(self):
        """Lists every package in the namespace, following the server's pages"""
        logger.debug('Listing packages')
        return self._list(self._url('namespaces', self.namespace, 'packages'))

    def delete_package(self, package):
        """Deletes a package. One that is already gone is not an error"""
        logger.debug(f"Deleting package: {package}")
        url = self._url('namespaces', self.namespace, 'packages', package)
        res = self._request('DELETE', url)
        if res.status_code in (200, 404):
            return self._body(res)
        self._raise(res, f'deleting the package {package}')

    def create_package(self, package):
        """
        Creates a package. A package that already exists is left as it is,
        so a redeploy does not drop the parameters stored on it
        """
        logger.debug(f'Creating package {package}')
        url = self._url('namespaces', self.namespace, 'packages', package)
        res = self._request(
            'PUT', url, params={'overwrite': 'false'}, body={"name": package}
        )
        if res.status_code in (200, 201, 409):
            logger.debug(f"OK --> Package {package} is present")
            return
        self._raise(res, f'creating package {package}')

    def invoke(self, package, action_name, payload=None, is_ow_action=False, self_invoked=False):
        """
        Invokes an action without waiting for it.

        Returns the activation id, None when the namespace is throttled (429,
        the caller invokes it again later), or the int 401 or 404 so the
        caller can report a bad key or a missing action. Any other failure
        raises. A dropped connection is tried once.

        Each call opens its own connection and closes it. A requests session
        keeps a pool of 10 connections per host unless told otherwise, so the
        invoker threads queue for a socket, and it sends the next call down a
        socket the controller may already have closed. `is_ow_action` is
        accepted for callers; a worker uses the same connection
        """
        logger.debug(f'Invoking {package}/{action_name} (worker={is_ow_action})')
        url = self._url('namespaces', self.namespace, 'actions', package, action_name)
        try:
            status, raw = self._post_invoke(url, payload or {})
        except (http.client.HTTPException, OSError) as e:
            if self_invoked:
                raise
            logger.debug(f'Invocation failed: {e}. Retrying once')
            return self.invoke(
                package, action_name, payload, is_ow_action=is_ow_action, self_invoked=True
            )

        if status in (401, 404):
            return status
        data = _decode_body(raw)
        if status == 202 and isinstance(data, dict) and 'activationId' in data:
            return data['activationId']
        if status == 429:
            return None
        if isinstance(data, dict) and 'error' in data:
            raise Exception(data['error'])
        raise Exception(f'An error occurred invoking action {action_name}: {data or raw.decode(errors="replace")}')

    def _post_invoke(self, url, payload):
        """POSTs once on a new connection and always closes it"""
        parsed = urlparse(url)
        body = json.dumps(payload, default=str).encode()
        headers = {'Content-Type': 'application/json', 'Connection': 'close'}
        authorization = self.session.headers.get('Authorization')
        if authorization:
            headers['Authorization'] = authorization
        user_agent = self.session.headers.get('User-Agent')
        if user_agent:
            headers['User-Agent'] = user_agent

        if parsed.scheme == 'https':
            context = ssl.create_default_context() if self.session.verify else ssl._create_unverified_context()
            conn = http.client.HTTPSConnection(
                parsed.hostname, parsed.port, timeout=60, context=context
            )
        elif parsed.scheme == 'http':
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=60)
        else:
            raise ValueError(f'Unsupported endpoint scheme in {url}')

        path = parsed.path or '/'
        if parsed.query:
            path = f'{path}?{parsed.query}'
        try:
            conn.request('POST', path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def get_activation(self, activation_id):
        """Returns an activation, or None while it is not stored yet"""
        url = self._url('namespaces', self.namespace, 'activations', activation_id)
        res = self._request('GET', url)
        if res.status_code == 200:
            return self._body(res)
        if res.status_code == 404:
            return None
        self._raise(res, f'getting activation {activation_id}')

    def invoke_with_result(self, package, action_name, payload=None, timeout=180):
        """
        Invokes an action and returns its result. The controller holds the
        request for a short while; if the action is still running, the
        activation is polled until `timeout` seconds have passed
        """
        url = self._url('namespaces', self.namespace, 'actions', package, action_name)
        deadline = time.monotonic() + timeout
        response = None
        while time.monotonic() < deadline:
            remaining = max(1, deadline - time.monotonic())
            try:
                # Wait out the whole budget. The controller answers earlier, with
                # the result or with the activation id, and a second POST would
                # start a second activation
                response = self._request(
                    'POST', url,
                    params={'blocking': 'true', 'result': 'true'},
                    body=payload or {},
                    timeout=(10, remaining),
                )
            except requests.Timeout:
                raise Exception(f'Timed out invoking {package}/{action_name}') from None
            if response.status_code != 429:
                break
            time.sleep(1)
        else:
            raise Exception(f'Timed out invoking {package}/{action_name}')

        data = self._body(response)
        if response.status_code == 200 and not _is_pending(data):
            return data
        if response.status_code in (200, 202) and _is_pending(data):
            return self._wait_for_activation(data['activationId'], deadline)
        self._raise(response, f'invoking action {action_name}')

    def _wait_for_activation(self, activation_id, deadline):
        """Polls an activation until it has a result or the deadline passes"""
        while time.monotonic() < deadline:
            activation = self.get_activation(activation_id)
            result = _activation_result(activation)
            if result is not None:
                status, value = result
                if status == 'success':
                    return value
                raise Exception(f'Activation {activation_id} failed ({status}): {value}')
            time.sleep(1)
        raise Exception(f'Timed out waiting for activation {activation_id}')


def _decode_body(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _is_pending(data):
    """A not-yet-finished blocking call comes back as only an activation id"""
    return isinstance(data, dict) and 'activationId' in data and 'preinstalls' not in data and len(data) == 1


def _activation_result(activation):
    """
    (status, result) once the activation has finished, None while it is running.
    OpenWhisk stores an activation only after it completes, so a missing one is
    still running
    """
    if not isinstance(activation, dict):
        return None
    response = activation.get('response')
    if not isinstance(response, dict) or 'status' not in response:
        return None
    return response['status'], response.get('result')
