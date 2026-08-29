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
from unittest.mock import MagicMock, patch

import pytest

from lithops.constants import JOBS_PREFIX, RUNTIMES_PREFIX, TEMP_PREFIX
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


class TestStorageCloudObjects:

    def test_put_cloudobject_uses_temp_prefix_and_hex_id(self, monkeypatch):
        monkeypatch.delenv('__LITHOPS_SESSION_ID', raising=False)
        storage = _bare_storage()
        cloudobject = storage.put_cloudobject(b'data')
        key = storage.storage_handler.put_object.call_args[0][1]
        assert key.startswith(TEMP_PREFIX + '/')
        assert 'cloudobject_' in key
        assert cloudobject.backend == 'localhost'
        assert cloudobject.bucket == 'storage'

    def test_put_cloudobject_prefixes_session_id(self, monkeypatch):
        monkeypatch.setenv('__LITHOPS_SESSION_ID', 'sess')
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

    def test_get_call_status_and_output_missing_are_none(self):
        internal = _bare_internal()
        internal.storage.get_object.side_effect = StorageNoSuchKeyError('b', 'k')
        assert internal.get_call_status('e', 'j', 'c') is None
        assert internal.get_call_output('e', 'j', 'c') is None

    def test_get_call_status_decodes_ascii_json(self):
        internal = _bare_internal()
        internal.storage.get_object.return_value = b'{"ok": true}'
        assert internal.get_call_status('e', 'M000', '00000') == {'ok': True}

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

    def test_exists_keeps_leading_slash_on_list_prefix(self):
        fake = FakeCloudStorage()
        fake.list_bucket_keys = MagicMock(return_value=[])
        _path(fake).exists('/foo')
        fake.list_bucket_keys.assert_called_once_with(prefix='/foo')

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
        assert seen == [b'ab', 'cd']

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
