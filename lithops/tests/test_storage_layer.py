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

import json
import pickle
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lithops.constants import (
    JOBS_PREFIX,
    RUNTIMES_PREFIX,
    SESSION_ID_ENV,
    TEMP_PREFIX,
)
from lithops.storage.backends.localhost.localhost import LocalhostStorageBackend
from lithops.storage.cloud_proxy import (
    CloudFileProxy,
    CloudStorage,
    DelayedBytesBuffer,
    DelayedStringBuffer,
    _path,
    cloud_open,
    remove_lithops_keys,
)
from lithops.storage.storage import (
    RUNTIME_META_CACHE,
    InternalStorage,
    Storage,
)
from lithops.storage.utils import (
    CloudObject,
    CloudObjectLocal,
    CloudObjectUrl,
    StorageConfigMismatchError,
    StorageNoSuchKeyError,
    check_storage_path,
    clean_bucket,
    create_data_key,
    create_func_key,
    create_init_key,
    create_job_key,
    create_output_key,
    create_status_key,
    get_storage_path,
)


def _bare_storage(backend='localhost'):
    storage = Storage.__new__(Storage)
    storage.backend = backend
    storage.bucket = 'storage'
    storage.config = {'backend': backend, backend: {'storage_bucket': 'storage'}}
    storage.storage_handler = MagicMock()
    return storage


def _bare_internal(bucket='storage'):
    internal = InternalStorage.__new__(InternalStorage)
    internal.storage = MagicMock()
    internal.backend = 'localhost'
    internal.bucket = bucket
    return internal


class FakeCloudStorage:
    def __init__(self, keys=None, data=None):
        self.keys = list(keys or [])
        self.data = dict(data or {})
        self.deleted = []
        self.puts = []

    def list_bucket_keys(self, prefix=None):
        if prefix is None:
            return list(self.keys)
        return [key for key in self.keys if key.startswith(prefix)]

    def delete_data(self, key):
        self.deleted.append(key)

    def get_data(self, key):
        return self.data[key]

    def put_data(self, key, data):
        self.puts.append((key, data))
        self.data[key] = data


class TestStorageUtils:

    def test_exception_messages(self):
        err = StorageNoSuchKeyError('bucket', 'key')
        assert str(err) == 'No such key /bucket/key found in storage.'
        mismatch = StorageConfigMismatchError(['a', 'b'], ['c', 'd'])
        assert 'stored at' in str(mismatch)
        assert "['c', 'd']" in str(mismatch)
        assert "['a', 'b']" in str(mismatch)

    def test_cloudobject_str_forms(self):
        assert str(CloudObject('localhost', 'b', 'k')) == (
            '<CloudObject at localhost://b/k>'
        )
        assert str(CloudObjectUrl('https://x')) == '<CloudObject at https://x>'
        local = CloudObjectLocal('/tmp/dir/file.txt')
        assert local.bucket == '/tmp/dir'
        assert local.key == 'file.txt'
        assert str(local) == '<CloudObject at /tmp/dir/file.txt>'

    def test_job_key_builders(self):
        assert create_job_key('sess-0', 'M000') == 'sess-0-M000'
        assert create_func_key('sess-0', 'abc') == (
            f'{JOBS_PREFIX}/sess-0/abc.func.pickle'
        )
        assert create_data_key('sess-0', 'M000') == (
            f'{JOBS_PREFIX}/sess-0-M000/aggdata.pickle'
        )
        assert create_output_key('sess-0', 'M000', '00000') == (
            f'{JOBS_PREFIX}/sess-0-M000/00000/output.pickle'
        )
        assert create_status_key('sess-0', 'M000', '00000') == (
            f'{JOBS_PREFIX}/sess-0-M000/00000/status.json'
        )
        assert create_init_key('sess-0', 'M000', '00000', 'act') == (
            f'{JOBS_PREFIX}/sess-0-M000/00000/act.init'
        )
        for key in (
            create_func_key('sess-0', 'abc'),
            create_data_key('sess-0', 'M000'),
            create_output_key('sess-0', 'M000', '00000'),
        ):
            assert '\\' not in key
            assert key.startswith(f'{JOBS_PREFIX}/')

    def test_storage_path_is_a_list_and_check_raises(self):
        cfg = {'backend': 'localhost', 'localhost': {'storage_bucket': 'b'}}
        path = get_storage_path(cfg)
        assert path == ['localhost', 'b']
        assert type(path) is list
        check_storage_path(cfg, ['localhost', 'b'])
        with pytest.raises(StorageConfigMismatchError):
            check_storage_path(cfg, ['s3', 'other'])

    def test_clean_bucket_loops_until_empty(self):
        storage = MagicMock()
        storage.list_keys.side_effect = [['a', 'b'], ['c'], []]
        sleeps = []
        test_thread = threading.current_thread()

        def sleep(seconds):
            if threading.current_thread() is test_thread:
                sleeps.append(seconds)

        with patch('lithops.storage.utils.time.sleep', side_effect=sleep):
            clean_bucket(storage, 'bucket', 'pref', sleep=2)
        assert storage.delete_objects.call_count == 2
        assert sleeps == [2, 2]


