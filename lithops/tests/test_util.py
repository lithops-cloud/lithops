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
import pickle
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lithops.util.metrics import PrometheusExporter
from lithops.util.ssh_client import SSHClient, ssh_boot_status_message


class TestSshBootStatusMessage:

    def test_timeout(self):
        assert 'waiting for network' in ssh_boot_status_message(
            TimeoutError('timed out')
        )

    def test_connection_refused(self):
        assert 'starting SSH' in ssh_boot_status_message(
            OSError('Connection refused')
        )

    def test_banner(self):
        assert 'Configuring SSH' in ssh_boot_status_message(
            Exception('Error reading SSH protocol banner')
        )

    def test_fallback_to_str(self):
        assert ssh_boot_status_message(Exception('weird')) == 'weird'


class TestSSHClient:

    def test_expands_key_filename(self, tmp_path):
        key = tmp_path / 'id_rsa'
        key.write_text('k')
        creds = {'username': 'u', 'key_filename': str(key)}
        SSHClient('1.2.3.4', creds)
        assert creds['key_filename'] == str(key)

    def test_missing_key_falls_back_to_default(self, tmp_path):
        creds = {'username': 'u', 'key_filename': str(tmp_path / 'missing')}
        SSHClient('1.2.3.4', creds)
        assert creds['key_filename'] == os.path.expanduser('~/.ssh/id_rsa')

    def test_invalid_ip_raises(self):
        client = SSHClient('0.0.0.0', {})
        with pytest.raises(Exception, match='Invalid IP Address'):
            client.run_remote_command('true')

    def test_create_client_passes_key_filename(self, tmp_path):
        key = tmp_path / 'id_rsa'
        key.write_text('k')
        creds = {
            'username': 'ubuntu',
            'password': None,
            'key_filename': str(key),
        }
        client = SSHClient('10.0.0.1', creds)
        ssh = MagicMock()
        with patch('lithops.util.ssh_client.paramiko.SSHClient', return_value=ssh):
            client.create_client(timeout=5)
        kwargs = ssh.connect.call_args.kwargs
        assert kwargs['hostname'] == '10.0.0.1'
        assert kwargs['username'] == 'ubuntu'
        assert kwargs['key_filename'] == str(key)
        assert 'pkey' not in kwargs

    def test_run_remote_retries_on_exec_failure(self):
        client = SSHClient('10.0.0.1', {'username': 'u'})
        ssh = MagicMock()
        stdout = MagicMock()
        stdout.read.return_value = b'ok\n'
        stderr = MagicMock()
        stderr.read.return_value = b''
        ssh.exec_command.side_effect = [
            Exception('timeout'),
            (MagicMock(), stdout, stderr),
        ]
        with patch.object(client, 'create_client', return_value=ssh) as created:
            client.ssh_client = ssh
            out, err = client.run_remote_command('echo ok')
        assert created.call_count == 1
        assert out == 'ok'
        assert err == ''

    def test_download_creates_parent_dir(self, tmp_path):
        dest = tmp_path / 'nested' / 'file.txt'
        client = SSHClient('10.0.0.1', {})
        ftp = MagicMock()
        ssh = MagicMock()
        ssh.open_sftp.return_value = ftp
        client.ssh_client = ssh
        client.download_remote_file('/remote', str(dest))
        assert dest.parent.is_dir()
        ftp.get.assert_called_once_with('/remote', str(dest))
        ftp.close.assert_called_once()

    def test_sftp_closes_on_error(self):
        client = SSHClient('10.0.0.1', {})
        ftp = MagicMock()
        ftp.put.side_effect = OSError('fail')
        ssh = MagicMock()
        ssh.open_sftp.return_value = ftp
        client.ssh_client = ssh
        with pytest.raises(OSError):
            client.upload_local_file('/local', '/remote')
        ftp.close.assert_called_once()

    def test_upload_multiple_and_data(self):
        client = SSHClient('10.0.0.1', {})
        ftp = MagicMock()
        remote = MagicMock()
        ftp.open.return_value.__enter__.return_value = remote
        ssh = MagicMock()
        ssh.open_sftp.return_value = ftp
        client.ssh_client = ssh
        client.upload_multiple_local_files([('a', 'b'), ('c', 'd')])
        assert ftp.put.call_count == 2
        client.upload_data_to_file('hello', '/dst')
        remote.write.assert_called_once_with('hello')


