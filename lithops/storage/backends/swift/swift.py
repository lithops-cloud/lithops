#
# (C) Copyright IBM Corp. 2020
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
import re
import json
import shutil
import logging
import requests
from urllib.parse import urlsplit, urlunsplit

from lithops.storage.utils import StorageNoSuchKeyError
from lithops.utils import sizeof_fmt
from lithops.constants import STORAGE_CLI_MSG

logger = logging.getLogger(__name__)

# Keystone ids are 32 hex characters, or a UUID with hyphens
_OPENSTACK_ID = re.compile(
    r'^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$'
)


class StorageBackend:
    """
    A wrap-up around OpenStack Swift APIs.
    """

    def __init__(self, swift_config):
        logger.debug("Creating OpenStack Swift client")
        self.config = swift_config
        self.auth_url = swift_config['auth_url'].rstrip('/')
        self.user_id = swift_config.get('user_id')
        self.project_id = swift_config.get('project_id')
        self.password = swift_config.get('password')
        self.region = swift_config.get('region')
        # Keystone's own default domain is named Default. "default" does not match it
        self.user_domain_name = swift_config.get('user_domain_name', 'Default')
        self.project_domain_name = swift_config.get('project_domain_name', 'Default')
        configured_endpoint = swift_config.get('endpoint')

        if swift_config.get('token'):
            if not configured_endpoint:
                raise Exception('A Swift token also needs the storage endpoint')
            self.token = swift_config['token']
            self.endpoint = configured_endpoint
        else:
            self.token = self.generate_swift_token()
            if configured_endpoint:
                self.endpoint = configured_endpoint
            swift_config['token'] = self.token
            swift_config['endpoint'] = self.endpoint

        self.session = requests.session()
        self.session.headers.update({'X-Auth-Token': self.token})
        adapter = requests.adapters.HTTPAdapter(pool_maxsize=64, max_retries=3)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        msg = STORAGE_CLI_MSG.format('OpenStack Swift')
        logger.info("{} - Region: {}".format(msg, self.region))

    def generate_bucket_name(self):
        """
        Generates a unique bucket name
        """
        owner = self.config.get('user_name') or self.user_id or 'user'
        self.config['storage_bucket'] = f'lithops-{self.region}-{owner[:6].lower()}'

        return self.config['storage_bucket']

    def get_client(self):
        """The requests session that carries the Keystone token"""
        return self.session

    def create_bucket(self, bucket_name):
        """
        Create a container. Swift answers 202 when it already exists
        """
        url = '/'.join([self.endpoint.rstrip('/'), bucket_name])
        res = self.session.put(url)
        if res.status_code not in (201, 202):
            raise Exception(
                f'PUT container {bucket_name} failed with status {res.status_code}'
            )

    def _token_url(self):
        """Keystone identity URL. auth_url may already end in /v3"""
        if self.auth_url.endswith('/v3'):
            return self.auth_url + '/auth/tokens'
        return self.auth_url + '/v3/auth/tokens'

    def _user_identity(self):
        """
        A user is an id, or a name in a domain. Keystone rejects a domain
        on a user that was named by id
        """
        user_name = self.config.get('user_name')
        if user_name:
            return {
                'name': user_name,
                'password': self.password,
                'domain': {'name': self.user_domain_name},
            }
        if _OPENSTACK_ID.match(self.user_id or ''):
            return {'id': self.user_id, 'password': self.password}
        if not self.user_id:
            raise Exception('Swift config needs user_id or user_name')
        # user_id has historically held the user name
        return {
            'name': self.user_id,
            'password': self.password,
            'domain': {'name': self.user_domain_name},
        }

    def _project_scope(self):
        """A project is an id, or a name in a domain. The two cannot be mixed"""
        project_name = self.config.get('project_name')
        if project_name:
            return {
                'name': project_name,
                'domain': {'name': self.project_domain_name},
            }
        if _OPENSTACK_ID.match(self.project_id or ''):
            return {'id': self.project_id}
        if not self.project_id:
            raise Exception('Swift config needs project_id or project_name')
        return {
            'name': self.project_id,
            'domain': {'name': self.project_domain_name},
        }

    def _select_endpoint(self, catalog, project_id):
        """The public object-store URL for the configured region"""
        known = []
        for service in catalog:
            if service.get('type') != 'object-store' and service.get('name') != 'swift':
                continue
            for endpoint in service.get('endpoints', []):
                region = endpoint.get('region_id') or endpoint.get('region')
                known.append(region or '')
                if endpoint.get('interface') != 'public':
                    continue
                if self.region and region != self.region:
                    continue
                url = endpoint['url']
                if project_id:
                    url = url.replace('%(project_id)s', project_id)
                    url = url.replace('%(tenant_id)s', project_id)
                return self._endpoint_reachable_from_here(url)
        regions = ', '.join(sorted(set(known))) or 'none'
        raise Exception(
            f'No public Swift endpoint for region {self.region!r}. '
            f'Known regions: {regions}'
        )

    def _endpoint_reachable_from_here(self, url):
        """
        A catalog entry of 0.0.0.0 is the address the server bound, not an
        address a client can open. Use the host Keystone itself was reached on
        """
        parts = urlsplit(url)
        if parts.hostname != '0.0.0.0':
            return url
        auth_host = urlsplit(self.auth_url).hostname
        if not auth_host:
            return url
        netloc = auth_host if parts.port is None else f'{auth_host}:{parts.port}'
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    def generate_swift_token(self):
        """
        Generates new token for accessing to Swift.
        :return: token
        """
        payload = {
            'auth': {
                'identity': {
                    'methods': ['password'],
                    'password': {'user': self._user_identity()},
                },
                'scope': {'project': self._project_scope()},
            }
        }
        response = requests.post(
            self._token_url(),
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'},
        )
        if response.status_code != 201:
            try:
                message = response.json()['error']['message']
            except Exception:
                message = response.text
            raise Exception(f'{response.status_code} - {message}')

        body = response.json()
        project_id = (body.get('token') or {}).get('project', {}).get('id')
        self.endpoint = self._select_endpoint(body['token']['catalog'], project_id)
        return response.headers['X-Subject-Token']

    def put_object(self, bucket_name, key, data):
        """
        Put an object in Swift. Override the object if the key already exists.
        :param key: key of the object.
        :param data: data of the object
        :type data: str/bytes
        :return: None
        """
        url = '/'.join([self.endpoint, bucket_name, key])
        res = self.session.put(url, data=data)
        if res.status_code != 201:
            raise Exception(f'PUT {key} failed with status {res.status_code}')
        try:
            logger.debug('PUT Object {} - Size: {} - {}'.format(key, sizeof_fmt(len(data)), 'OK'))
        except Exception:
            logger.debug('PUT Object {} - OK'.format(key))

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from Swift with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        url = '/'.join([self.endpoint, bucket_name, key])
        headers = {'X-Auth-Token': self.token}
        headers.update(extra_get_args)
        res = self.session.get(url, headers=headers, stream=stream)
        if res.status_code in (200, 206):
            return res.raw if stream else res.content
        if res.status_code == 404:
            raise StorageNoSuchKeyError(bucket_name, key)
        raise Exception('{} - {}'.format(res.status_code, key))

    def upload_file(self, file_name, bucket, key=None, extra_args={}, config=None):
        """Upload a file

        :param file_name: File to upload
        :param bucket: Bucket to upload to
        :param key: S3 object name. If not specified then file_name is used
        :return: True if file was uploaded, else False
        """
        # If S3 key was not specified, use file_name
        if key is None:
            key = os.path.basename(file_name)

        # Upload the file
        try:
            with open(file_name, 'rb') as in_file:
                self.put_object(bucket, key, in_file)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def download_file(self, bucket, key, file_name=None, extra_args={}, config=None):
        """Download a file

        :param bucket: Bucket to download from
        :param key: S3 object name. If not specified then file_name is used
        :param file_name: File to upload
        :return: True if file was downloaded, else False
        """
        # If file_name was not specified, use S3 key
        if file_name is None:
            file_name = key

        # Download the file
        try:
            dirname = os.path.dirname(file_name)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname)
            with open(file_name, 'wb') as out:
                data_stream = self.get_object(bucket, key, stream=True)
                shutil.copyfileobj(data_stream, out)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def head_object(self, bucket_name, key):
        """
        Head object from Swift with a key. Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        url = '/'.join([self.endpoint, bucket_name, key])
        res = self.session.head(url)
        if res.status_code == 200:
            return res.headers
        if res.status_code == 404:
            raise StorageNoSuchKeyError(bucket_name, key)
        raise Exception('{} - {}'.format(res.status_code, key))

    def delete_object(self, bucket_name, key):
        """
        Delete an object from Swift.
        :param bucket: bucket name
        :param key: data key
        """
        url = '/'.join([self.endpoint, bucket_name, key])
        res = self.session.delete(url)
        if res.status_code not in (204, 404):
            raise Exception(f'{res.status_code} - {key}')
        return res

    def delete_objects(self, bucket_name, key_list):
        """
        Delete a list of objects from Swift.
        :param bucket: bucket name
        :param key: data key
        """
        headers = {'X-Auth-Token': self.token,
                   'X-Bulk-Delete': 'True'}

        keys_to_delete = []
        for key in key_list:
            keys_to_delete.append('/{}/{}'.format(bucket_name, key))

        keys_to_delete = '\n'.join(keys_to_delete)
        url = self.endpoint.rstrip('/') + '/?bulk-delete'
        res = self.session.delete(url, data=keys_to_delete, headers=headers)
        if res.status_code != 200:
            raise Exception(
                f'Bulk delete of {bucket_name} failed with status {res.status_code}'
            )
        return res

    def head_bucket(self, bucket_name):
        """
        Head a container. Throws StorageNoSuchKeyError if it does not exist.
        :param bucket_name: name of the container
        :return: response headers
        """
        url = '/'.join([self.endpoint, bucket_name])
        res = self.session.head(url)
        if res.status_code == 404:
            raise StorageNoSuchKeyError(bucket_name, '')
        if not 200 <= res.status_code < 300:
            raise Exception('{} - {}'.format(res.status_code, bucket_name))
        return res.headers

    def list_objects(self, bucket_name, prefix='', match_pattern=None):
        """
        Lists the objects in a bucket. Throws StorageNoSuchKeyError if the bucket does not exist.
        :param bucket_name: name of the bucket
        :param prefix: prefix to filter object names
        :return: one dict per object, with its key ('Key') and size in bytes ('Size')
        :rtype: list of dict
        """
        url = '/'.join([self.endpoint, bucket_name])
        params = {'format': 'json', 'prefix': prefix or ''}
        objects = []
        # A listing returns at most one page of objects (10,000 by default),
        # and the next one starts after the last name of the previous one
        while True:
            res = self.session.get(url, params=params)
            if res.status_code == 404:
                raise StorageNoSuchKeyError(bucket_name, prefix)
            # Past the last page the listing is empty. Some Swift versions
            # answer that with a 204 and no body. An empty error response
            # is not the end of the listing
            if res.status_code == 204 or (res.status_code == 200 and not res.content):
                return objects
            if res.status_code != 200:
                raise Exception(
                    f'{res.status_code} listing {bucket_name}/{prefix}'
                )
            page = res.json()
            if not page:
                return objects
            # Swift names the key 'name' and the size 'bytes'
            objects.extend({'Key': obj['name'], 'Size': obj['bytes']} for obj in page)
            params['marker'] = page[-1]['name']

    def list_keys(self, bucket_name, prefix):
        """
        Return a list of keys for the given prefix.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        """
        objects = self.list_objects(bucket_name, prefix)
        object_keys = [r['Key'] for r in objects]
        return object_keys