class TestLocalhostStorageKeys:

    @pytest.fixture
    def backend(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'lithops.storage.backends.localhost.localhost.LITHOPS_TEMP_DIR',
            str(tmp_path),
        )
        return LocalhostStorageBackend({})

    def test_list_keys_prefix_is_literal(self, backend):
        # The prefix went to glob, so 'data[1]' matched 'data1.csv' only
        backend.put_object('b', 'data[1].csv', b'x')
        backend.put_object('b', 'data1.csv', b'y')
        backend.put_object('b', 'data[1]/inner', b'z')
        assert sorted(backend.list_keys('b', 'data[1]')) == ['data[1].csv', 'data[1]/inner']
        assert backend.list_keys('b', 'data?') == []
        assert [o['Key'] for o in backend.list_objects('b', 'data[1].')] == ['data[1].csv']

    def test_list_keys_includes_dotfiles(self, backend):
        # glob skips dotfiles, so clean_bucket never deleted them
        backend.put_object('b', 'dir/.hidden', b'x')
        backend.put_object('b', '.top', b'x')
        backend.put_object('b', 'dir/.sub/f', b'x')
        backend.put_object('b', 'dir/visible', b'y')
        assert sorted(backend.list_keys('b')) == ['.top', 'dir/.hidden', 'dir/.sub/f', 'dir/visible']
        assert sorted(backend.list_keys('b', 'dir/')) == ['dir/.hidden', 'dir/.sub/f', 'dir/visible']
        assert sorted(backend.list_keys('b', 'dir/.')) == ['dir/.hidden', 'dir/.sub/f']
        clean_bucket(backend, 'b', 'dir/', sleep=0)
        assert backend.list_keys('b') == ['.top']

    def test_list_objects_skips_keys_deleted_since_listed(self, backend, monkeypatch):
        # A job running alongside deletes its files while the bucket is
        # listed, which made the listing fail
        backend.put_object('b', 'a', b'x')
        backend.put_object('b', 'gone', b'y')
        monkeypatch.setattr(backend, 'list_keys', lambda bucket, prefix=None: ['a', 'gone', 'never'])
        backend.delete_object('b', 'gone')
        assert backend.list_objects('b') == [{'Key': 'a', 'Size': 1}]

    def test_list_keys_partial_and_missing_prefixes(self, backend):
        backend.put_object('b', 'a/b/c1', b'x')
        backend.put_object('b', 'a/b/c2', b'x')
        backend.put_object('b', 'a/bc', b'x')
        assert sorted(backend.list_keys('b', 'a/b')) == ['a/b/c1', 'a/b/c2', 'a/bc']
        assert sorted(backend.list_keys('b', 'a/b/c')) == ['a/b/c1', 'a/b/c2']
        assert backend.list_keys('b', 'a/b/c1') == ['a/b/c1']
        assert backend.list_keys('b', 'zz/') == []
        assert backend.list_keys('b', '/a') == []
        assert backend.list_keys('missing-bucket') == []

    @pytest.mark.parametrize('byte_range, expected', [
        ('bytes=2-4', b'234'),
        ('bytes=5-', b'56789'),
        ('bytes=-3', b'789'),
        ('bytes=-30', b'0123456789'),
    ])
    def test_get_object_ranges(self, backend, byte_range, expected):
        # An open-ended range crashed in int('') and was reported as a
        # missing key
        backend.put_object('b', 'k', b'0123456789')
        assert backend.get_object('b', 'k', extra_get_args={'Range': byte_range}) == expected

    def test_get_object_bad_range_is_not_a_missing_key(self, backend):
        backend.put_object('b', 'k', b'0123456789')
        with pytest.raises(ValueError):
            backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=x-'})
        with pytest.raises(StorageNoSuchKeyError):
            backend.get_object('b', 'missing', extra_get_args={'Range': 'bytes=5-'})
        with pytest.raises(StorageNoSuchKeyError):
            backend.get_object('b', 'k/below-a-file')
        backend.put_object('b', 'dir/f', b'x')
        with pytest.raises(StorageNoSuchKeyError):
            backend.get_object('b', 'dir')