class TestPrometheusExporter:

    def test_missing_session_id_does_not_raise(self, monkeypatch):
        monkeypatch.delenv('__LITHOPS_SESSION_ID', raising=False)
        exporter = PrometheusExporter(False, None)
        assert exporter.instance == 'lithops'
        exporter.send_metric('n', 1, type='gauge', labels=[])

    def test_instance_from_session_id(self, monkeypatch):
        monkeypatch.setenv('__LITHOPS_SESSION_ID', 'ek-j0-00000')
        exporter = PrometheusExporter(True, {'apigateway': 'http://prom'})
        assert exporter.instance == 'ek'

    def test_send_metric_posts_when_enabled(self, monkeypatch):
        monkeypatch.setenv('__LITHOPS_SESSION_ID', 'sid-1')
        exporter = PrometheusExporter(True, {'apigateway': 'http://prom'})
        with patch('lithops.util.metrics.requests.post') as post:
            exporter.send_metric(
                'function_start', 1.5, type='gauge',
                labels=[('job_id', 'j'), ('call_id', 'c')],
            )
        post.assert_called_once()
        url = post.call_args[0][0]
        assert url.startswith('http://prom/metrics/')
        assert 'job/lithops' in url
        assert 'function_start' in post.call_args.kwargs['data']

    def test_send_metric_swallows_post_errors(self, monkeypatch):
        monkeypatch.setenv('__LITHOPS_SESSION_ID', 'sid-1')
        exporter = PrometheusExporter(True, {'apigateway': 'http://prom'})
        with patch(
            'lithops.util.metrics.requests.post', side_effect=OSError('down')
        ):
            exporter.send_metric('n', 1, type='gauge', labels=[])