class TestSwiftBackend:

    def test_generate_bucket_name(self):
        """It wrote to self.config, which the backend never set"""
        from lithops.storage.backends.swift.swift import StorageBackend
        config = {
            'auth_url': 'http://auth', 'user_id': 'ABCDEF123', 'project_id': 'p',
            'password': 'x', 'region': 'reg', 'token': 't', 'endpoint': 'http://swift',
        }
        backend = StorageBackend(config)
        assert backend.generate_bucket_name() == 'lithops-reg-abcdef'
        assert config['storage_bucket'] == 'lithops-reg-abcdef'

    def _token_response(self, url='https://swift.example/v1/AUTH_abc', region='RegionOne'):
        catalog = {
            'token': {
                'project': {'id': 'a' * 32},
                'catalog': [{
                    'type': 'object-store',
                    'name': 'swift',
                    'endpoints': [
                        {'interface': 'internal', 'region': region, 'url': 'http://internal'},
                        {'interface': 'public', 'region': region, 'region_id': region, 'url': url},
                    ],
                }],
            }
        }
        response = MagicMock(status_code=201, headers={'X-Subject-Token': 'tok'})
        response.json.return_value = catalog
        return response

    def test_keystone_scopes_a_project_by_name_and_keeps_https(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        response = self._token_response()
        with patch('lithops.storage.backends.swift.swift.requests.post', return_value=response) as posted:
            backend = StorageBackend({
                'auth_url': 'http://keystone:5000/v3/',
                'user_name': 'admin',
                'project_name': 'admin',
                'password': 'secret',
                'region': 'RegionOne',
            })
        assert backend.endpoint == 'https://swift.example/v1/AUTH_abc'
        sent = json.loads(posted.call_args.kwargs['data'])
        assert posted.call_args.args[0] == 'http://keystone:5000/v3/auth/tokens'
        assert sent['auth']['scope']['project'] == {
            'name': 'admin', 'domain': {'name': 'Default'},
        }
        assert sent['auth']['identity']['password']['user']['name'] == 'admin'
        assert 'id' not in sent['auth']['scope']['project']

    def test_keystone_scopes_an_id_without_a_domain(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        user_id = 'f' * 32
        project_id = 'a' * 32
        with patch(
            'lithops.storage.backends.swift.swift.requests.post',
            return_value=self._token_response('http://0.0.0.0:8080/v1/AUTH_%(project_id)s'),
        ) as posted:
            backend = StorageBackend({
                'auth_url': 'http://127.0.0.1:5000',
                'user_id': user_id,
                'project_id': project_id,
                'password': 'secret',
                'region': 'RegionOne',
            })
        sent = json.loads(posted.call_args.kwargs['data'])
        assert sent['auth']['identity']['password']['user'] == {
            'id': user_id, 'password': 'secret',
        }
        assert sent['auth']['scope']['project'] == {'id': project_id}
        assert backend.endpoint == f'http://127.0.0.1:8080/v1/AUTH_{project_id}'

    def test_an_unknown_region_names_the_known_ones(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        with patch(
            'lithops.storage.backends.swift.swift.requests.post',
            return_value=self._token_response(),
        ):
            with pytest.raises(Exception, match='region \'nope\''):
                StorageBackend({
                    'auth_url': 'http://keystone:5000',
                    'user_name': 'admin',
                    'project_name': 'admin',
                    'password': 'secret',
                    'region': 'nope',
                })

    def test_keystone_error_message_is_raised(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        response = MagicMock(status_code=401, text='no')
        response.json.return_value = {'error': {'message': 'The request you have made requires authentication.'}}
        with patch('lithops.storage.backends.swift.swift.requests.post', return_value=response):
            with pytest.raises(Exception, match='401 - The request you have made requires authentication'):
                StorageBackend({
                    'auth_url': 'http://keystone:5000',
                    'user_name': 'admin',
                    'project_name': 'admin',
                    'password': 'secret',
                    'region': 'RegionOne',
                })

    def test_create_bucket_accepts_an_existing_container(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://swift/v1/AUTH_x'
        backend.session = MagicMock()
        backend.session.put.return_value.status_code = 202
        backend.create_bucket('lithops')
        assert backend.session.put.call_args.args[0] == 'http://swift/v1/AUTH_x/lithops'
        backend.session.put.return_value.status_code = 500
        with pytest.raises(Exception, match='PUT container lithops failed'):
            backend.create_bucket('lithops')

    def test_get_object_missing_key(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://swift'
        backend.token = 't'
        backend.session = MagicMock()
        backend.session.get.return_value.status_code = 404
        with pytest.raises(StorageNoSuchKeyError, match='/b/k'):
            backend.get_object('b', 'k')

    def test_list_errors_propagate(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://swift'
        backend.session = MagicMock()
        page = [{'name': 'p/a', 'bytes': 1}, {'name': 'p/b', 'bytes': 2}]
        backend.session.get.return_value.status_code = 200
        backend.session.get.return_value.content = b'page'
        backend.session.get.return_value.json.side_effect = [page, []]
        assert backend.list_keys('b', 'p/') == ['p/a', 'p/b']
        backend.session.get.side_effect = ValueError('boom')
        with pytest.raises(ValueError, match='boom'):
            backend.list_keys('b', 'p/')

    @staticmethod
    def _listing_backend():
        from lithops.storage.backends.swift.swift import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://swift'
        backend.session = MagicMock()
        backend.session.get.return_value.status_code = 200
        backend.session.get.return_value.json.side_effect = [[
            {'name': f'p/{n}', 'bytes': size, 'hash': 'h', 'content_type': 'text/csv',
             'last_modified': '2024-01-01T00:00:00.000000'}
            for n, size in [('a.csv', 3), ('b.txt', 5)]
        ], []]
        return backend

    def test_list_objects_keys_and_sizes(self):
        """It returned the raw Swift entries, with 'name' and 'bytes'"""
        backend = self._listing_backend()
        assert backend.list_objects('b', 'p/') == [{'Key': 'p/a.csv', 'Size': 3}, {'Key': 'p/b.txt', 'Size': 5}]
        assert backend.session.get.call_args.args[0] == 'http://swift/b'
        assert backend.session.get.call_args.kwargs['params']['prefix'] == 'p/'

    def test_list_objects_pages_past_the_listing_limit(self):
        """Only the first page, at most 10,000 objects by default, was returned"""
        backend = self._listing_backend()
        pages = [[{'name': f'k{i}', 'bytes': 1}] for i in range(3)] + [[]]
        backend.session.get.return_value.json.side_effect = pages
        assert [o['Key'] for o in backend.list_objects('b')] == ['k0', 'k1', 'k2']
        # One request per page, the last one past the final name
        assert backend.session.get.call_count == 4
        assert backend.session.get.call_args.kwargs['params']['marker'] == 'k2'

    def test_list_objects_ends_at_an_empty_listing_with_no_body(self):
        """Some Swift versions answer the request past the last page with a 204 and no body"""
        backend = self._listing_backend()
        first, empty = MagicMock(status_code=200), MagicMock(status_code=204, content=b'')
        first.json.return_value = [{'name': 'k0', 'bytes': 1}]
        empty.json.side_effect = ValueError('no JSON body')
        backend.session.get.side_effect = [first, empty]
        assert backend.list_objects('b') == [{'Key': 'k0', 'Size': 1}]

    def test_list_objects_of_a_missing_bucket(self):
        backend = self._listing_backend()
        backend.session.get.return_value.status_code = 404
        with pytest.raises(StorageNoSuchKeyError):
            backend.list_objects('b', 'p/')

    def test_list_objects_does_not_treat_an_empty_error_as_the_end(self):
        backend = self._listing_backend()
        backend.session.get.return_value.status_code = 500
        backend.session.get.return_value.content = b''
        with pytest.raises(Exception, match='500 listing'):
            backend.list_objects('b')

    def test_put_object_raises_on_failure(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://swift'
        backend.session = MagicMock()
        backend.session.put.return_value.status_code = 500
        with pytest.raises(Exception, match='PUT k failed'):
            backend.put_object('b', 'k', b'data')
        backend.session.put.side_effect = ConnectionError('down')
        with pytest.raises(ConnectionError):
            backend.put_object('b', 'k', b'data')

    def test_get_and_head_keep_non_404_errors(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://swift'
        backend.token = 't'
        backend.session = MagicMock()
        backend.session.get.return_value.status_code = 503
        with pytest.raises(Exception, match='503'):
            backend.get_object('b', 'k')
        backend.session.head.return_value.status_code = 503
        with pytest.raises(Exception, match='503'):
            backend.head_object('b', 'k')

    def test_head_bucket(self):
        from lithops.storage.backends.swift.swift import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://swift'
        backend.session = MagicMock()
        backend.session.head.return_value.status_code = 204
        backend.session.head.return_value.headers = {'X-Container-Object-Count': '1'}
        assert backend.head_bucket('b')['X-Container-Object-Count'] == '1'
        backend.session.head.return_value.status_code = 404
        with pytest.raises(StorageNoSuchKeyError):
            backend.head_bucket('missing')

    def test_list_objects_match_pattern(self):
        """The glob pattern failed on the raw entries, which have no 'Key'"""
        storage = _bare_storage('swift')
        storage.storage_handler = self._listing_backend()
        assert storage.list_objects('b', 'p/', 'p/*.csv') == [{'Key': 'p/a.csv', 'Size': 3}]


class TestInfinispanBackendListing:

    @pytest.fixture
    def backend(self):
        from lithops.storage.backends.infinispan import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://ispn'
        backend.auth = None
        backend.infinispan_client = MagicMock()
        backend.infinispan_client.get.return_value.content = json.dumps(
            ['p/a', '', 'p/bb', 'q/c']
        ).encode()
        values = {'p/a': b'1', 'p/bb': b'22', 'q/c': b'333'}

        def get_object(bucket, key, stream=False, extra_get_args={}):
            if key not in values:
                raise StorageNoSuchKeyError(bucket, key)
            return values[key]

        backend.get_object = get_object
        return backend

    def test_list_keys(self, backend):
        assert backend.list_keys('b') == ['p/a', 'p/bb', 'q/c']
        assert backend.list_keys('b', 'p/') == ['p/a', 'p/bb']
        assert backend.list_keys('b', 'x') == []
        backend.infinispan_client.get.assert_called_with('http://ispn/rest/v2/caches/b?action=keys', auth=None)

    def test_list_objects(self, backend):
        assert backend.list_objects('b', 'p/') == [{'Key': 'p/a', 'Size': 1}, {'Key': 'p/bb', 'Size': 2}]
        assert backend.list_objects('b', 'x') == []

    def test_list_objects_skips_keys_gone_since_listed(self, backend):
        backend.infinispan_client.get.return_value.content = b'["p/a", "p/gone"]'
        assert backend.list_objects('b') == [{'Key': 'p/a', 'Size': 1}]

    def test_get_object_range_and_head_bucket(self):
        from lithops.storage.backends.infinispan import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://ispn'
        backend.auth = None
        backend.headers = {}
        backend.infinispan_client = MagicMock()
        backend.infinispan_client.get.return_value = MagicMock(
            status_code=200, content=b'abcdefghij'
        )
        assert backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=2-5'}) == b'cdef'
        assert backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=-3'}) == b'hij'
        backend.infinispan_client.head.return_value = MagicMock(status_code=404)
        with pytest.raises(StorageNoSuchKeyError):
            backend.head_bucket('b')
        backend.infinispan_client.head.return_value = MagicMock(status_code=200)
        assert backend.head_bucket('b')['ResponseMetadata']['HTTPStatusCode'] == 200

    def test_put_object_raises_on_http_error(self):
        import requests
        from lithops.storage.backends.infinispan import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.endpoint = 'http://ispn'
        backend.auth = None
        backend.headers = {}
        backend.infinispan_client = MagicMock()
        backend.infinispan_client.put.return_value.raise_for_status.side_effect = (
            requests.HTTPError('500')
        )
        with pytest.raises(requests.HTTPError):
            backend.put_object('b', 'k', b'data')


class TestRedisBackend:

    def _backend(self):
        pytest.importorskip('redis')
        from lithops.storage.backends.redis import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend._client = MagicMock()
        return backend

    def test_range_read_distinguishes_a_missing_key(self):
        backend = self._backend()
        pipe = backend._client.pipeline.return_value
        pipe.execute.return_value = (True, b'cdef')
        assert backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=2-5'}) == b'cdef'
        pipe.getrange.assert_called_with('b/k', 2, 5)
        pipe.execute.return_value = (False, b'')
        with pytest.raises(StorageNoSuchKeyError):
            backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=0-1'})

    def test_open_ended_and_suffix_ranges(self):
        backend = self._backend()
        pipe = backend._client.pipeline.return_value
        pipe.execute.return_value = (True, b'cdef')
        backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=2-'})
        pipe.getrange.assert_called_with('b/k', 2, -1)
        backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=-3'})
        pipe.getrange.assert_called_with('b/k', -3, -1)

    def test_head_bucket(self):
        backend = self._backend()
        backend._client.exists.return_value = 0
        with pytest.raises(StorageNoSuchKeyError):
            backend.head_bucket('b')
        backend._client.exists.return_value = 1
        assert backend.head_bucket('b')['ResponseMetadata']['HTTPStatusCode'] == 200


class TestCloudBackendRanges:
    """Open ranges work, and the caller's extra_get_args is not modified"""

    def test_gcp_storage(self):
        pytest.importorskip('google.cloud.storage')
        from lithops.storage.backends.gcp_storage import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.client = MagicMock()
        blob = backend.client.get_bucket.return_value.blob.return_value
        blob.size = 10
        backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=4-'})
        blob.download_as_bytes.assert_called_with(start=4, end=None)
        backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=-3'})
        blob.download_as_bytes.assert_called_with(start=7, end=None)

    def test_azure_storage(self):
        pytest.importorskip('azure.storage.blob')
        from lithops.storage.backends.azure_storage import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.blob_client = MagicMock()
        container = backend.blob_client.get_container_client.return_value
        container.get_blob_client.return_value.get_blob_properties.return_value.size = 10
        args = {'Range': 'bytes=2-5'}
        backend.get_object('b', 'k', extra_get_args=args)
        container.download_blob.assert_called_with('k', offset=2, length=4)
        assert args == {'Range': 'bytes=2-5'}
        backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=4-'})
        container.download_blob.assert_called_with('k', offset=4, length=None)
        backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=-3'})
        container.download_blob.assert_called_with('k', offset=7, length=None)

    def test_aliyun_oss(self):
        pytest.importorskip('oss2')
        from lithops.storage.backends.aliyun_oss import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        bucket = MagicMock()
        bucket.head_object.return_value.content_length = 10
        backend._connect_bucket = lambda name: bucket
        args = {'Range': 'bytes=2-50'}
        backend.get_object('b', 'k', extra_get_args=args)
        bucket.get_object.assert_called_with(key='k', byte_range=(2, 9))
        assert args == {'Range': 'bytes=2-50'}
        backend.get_object('b', 'k', extra_get_args={'Range': 'bytes=-3'})
        bucket.get_object.assert_called_with(key='k', byte_range=(None, 3))


class TestCloudBackendListing:
    """Listings go past the first page of 1000 objects"""

    def test_aliyun_oss(self):
        pytest.importorskip('oss2')
        from lithops.storage.backends.aliyun_oss import StorageBackend, aliyun_oss
        backend = StorageBackend.__new__(StorageBackend)
        backend._connect_bucket = lambda name: MagicMock()
        objects = [SimpleNamespace(key=f'k{i}', size=i) for i in range(1500)]
        with patch.object(aliyun_oss.oss2, 'ObjectIterator', return_value=iter(objects)):
            assert len(backend.list_objects('b', 'p')) == 1500
        with patch.object(aliyun_oss.oss2, 'ObjectIterator', return_value=iter(objects)):
            assert len(backend.list_keys('b', 'p')) == 1500

    def test_oracle_oss(self):
        pytest.importorskip('oci')
        from lithops.storage.backends.oracle_oss import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.namespace = 'ns'
        backend.os_client = MagicMock()

        def page(names, next_start):
            objects = [SimpleNamespace(name=n, size=1) for n in names]
            return SimpleNamespace(data=SimpleNamespace(objects=objects, next_start_with=next_start))

        backend.os_client.list_objects.side_effect = [page(['a', 'b'], 'c'), page(['c'], None)]
        assert [o['Key'] for o in backend.list_objects('bkt', 'p')] == ['a', 'b', 'c']
        assert backend.os_client.list_objects.call_args.kwargs['start'] == 'c'

    def test_oracle_list_keeps_non_404_errors(self):
        oci = pytest.importorskip('oci')
        from lithops.storage.backends.oracle_oss import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.namespace = 'ns'
        backend.os_client = MagicMock()
        backend.os_client.list_objects.side_effect = oci.exceptions.ServiceError(
            500, 'InternalError', {}, 'down'
        )
        with pytest.raises(oci.exceptions.ServiceError):
            backend.list_objects('bkt', 'p')
        backend.os_client.list_objects.side_effect = oci.exceptions.ServiceError(
            404, 'BucketNotFound', {}, 'missing'
        )
        with pytest.raises(StorageNoSuchKeyError):
            backend.list_objects('bkt', 'p')


class TestS3MissingBucket:

    @staticmethod
    def _cases():
        found = []
        try:
            import botocore
            from lithops.storage.backends.aws_s3 import StorageBackend as AWS
            found.append((AWS, botocore.exceptions.ClientError))
        except ImportError:
            pass
        try:
            import ibm_botocore
            from lithops.storage.backends.ibm_cos import StorageBackend as IBM
            found.append((IBM, ibm_botocore.exceptions.ClientError))
        except ImportError:
            pass
        try:
            import botocore
            from lithops.storage.backends.ceph import StorageBackend as Ceph
            found.append((Ceph, botocore.exceptions.ClientError))
        except ImportError:
            pass
        try:
            import botocore
            from lithops.storage.backends.minio import StorageBackend as Minio
            found.append((Minio, botocore.exceptions.ClientError))
        except ImportError:
            pass
        if not found:
            pytest.skip('no S3-compatible storage backend is installed')
        return found

    def test_list_maps_no_such_bucket_and_keeps_other_errors(self):
        for cls, error in self._cases():
            backend = cls.__new__(cls)
            client = MagicMock()
            backend.s3_client = client
            backend.cos_client = client

            def boom(code, error=error):
                client.get_paginator.return_value.paginate.side_effect = error(
                    {'Error': {'Code': code, 'Message': code}}, 'ListObjectsV2'
                )

            boom('NoSuchBucket')
            with pytest.raises(StorageNoSuchKeyError):
                backend.list_objects('missing')
            boom('NoSuchBucket')
            with pytest.raises(StorageNoSuchKeyError):
                backend.list_keys('missing')
            boom('AccessDenied')
            with pytest.raises(error):
                backend.list_objects('missing')


class TestAzureAndGcpMissingObjects:

    def test_azure_head_object_maps_a_missing_blob(self):
        pytest.importorskip('azure.storage.blob')
        from azure.core.exceptions import ResourceNotFoundError
        from lithops.storage.backends.azure_storage import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.blob_client = MagicMock()
        blob = backend.blob_client.get_container_client.return_value.get_blob_client.return_value
        blob.get_blob_properties.side_effect = ResourceNotFoundError('gone')
        with pytest.raises(StorageNoSuchKeyError):
            backend.head_object('b', 'k')
        blob.get_blob_properties.side_effect = ConnectionError('down')
        with pytest.raises(ConnectionError):
            backend.head_object('b', 'k')

    def test_gcp_head_bucket_maps_not_found(self):
        pytest.importorskip('google.cloud.storage')
        from google.api_core import exceptions as google_exceptions
        from lithops.storage.backends.gcp_storage import StorageBackend
        backend = StorageBackend.__new__(StorageBackend)
        backend.client = MagicMock()
        backend.client.get_bucket.side_effect = google_exceptions.NotFound('gone')
        with pytest.raises(StorageNoSuchKeyError):
            backend.head_bucket('missing')
        backend.client.get_bucket.side_effect = google_exceptions.Forbidden('no')
        with pytest.raises(google_exceptions.Forbidden):
            backend.head_bucket('missing')


class TestStorageListObjectsGlob:
    """
    Storage.list_objects matches the glob pattern itself, on every backend:
    it used to be passed to the backend, and all but aws_s3 and ibm_cos
    ignored it
    """

    @pytest.fixture
    def storage(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'lithops.storage.backends.localhost.localhost.LITHOPS_TEMP_DIR',
            str(tmp_path),
        )
        storage = _bare_storage()
        storage.storage_handler = LocalhostStorageBackend({})
        for key in ['dir/a.csv', 'dir/b.txt', 'dir/sub/c.csv', 'dir2/d.csv']:
            storage.put_object('b', key, b'x')
        return storage

    @pytest.mark.parametrize('prefix, pattern, keys', [
        ('dir/', None, ['dir/a.csv', 'dir/b.txt', 'dir/sub/c.csv']),
        ('dir', None, ['dir/a.csv', 'dir/b.txt', 'dir/sub/c.csv', 'dir2/d.csv']),
        ('dir/', 'dir/*.csv', ['dir/a.csv']),
        ('dir', 'dir*/*.csv', ['dir/a.csv', 'dir2/d.csv']),
        (None, '**/*.csv', ['dir/a.csv', 'dir/sub/c.csv', 'dir2/d.csv']),
        ('dir/', 'dir/?.txt', ['dir/b.txt']),
        ('dir/', 'other/*', []),
    ])
    def test_match_pattern(self, storage, prefix, pattern, keys):
        objects = storage.list_objects('b', prefix, pattern)
        assert sorted(o['Key'] for o in objects) == keys
        assert all(o['Size'] == 1 for o in objects)

    def test_match_pattern_on_windows(self, monkeypatch):
        """
        Keys are split on '/' on Windows too: the separator used to be
        replaced by the platform one, which split keys holding a '\\'
        """
        monkeypatch.setattr('os.sep', '\\')
        storage = _bare_storage()
        storage.storage_handler.list_objects.return_value = [
            {'Key': 'dir/a\\b.csv', 'Size': 1}, {'Key': 'dir/sub/', 'Size': 0}, {'Key': 'dir/sub/c.csv', 'Size': 1},
        ]
        assert [o['Key'] for o in storage.list_objects('b', 'dir/', 'dir/*')] == ['dir/a\\b.csv', 'dir/sub/']
        assert [o['Key'] for o in storage.list_objects('b', 'dir/', 'dir/**/*.csv')] == [
            'dir/a\\b.csv', 'dir/sub/c.csv',
        ]

    def test_backend_gets_no_pattern(self):
        storage = _bare_storage()
        storage.storage_handler.list_objects.return_value = [{'Key': 'a/b', 'Size': 1}, {'Key': 'a/c', 'Size': 1}]
        assert storage.list_objects('bkt', 'a/', 'a/b') == [{'Key': 'a/b', 'Size': 1}]
        storage.storage_handler.list_objects.assert_called_once_with('bkt', 'a/')

    @pytest.mark.parametrize('module, client_attr', [('aws_s3', 's3_client'), ('ibm_cos', 'cos_client')])
    def test_s3_backends_list_every_page(self, module, client_attr):
        pytest.importorskip('boto3' if module == 'aws_s3' else 'ibm_boto3')
        import importlib
        backend_cls = importlib.import_module(f'lithops.storage.backends.{module}').StorageBackend
        backend = backend_cls.__new__(backend_cls)
        client = MagicMock()
        setattr(backend, client_attr, client)
        client.get_paginator.return_value.paginate.return_value = [
            {'Contents': [{'Key': 'p/a', 'Size': 1}]}, {}, {'Contents': [{'Key': 'p/b', 'Size': 2}]},
        ]
        assert [o['Key'] for o in backend.list_objects('bkt', 'p/')] == ['p/a', 'p/b']
        client.get_paginator.return_value.paginate.assert_called_once_with(Bucket='bkt', Prefix='p/')


class TestStorageCloudObjects:

    def test_put_cloudobject_uses_temp_prefix_and_hex_id(self, monkeypatch):
        monkeypatch.delenv(SESSION_ID_ENV, raising=False)
        storage = _bare_storage()
        cloudobject = storage.put_cloudobject(b'data')
        key = storage.storage_handler.put_object.call_args[0][1]
        assert key.startswith(TEMP_PREFIX + '/')
        assert 'cloudobject_' in key
        assert cloudobject.backend == 'localhost'
        assert cloudobject.bucket == 'storage'

    def test_put_cloudobject_prefixes_session_id(self, monkeypatch):
        monkeypatch.setenv(SESSION_ID_ENV, 'sess')
        storage = _bare_storage()
        cloudobject = storage.put_cloudobject(b'data')
        key = storage.storage_handler.put_object.call_args[0][1]
        assert '/sess/cloudobject_' in key
        assert cloudobject.key == key

    def test_get_and_delete_cloudobject_reject_other_backend(self):
        storage = _bare_storage()
        other = CloudObject('s3', 'b', 'k')
        with pytest.raises(Exception, match='Invalid Storage backend'):
            storage.get_cloudobject(other)
        with pytest.raises(Exception, match='Invalid Storage backend'):
            storage.delete_cloudobject(other)
        own = CloudObject('localhost', 'b', 'k')
        storage.get_cloudobject(own, stream=True)
        storage.storage_handler.get_object.assert_called_once_with(
            'b', 'k', stream=True
        )

    def test_delete_cloudobjects_groups_by_bucket(self):
        storage = _bare_storage()
        storage.delete_cloudobjects([
            CloudObject('localhost', 'b1', 'k1'),
            CloudObject('localhost', 'b2', 'k2'),
            CloudObject('localhost', 'b1', 'k3'),
        ])
        calls = storage.storage_handler.delete_objects.call_args_list
        deleted = {call[0][0]: set(call[0][1]) for call in calls}
        assert deleted == {'b1': {'k1', 'k3'}, 'b2': {'k2'}}

    def test_delete_cloudobjects_rejects_other_backend(self):
        storage = _bare_storage()
        with pytest.raises(Exception, match='Invalid Storage backend'):
            storage.delete_cloudobjects([CloudObject('s3', 'b', 'k')])

    def test_create_bucket_skips_when_backend_has_no_method(self):
        storage = _bare_storage()
        del storage.storage_handler.create_bucket
        assert storage.create_bucket('b') is None

    def test_get_object_keeps_mutable_extra_get_args_default(self):
        assert Storage.get_object.__defaults__[-1] == {}


class TestInternalStorage:

    def test_missing_bucket_raises(self):
        storage = MagicMock()
        storage.backend = 'localhost'
        storage.bucket = None
        with patch('lithops.storage.storage.Storage', return_value=storage):
            with pytest.raises(Exception, match='storage_bucket'):
                InternalStorage({'backend': 'localhost'})

    def test_get_job_status_parses_init_and_status_keys(self):
        internal = _bare_internal()
        keys = [
            create_init_key('sess-0', 'M000', '00000', 'act1'),
            create_status_key('sess-0', 'M000', '00001'),
            f'{JOBS_PREFIX}/ignored.txt',
        ]
        internal.storage.list_keys.return_value = keys
        running, done = internal.get_job_status('sess-0')
        assert (('sess-0', 'M000', '00000'), 'act1') in running
        assert ('sess-0', 'M000', '00001') in done
        internal.storage.list_keys.assert_called_once_with(
            'storage', f'{JOBS_PREFIX}/sess-0'
        )

    def test_get_job_status_lists_per_job_when_job_ids_given(self):
        internal = _bare_internal()
        keys = [
            create_init_key('sess-0', 'M000', '00000', 'act1'),
            create_status_key('sess-0', 'M000', '00001'),
        ]
        internal.storage.list_keys.return_value = keys
        running, done = internal.get_job_status('sess-0', job_ids=['M000'])
        assert (('sess-0', 'M000', '00000'), 'act1') in running
        assert ('sess-0', 'M000', '00001') in done
        internal.storage.list_keys.assert_called_once_with(
            'storage', f'{JOBS_PREFIX}/{create_job_key("sess-0", "M000")}'
        )

    def test_get_job_status_does_not_list_when_job_ids_is_empty(self):
        """
        After wait() drops the finished futures the monitor stays up with
        no jobs. Falling through to the executor prefix would LIST every
        leftover job and the function pickle on every poll
        """
        internal = _bare_internal()
        running, done = internal.get_job_status('sess-0', job_ids=set())
        assert running == set()
        assert done == set()
        internal.storage.list_keys.assert_not_called()

    def test_get_call_status_and_output_missing_are_none(self):
        internal = _bare_internal()
        internal.storage.get_object.side_effect = StorageNoSuchKeyError('b', 'k')
        assert internal.get_call_status('e', 'j', 'c') is None
        assert internal.get_call_output('e', 'j', 'c') is None

    def test_get_call_status_decodes_ascii_json(self):
        internal = _bare_internal()
        internal.storage.get_object.return_value = b'{"ok": true}'
        assert internal.get_call_status('e', 'M000', '00000') == {'ok': True}

    def test_get_call_status_reads_a_half_written_status_as_missing(self):
        """
        The localhost backend fills an object after truncating it, so a poll
        can read an empty one. That is a status not written yet, and used to
        come back as a JSONDecodeError that failed the call
        """
        internal = _bare_internal()
        internal.storage.get_object.return_value = b''
        assert internal.get_call_status('e', 'M000', '00000') is None

    def test_runtime_meta_memory_cache(self):
        RUNTIME_META_CACHE.clear()
        internal = _bare_internal()
        cache_key = f'{RUNTIMES_PREFIX}/rk.meta.json'
        RUNTIME_META_CACHE[cache_key] = {'cached': True}
        assert internal.get_runtime_meta('rk') == {'cached': True}
        internal.storage.get_object.assert_not_called()
        RUNTIME_META_CACHE.clear()

    def test_runtime_meta_disk_then_storage_then_missing(self, tmp_path, monkeypatch):
        RUNTIME_META_CACHE.clear()
        monkeypatch.setattr('lithops.storage.storage.CACHE_DIR', str(tmp_path))
        monkeypatch.setattr(
            'lithops.storage.storage.is_lithops_worker', lambda: False
        )
        internal = _bare_internal()
        meta_dir = tmp_path / RUNTIMES_PREFIX
        meta_dir.mkdir()
        (meta_dir / 'rk.meta.json').write_text(json.dumps({'from': 'disk'}))
        assert internal.get_runtime_meta('rk') == {'from': 'disk'}

        RUNTIME_META_CACHE.clear()
        (meta_dir / 'rk.meta.json').unlink()
        internal.storage.get_object.return_value = b'{"from": "storage"}'
        assert internal.get_runtime_meta('rk') == {'from': 'storage'}
        assert (meta_dir / 'rk.meta.json').exists()

        RUNTIME_META_CACHE.clear()
        (meta_dir / 'rk.meta.json').unlink()
        internal.storage.get_object.side_effect = StorageNoSuchKeyError('b', 'k')
        assert internal.get_runtime_meta('rk') is None
        RUNTIME_META_CACHE.clear()

    def test_put_and_delete_runtime_meta(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.storage.storage.CACHE_DIR', str(tmp_path))
        monkeypatch.setattr(
            'lithops.storage.storage.is_lithops_worker', lambda: False
        )
        internal = _bare_internal()
        internal.put_runtime_meta('rk', {'a': 1})
        obj_key = f'{RUNTIMES_PREFIX}/rk.meta.json'
        internal.storage.put_object.assert_called_once()
        assert internal.storage.put_object.call_args[0][1] == obj_key
        local = tmp_path / RUNTIMES_PREFIX / 'rk.meta.json'
        assert json.loads(local.read_text()) == {'a': 1}

        internal.delete_runtime_meta('rk')
        assert not local.exists()
        internal.storage.delete_object.assert_called_once_with('storage', obj_key)


class TestCloudProxy:

    def test_remove_lithops_keys(self):
        keys = [
            f'{JOBS_PREFIX}/a',
            'user/file',
            f'{TEMP_PREFIX}/x',
            f'{RUNTIMES_PREFIX}/r',
            'other',
        ]
        assert remove_lithops_keys(keys) == ['user/file', 'other']

    def test_listdir_and_path_helpers(self):
        fake = FakeCloudStorage(keys=[
            'dir/a.txt',
            'dir/sub/b.txt',
            f'{JOBS_PREFIX}/hidden',
            'dir/c.txt',
        ])
        proxy = CloudFileProxy(fake)
        listed = proxy.listdir('dir', suffix_dirs=True)
        assert 'a.txt' in listed
        assert 'c.txt' in listed
        assert 'sub/' in listed
        assert not any(name.startswith(JOBS_PREFIX) for name in listed)

        assert proxy.path.isfile('dir/a.txt') is True
        assert proxy.path.isdir('dir') is True
        assert proxy.path.exists('dir/a.txt') is True
        assert proxy.path.exists('missing') is False

    def test_exists_ignores_lithops_keys(self):
        fake = FakeCloudStorage(keys=[f'{JOBS_PREFIX}/hidden'])
        path = _path(fake)
        assert path.isdir(JOBS_PREFIX) is False
        assert path.exists(JOBS_PREFIX) is False
        assert path.exists(f'{JOBS_PREFIX}/hidden') is False

    def test_exists_strips_the_leading_slash_like_isfile(self):
        # isfile and isdir dropped the leading slash and exists did not, so
        # '/k' was a file that did not exist
        fake = FakeCloudStorage(keys=['k', 'dir/a'])
        path = _path(fake)
        assert path.isfile('/k') is True
        assert path.exists('/k') is True
        assert path.exists('/dir') is True
        assert path.exists('/di') is False

    def test_the_empty_path_does_not_exist(self):
        # As os.path.exists(''); stripped to the key '', it matched any key
        path = _path(FakeCloudStorage(keys=['k']))
        assert path.exists('') is False
        assert path.isfile('') is False

    def test_isfile_is_an_exact_key_match(self):
        # A sibling sharing the prefix made the key count as a directory
        fake = FakeCloudStorage(keys=['foo', 'foo.bak', 'bar/x'])
        path = _path(fake)
        assert path.isfile('foo') is True
        assert path.isfile('/foo') is True
        assert path.isfile('fo') is False
        assert path.isfile('bar') is False

    def test_listdir_of_an_absolute_path_stays_in_that_directory(self):
        # '/foo' asked for the prefix 'foo', which also matches 'foobar/'
        fake = FakeCloudStorage(keys=['foo/a', 'foobar/b'])
        proxy = CloudFileProxy(fake)
        assert proxy.listdir('foo') == ['a']
        assert proxy.listdir('/foo') == ['a']
        assert proxy.listdir('/foo/') == ['a']

    def test_open_and_remove_strip_the_leading_slash(self):
        fake = FakeCloudStorage(data={'k': b'v'})
        proxy = CloudFileProxy(fake)
        assert proxy.open('/k', 'rb').read() == b'v'
        with proxy.open('/out', 'wb') as f:
            f.write(b'x')
        assert fake.puts[-1] == ('out', b'x')
        proxy.remove('/k')
        assert fake.deleted == ['k']

    def test_delayed_buffers_close_twice_uploads_once(self):
        # A second close, as after a with block, read the closed buffer and
        # raised ValueError
        fake = FakeCloudStorage()
        with cloud_open('t', 'w', cloud_storage=fake) as f:
            f.write('hello')
        f.close()
        b = cloud_open('b', 'wb', cloud_storage=fake)
        b.write(b'hi')
        b.close()
        b.close()
        assert fake.puts == [('t', 'hello'), ('b', b'hi')]

    @pytest.mark.parametrize('mode', ['r+', 'r+b', 'rb+'])
    def test_open_read_plus_writes_back_on_close(self, mode):
        # 'r+' returned a plain buffer, so the writes were silently dropped
        conv = (lambda s: s.encode()) if 'b' in mode else str
        fake = FakeCloudStorage(data={'k': b'abc'})
        with cloud_open('k', mode, cloud_storage=fake) as f:
            assert f.read(1) == conv('a')
            f.seek(0)
            f.write(conv('X'))
        assert fake.data['k'] == conv('Xbc')

    def test_listdir_of_the_root_matches_the_slash_form(self):
        # The empty path is the default argument, and it used to ask for the
        # prefix '/', which no key can start with
        fake = FakeCloudStorage(keys=['top.txt', 'dir/inner.txt'])
        assert sorted(CloudFileProxy(fake).listdir('')) == ['dir', 'top.txt']
        assert sorted(CloudFileProxy(fake).listdir('/')) == ['dir', 'top.txt']

    def test_walk_yields_nothing_when_missing(self):
        # os.walk yields nothing for a path that is not there, and raising
        # StopIteration inside a generator only became a RuntimeError
        proxy = CloudFileProxy(FakeCloudStorage(keys=[]))
        assert list(proxy.walk('missing')) == []

    def test_walk_orders_and_prunes_like_os_walk(self):
        fake = FakeCloudStorage(keys=['a/x', 'a/b/y', 'a/b/c/z'])
        proxy = CloudFileProxy(fake)
        expected = [('a', ['b'], ['x']), ('a/b', ['c'], ['y']), ('a/b/c', [], ['z'])]
        assert list(proxy.walk('a')) == expected
        assert list(proxy.walk('a', topdown=False)) == expected[::-1]

        # Top-down, emptying dirs in place stops the walk going below, as in os.walk
        walked = []
        for top, dirs, _ in proxy.walk('a'):
            walked.append(top)
            dirs.clear()
        assert walked == ['a']

    def test_open_rejects_unsupported_mode(self):
        fake = FakeCloudStorage(data={'f.txt': b'hello'})
        with pytest.raises(ValueError, match='Unsupported mode'):
            cloud_open('f.txt', mode='a', cloud_storage=fake)

    def test_open_read_and_write_buffers(self):
        fake = FakeCloudStorage(data={'f.txt': b'hello'})
        text = cloud_open('f.txt', mode='r', cloud_storage=fake)
        assert text.read() == 'hello'
        binary = cloud_open('f.txt', mode='rb', cloud_storage=fake)
        assert binary.read() == b'hello'

        buf = cloud_open('out.txt', mode='w', cloud_storage=fake)
        buf.write('world')
        buf.close()
        assert fake.puts[-1] == ('out.txt', 'world')

        bbuf = cloud_open('out.bin', mode='wb', cloud_storage=fake)
        bbuf.write(b'xyz')
        bbuf.close()
        assert fake.puts[-1] == ('out.bin', b'xyz')

    def test_delayed_buffers_run_action_on_close(self):
        seen = []
        DelayedBytesBuffer(seen.append, b'ab').close()
        DelayedStringBuffer(seen.append, 'cd').close()
        DelayedBytesBuffer(seen.append, initial_bytes=b'ef').close()
        DelayedStringBuffer(seen.append, initial_value='gh').close()
        DelayedBytesBuffer(seen.append).close()
        DelayedStringBuffer(seen.append).close()
        assert seen == [b'ab', 'cd', b'ef', 'gh', b'', '']

    def test_remove_delegates_and_mkdir_is_noop(self):
        fake = FakeCloudStorage()
        proxy = CloudFileProxy(fake)
        proxy.remove('x')
        assert fake.deleted == ['x']
        proxy.mkdir('whatever')
        proxy.makedirs('whatever')

    def test_cloud_storage_config_branches(self):
        with patch.object(Storage, '__init__', return_value=None):
            raw = {'backend': 'localhost', 'localhost': {'storage_bucket': 'b'}}
            assert CloudStorage(raw)._config is raw
            extracted = {'backend': 'localhost', 'localhost': {'storage_bucket': 'x'}}
            with patch(
                'lithops.storage.cloud_proxy.extract_storage_config',
                return_value=extracted,
            ):
                lithops_cfg = {'lithops': {}, 'localhost': {}}
                assert CloudStorage(lithops_cfg)._config is extracted

    def test_cloud_storage_pickle_roundtrip_uses_config(self):
        cfg = {'backend': 'localhost', 'localhost': {'storage_bucket': 'storage'}}
        with patch.object(Storage, '__init__', return_value=None):
            original = CloudStorage(cfg)
            dumped = pickle.dumps(original)
        with patch.object(Storage, '__init__', return_value=None) as init:
            loaded = pickle.loads(dumped)
        assert loaded._config == cfg
        init.assert_called()


class TestStorageInit:

    def test_a_backend_that_fails_is_reraised_with_one_traceback(self):
        # The error was logged with its traceback and then raised, so the
        # caller printed the same traceback twice
        config = {'backend': 'no_such_backend', 'no_such_backend': {}}
        with patch('lithops.storage.storage.logger') as logger:
            with pytest.raises(ModuleNotFoundError):
                Storage(storage_config=config)
        logger.error.assert_called_once()
        assert "'no_such_backend' storage backend" in logger.error.call_args.args[0]
        assert 'exc_info' not in logger.error.call_args.kwargs


class TestIbmCosConfig:

    @staticmethod
    def _load(backend, **ibm_cos):
        from lithops.storage.backends.ibm_cos.config import load_config
        config = {'lithops': {'backend': backend}, 'ibm_cos': {'service_instance_id': 'sid', **ibm_cos}}
        load_config(config)
        return config['ibm_cos']

    @pytest.mark.parametrize('backend, private_endpoint', [
        ('code_engine', 'https://s3.direct.eu-de.cloud-object-storage.appdomain.cloud'),
        ('ibm_vpc', 'https://s3.direct.eu-de.cloud-object-storage.appdomain.cloud'),
        ('localhost', None),
    ])
    def test_region_sets_the_endpoints_of_the_compute_backend(self, backend, private_endpoint):
        cos = self._load(backend, region='eu-de', private_endpoint='https://s3.private.x')
        assert cos['endpoint'] == 'https://s3.eu-de.cloud-object-storage.appdomain.cloud'
        assert cos.get('private_endpoint') == private_endpoint

    @pytest.mark.parametrize('backend, private_endpoint, error', [
        ('code_engine', None, 'You must provide the private_endpoint'),
        ('code_engine', 'https://s3.private.x', 'is not valid$'),
        ('ibm_vpc', 'https://s3.private.x', 'is not valid. You must use the "direct" endpoint$'),
        ('ibm_vpc', 's3.direct.x', 'Private Endpoint must start with http'),
    ])
    def test_private_endpoint_is_validated(self, backend, private_endpoint, error):
        extra = {'private_endpoint': private_endpoint} if private_endpoint else {}
        with pytest.raises(Exception, match=error):
            self._load(backend, endpoint='https://s3.eu-de.x', **extra)