class TestIBMTokenManager:
    """
    ibm_token_manager imports ibm_botocore, which is only present with the
    IBM extra. Skip this class when that extra is not installed so the rest
    of the file still collects
    """

    @pytest.fixture(autouse=True)
    def _ibm(self):
        pytest.importorskip('ibm_botocore')
        pytest.importorskip('ibm_cloud_sdk_core')
        from lithops.util.ibm_token_manager import (
            COSTokenManager,
            EXPIRY_MINUTES,
            IAMTokenManager,
            IBMTokenManager,
        )

        class StubTokenManager(IBMTokenManager):
            TOKEN_FILE = None
            TYPE = 'TEST'

            def _generate_new_token(self):
                self.token = 'new-token'
                self.expiry_time = int(
                    (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
                )

        self.COSTokenManager = COSTokenManager
        self.EXPIRY_MINUTES = EXPIRY_MINUTES
        self.IAMTokenManager = IAMTokenManager
        self.StubTokenManager = StubTokenManager

    def test_token_file_constant_is_spelled_correctly(self):
        assert hasattr(self.COSTokenManager, 'TOKEN_FILE')
        assert hasattr(self.IAMTokenManager, 'TOKEN_FILE')
        assert 'ibm_cos' in self.COSTokenManager.TOKEN_FILE
        assert 'ibm_iam' in self.IAMTokenManager.TOKEN_FILE
        assert not hasattr(self.COSTokenManager, 'TOEKN_FILE')

    def test_missing_expiry_is_expired(self):
        mgr = self.StubTokenManager('key')
        assert mgr._get_token_minutes_left() == 0
        assert mgr._is_token_expired()

    def test_reuses_unexpired_token(self):
        expiry = int(
            (datetime.now(timezone.utc) + timedelta(hours=2)).timestamp()
        )
        mgr = self.StubTokenManager('key', token='cached', token_expiry_time=expiry)
        assert mgr._get_token_minutes_left() >= self.EXPIRY_MINUTES
        token, exp = mgr.get_token()
        assert token == 'cached'
        assert exp == expiry

    def test_refresh_dumps_and_returns_new_token(self, tmp_path, monkeypatch):
        path = tmp_path / 'token'
        monkeypatch.setattr(self.StubTokenManager, 'TOKEN_FILE', str(path))
        mgr = self.StubTokenManager('key')
        with patch(
            'lithops.util.ibm_token_manager.dump_yaml_config'
        ) as dump:
            token, expiry = mgr.refresh_token()
        assert token == 'new-token'
        assert expiry
        dump.assert_called_once()
        assert dump.call_args[0][0] == str(path)

    def test_loads_cache_file(self, tmp_path, monkeypatch):
        path = tmp_path / 'token'
        monkeypatch.setattr(self.StubTokenManager, 'TOKEN_FILE', str(path))
        path.write_text('x')
        expiry = int(
            (datetime.now(timezone.utc) + timedelta(hours=2)).timestamp()
        )
        with patch(
            'lithops.util.ibm_token_manager.load_yaml_config',
            return_value={'token': 'from-disk', 'expiry_time': expiry},
        ):
            with patch(
                'lithops.util.ibm_token_manager.os.path.exists',
                return_value=True,
            ):
                mgr = self.StubTokenManager('key')
        assert mgr.token == 'from-disk'
        assert mgr.expiry_time == expiry


class TestJoblibBackend:

    def test_consider_sharing_and_handle_call(self):
        pytest.importorskip('joblib')
        numpy = pytest.importorskip('numpy')
        from lithops.util.joblib.lithops_backend import (
            consider_sharing,
            handle_call_process,
        )
        assert consider_sharing([1, 2])
        assert consider_sharing(numpy.array([1]))
        assert not consider_sharing({'a': 1})
        assert handle_call_process(lambda x: x + 1, (2,), {}) == 3
        assert handle_call_process(lambda **kw: kw['v'], (), {'v': 9}) == 9

    def test_find_shared_objects_proxies_repeated_lists(self):
        pytest.importorskip('joblib')
        pytest.importorskip('numpy')
        from lithops.util.joblib.lithops_backend import find_shared_objects

        shared = [1, 2, 3]
        calls = [
            (None, (shared,), {}),
            (None, (shared,), {'k': shared}),
        ]
        storage = MagicMock()
        storage.put_cloudobject.return_value = 'cloud-obj'
        with patch(
            'lithops.util.joblib.lithops_backend.Storage',
            return_value=storage,
        ):
            out = find_shared_objects(calls)
        assert out[0][1][0] == 'cloud-obj'
        assert out[1][2]['k'] == 'cloud-obj'
        assert 0 in out[0][3]
        storage.put_cloudobject.assert_called_once()

    def test_submit_is_the_hook_joblib_calls(self):
        # joblib renamed the hook from apply_async to submit, and the
        # multiprocessing backend Lithops extends carries its own submit. If
        # the override goes away joblib silently stops using this backend
        pytest.importorskip('joblib')
        pytest.importorskip('diskcache')
        from joblib._parallel_backends import PoolManagerMixin
        from lithops.util.joblib.lithops_backend import LithopsBackend

        assert 'submit' in LithopsBackend.__dict__
        assert LithopsBackend.submit is not PoolManagerMixin.submit
        # Older joblib calls the old name
        assert LithopsBackend.apply_async is LithopsBackend.submit

    def test_submit_optimizes_the_batch_before_queueing_it(self):
        pytest.importorskip('joblib')
        pytest.importorskip('diskcache')
        from lithops.util.joblib.lithops_backend import LithopsBackend

        backend = LithopsBackend.__new__(LithopsBackend)
        backend.prefer = None
        batch = SimpleNamespace(items=[(print, (1,), {})])
        pool = MagicMock()
        optimizer = patch(
            'lithops.util.joblib.lithops_backend.find_shared_objects',
            return_value=['optimized'],
        )
        with patch.object(LithopsBackend, '_get_pool', return_value=pool), \
                optimizer as optimize:
            backend.submit(batch, callback='cb')

        optimize.assert_called_once_with(batch.items)
        pool.starmap_async.assert_called_once()
        assert pool.starmap_async.call_args[0][1] == ['optimized']

    def test_submit_runs_the_batch_in_one_call_when_threads_preferred(self):
        pytest.importorskip('joblib')
        pytest.importorskip('diskcache')
        from lithops.util.joblib.lithops_backend import LithopsBackend

        backend = LithopsBackend.__new__(LithopsBackend)
        backend.prefer = 'threads'
        batch = SimpleNamespace(items=[(print, (1,), {})])
        pool = MagicMock()
        optimizer = patch(
            'lithops.util.joblib.lithops_backend.find_shared_objects',
            return_value=['optimized'],
        )
        with patch.object(LithopsBackend, '_get_pool', return_value=pool), \
                optimizer:
            backend.submit(batch)
        pool.apply_async.assert_called_once()
        pool.starmap_async.assert_not_called()

    def test_proxied_args_are_read_from_the_cache_in_one_call(self):
        # The tasks of a runtime share the cache directory, and a value too
        # big to sit inline is a file of its own, so a key can be present
        # while its file is not readable yet. Asking and then reading raised
        # KeyError out of the worker
        pytest.importorskip('joblib')
        pytest.importorskip('diskcache')
        from lithops.util.joblib.lithops_backend import replace_with_values

        class RowWithoutItsFileYet:
            def __contains__(self, key):
                return True

            def __getitem__(self, key):
                raise KeyError(key)

            def get(self, key, default=None):
                return default

            def __setitem__(self, key, value):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        storage = MagicMock()
        storage.get_cloudobject.return_value = pickle.dumps([1, 2, 3])
        with patch(
            'lithops.util.joblib.lithops_backend.diskcache.Cache',
            return_value=RowWithoutItsFileYet(),
        ), patch(
            'lithops.util.joblib.lithops_backend.Storage',
            return_value=storage,
        ):
            args, kwargs = replace_with_values(('cloud-obj',), {}, [0])

        assert args == [[1, 2, 3]]
        storage.get_cloudobject.assert_called_once_with('cloud-obj')

    def test_proxied_args_come_from_the_cache_when_it_has_them(self):
        pytest.importorskip('joblib')
        pytest.importorskip('diskcache')
        from lithops.util.joblib.lithops_backend import replace_with_values

        cache = MagicMock()
        cache.__enter__ = lambda self: self
        cache.__exit__ = lambda self, *exc: False
        cache.get.return_value = [4, 5]
        with patch(
            'lithops.util.joblib.lithops_backend.diskcache.Cache',
            return_value=cache,
        ), patch(
            'lithops.util.joblib.lithops_backend.Storage'
        ) as storage_cls:
            args, kwargs = replace_with_values((), {'k': 'cloud-obj'}, ['k'])

        assert kwargs == {'k': [4, 5]}
        storage_cls.assert_not_called()

    def test_find_shared_objects_skips_unique_args(self):
        pytest.importorskip('joblib')
        pytest.importorskip('numpy')
        from lithops.util.joblib.lithops_backend import find_shared_objects

        calls = [
            (None, ([1],), {}),
            (None, ([2],), {}),
        ]
        with patch(
            'lithops.util.joblib.lithops_backend.Storage'
        ) as storage_cls:
            out = find_shared_objects(calls)
        storage_cls.assert_not_called()
        assert out[0][1][0] == [1]
        assert out[1][1][0] == [2]
