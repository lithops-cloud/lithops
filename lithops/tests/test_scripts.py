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
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from lithops.constants import (
    CACHE_DIR,
    JOBS_PREFIX,
    LOCALHOST,
    LITHOPS_TEMP_DIR,
    RUNTIMES_PREFIX,
    SERVERLESS,
    STANDALONE,
    TEMP_PREFIX,
)
from lithops.scripts import cleaner
from lithops.scripts import cli as cli_module
from lithops.scripts.cli import (
    _compute_handler,
    _format_storage_objects,
    _localize_and_sort_rows,
    _require_mode,
    lithops_cli,
    set_config_ow,
)
from lithops.scripts.cleaner import (
    _classify_cleaner_files,
    _executor_id_from_jobs,
    _run_clean_tasks,
    clean_cloudobjects,
    clean_executor_jobs,
    clean_functions,
)


def _cli(*args):
    return CliRunner().invoke(lithops_cli, list(args))


class TestSetConfigOw:

    def test_empty(self):
        assert set_config_ow() == {'lithops': {}, 'backend': {}}

    def test_backend_sets_mode(self):
        cfg = set_config_ow(backend=LOCALHOST)
        assert cfg['lithops']['backend'] == LOCALHOST
        assert cfg['lithops']['mode'] == LOCALHOST

    def test_optional_fields(self):
        cfg = set_config_ow(
            storage='ibm_cos', runtime_name='rt', region='eu'
        )
        assert cfg['lithops']['storage'] == 'ibm_cos'
        assert cfg['backend']['runtime'] == 'rt'
        assert cfg['backend']['region'] == 'eu'


class TestCliHelpers:

    def test_require_mode_standalone_mentions_command(self):
        with pytest.raises(Exception, match='lithops image list') as exc:
            _require_mode(
                {'lithops': {'mode': LOCALHOST}},
                STANDALONE,
                'lithops image list',
            )
        assert 'image build' not in str(exc.value)

    def test_require_mode_serverless(self):
        with pytest.raises(Exception, match='serverless'):
            _require_mode(
                {'lithops': {'mode': LOCALHOST}},
                SERVERLESS,
                'lithops runtime build',
            )

    def test_require_mode_ok(self):
        _require_mode(
            {'lithops': {'mode': STANDALONE}}, STANDALONE, 'lithops job list'
        )

    def test_compute_handler_unknown_mode_raises(self):
        with pytest.raises(Exception, match='Unknown compute mode'):
            _compute_handler({'lithops': {'mode': 'nope'}})

    def test_format_storage_objects(self):
        modified = datetime(2024, 1, 2, 3, 4, 5)
        rows = _format_storage_objects([
            {'Key': 'a', 'LastModified': modified, 'Size': 1024},
            {'Key': 'b'},
        ])
        assert rows[0]['Key'] == 'a'
        assert 'Jan' in rows[0]['LastModified']
        assert rows[0]['Size']
        assert rows[1] == {'Key': 'b'}

    def test_format_storage_objects_empty(self):
        assert _format_storage_objects([]) == []

    def test_localize_and_sort_rows(self):
        rows = [
            ['b', '2024-01-02 00:00:00 UTC'],
            ['a', '2024-01-01 00:00:00 UTC'],
        ]
        sorted_rows = _localize_and_sort_rows(rows, 1)
        assert sorted_rows[0][0] == 'a'


class TestStorageCommands:

    def test_list_empty_bucket_does_not_indexerror(self):
        client = MagicMock()
        client.backend = 'localhost'
        client.list_objects.return_value = []
        with patch('lithops.scripts.cli.Storage', return_value=client):
            with patch('lithops.scripts.cli.setup_lithops_logger'):
                result = _cli('storage', 'list', 'bucket')
        assert result.exit_code == 0
        assert result.exception is None
        assert 'No information' in result.output

    def test_list_objects_prints_table(self):
        client = MagicMock()
        client.backend = 'localhost'
        client.list_objects.return_value = [
            {'Key': 'a.txt', 'Size': 10, 'LastModified': datetime(2024, 1, 1)},
        ]
        with patch('lithops.scripts.cli.Storage', return_value=client):
            with patch('lithops.scripts.cli.setup_lithops_logger'):
                result = _cli('storage', 'list', 'bucket')
        assert result.exit_code == 0
        assert 'a.txt' in result.output
        assert 'Total objects: 1' in result.output

    def test_delete_requires_key_or_prefix(self):
        with patch('lithops.scripts.cli.Storage', return_value=MagicMock()):
            with patch('lithops.scripts.cli.setup_lithops_logger'):
                result = _cli('storage', 'delete', 'bucket')
        assert result.exit_code != 0
        assert 'KEY or --prefix' in result.output

    def test_delete_key(self):
        client = MagicMock()
        with patch('lithops.scripts.cli.Storage', return_value=client):
            with patch('lithops.scripts.cli.setup_lithops_logger'):
                result = _cli('storage', 'delete', 'bucket', 'obj')
        assert result.exit_code == 0
        client.delete_object.assert_called_once_with('bucket', 'obj')

    def test_delete_prefix(self):
        client = MagicMock()
        client.list_keys.return_value = ['a', 'b']
        with patch('lithops.scripts.cli.Storage', return_value=client):
            with patch('lithops.scripts.cli.setup_lithops_logger'):
                result = _cli('storage', 'delete', 'bucket', '--prefix', 'pre')
        assert result.exit_code == 0
        client.delete_objects.assert_called_once_with('bucket', ['a', 'b'])


class TestLogsAndAttach:

    def test_get_logs_missing_file_message(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.scripts.cli.LOGS_DIR', str(tmp_path))
        result = _cli('logs', 'get', 'missing-id')
        assert result.exit_code == 0
        assert 'does not exist' in result.output
        assert 'does not exists' not in result.output

    def test_get_logs_prints_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.scripts.cli.LOGS_DIR', str(tmp_path))
        (tmp_path / 'job.log').write_text('hello-log\n')
        result = _cli('logs', 'get', 'job')
        assert 'hello-log' in result.output

    def test_attach_ssh_uses_argv_list_for_key_with_spaces(self):
        handler = MagicMock()
        handler.is_initialized.return_value = True
        handler.backend.master.is_ready.return_value = True
        handler.backend.master.get_public_ip.return_value = '10.0.0.1'
        key = '/tmp/my key.pem'
        handler.backend.master.ssh_credentials = {
            'username': 'ubuntu',
            'key_filename': key,
        }
        with patch('lithops.scripts.cli._prepare_standalone', return_value=handler):
            with patch('lithops.scripts.cli.os.path.exists', return_value=True):
                with patch('lithops.scripts.cli.sp.run') as run:
                    result = _cli('attach', '-b', 'aws_ec2')
        assert result.exit_code == 0
        cmd = run.call_args[0][0]
        assert cmd[0] == 'ssh'
        assert isinstance(cmd, list)
        assert os.path.abspath(os.path.expanduser(key)) in cmd
        assert 'ubuntu@10.0.0.1' in cmd


class TestHelloAndClean:

    def test_hello_call_async(self):
        fexec = MagicMock()
        fexec.get_result.return_value = 'Hello tester!'
        with patch('getpass.getuser', return_value='tester'):
            with patch(
                'lithops.scripts.cli.lithops.FunctionExecutor',
                return_value=fexec,
            ):
                with patch('lithops.scripts.cli.setup_lithops_logger'):
                    result = _cli('hello')
        assert result.exit_code == 0
        fexec.call_async.assert_called_once()
        assert 'Lithops is working as expected' in result.output

    def test_clean_localhost(self):
        cfg = {
            'lithops': {'mode': LOCALHOST, 'backend': LOCALHOST},
            LOCALHOST: {},
        }
        handler = MagicMock()
        storage = MagicMock()
        storage.bucket = 'bkt'
        internal = MagicMock()
        internal.storage = storage
        with patch('lithops.scripts.cli._resolved_config', return_value=cfg):
            with patch('lithops.scripts.cli.extract_storage_config', return_value={}):
                with patch('lithops.scripts.cli.InternalStorage', return_value=internal):
                    with patch(
                        'lithops.scripts.cli._compute_handler',
                        return_value=handler,
                    ):
                        with patch('lithops.scripts.cli.clean_bucket') as cb:
                            with patch('lithops.scripts.cli.shutil.rmtree') as rmtree:
                                with patch(
                                    'lithops.scripts.cli._clean_local_temp_data'
                                ) as clean_temp:
                                    with patch('lithops.scripts.cli.setup_lithops_logger'):
                                        result = _cli('clean', '--all')
        assert result.exit_code == 0
        handler.clean.assert_called_once_with(all=True)
        assert cb.call_count == 2
        clean_temp.assert_called_once_with()
        removed = [call.args[0] for call in rmtree.call_args_list]
        assert LITHOPS_TEMP_DIR not in removed
        assert os.path.join(CACHE_DIR, RUNTIMES_PREFIX, LOCALHOST) in removed

    def test_clean_local_temp_keeps_the_shared_skeleton(
        self, tmp_path, monkeypatch
    ):
        cleaner_dir = tmp_path / 'cleaner'
        logs_dir = tmp_path / 'logs'
        jobs_dir = tmp_path / 'jobs'
        for path in (cleaner_dir, logs_dir, jobs_dir, tmp_path / 'modules'):
            path.mkdir()
        (cleaner_dir / 'pending-request').write_text('keep me')
        (logs_dir / 'ex-0-A000.log').write_text('drop me')
        (tmp_path / 'functions.log').write_text('drop me')

        for name, value in (
            ('LITHOPS_TEMP_DIR', tmp_path),
            ('CLEANER_DIR', cleaner_dir),
            ('LOGS_DIR', logs_dir),
            ('JOBS_DIR', jobs_dir),
        ):
            monkeypatch.setattr(f'lithops.scripts.cli.{name}', str(value))

        cli_module._clean_local_temp_data()

        # The requests of the other processes on this machine survive
        assert (cleaner_dir / 'pending-request').read_text() == 'keep me'
        # Their data does not, but the directories they write into come back
        assert not (logs_dir / 'ex-0-A000.log').exists()
        assert not (tmp_path / 'functions.log').exists()
        assert not (tmp_path / 'modules').exists()
        assert logs_dir.is_dir()
        assert jobs_dir.is_dir()

    def test_clean_local_temp_tolerates_a_missing_dir(self, tmp_path, monkeypatch):
        missing = tmp_path / 'gone'
        monkeypatch.setattr('lithops.scripts.cli.LITHOPS_TEMP_DIR', str(missing))
        for name in ('CLEANER_DIR', 'LOGS_DIR', 'JOBS_DIR'):
            monkeypatch.setattr(
                f'lithops.scripts.cli.{name}', str(missing / name.lower())
            )

        cli_module._clean_local_temp_data()

        assert missing.is_dir()


class TestJobWorkerList:

    def test_job_list_empty_does_not_crash(self):
        handler = MagicMock()
        handler.is_initialized.return_value = True
        handler.backend.master.is_ready.return_value = True
        handler._is_master_service_ready.return_value = True
        handler.list_jobs.return_value = []
        with patch('lithops.scripts.cli._prepare_standalone', return_value=handler):
            result = _cli('job', 'list', '-b', 'aws_ec2')
        assert result.exit_code == 0
        assert 'Total jobs: 0' in result.output

    def test_worker_list_empty_does_not_crash(self):
        handler = MagicMock()
        handler.is_initialized.return_value = True
        handler.backend.master.is_ready.return_value = True
        handler._is_master_service_ready.return_value = True
        handler.list_workers.return_value = []
        with patch('lithops.scripts.cli._prepare_standalone', return_value=handler):
            result = _cli('worker', 'list', '-b', 'aws_ec2')
        assert result.exit_code == 0
        assert 'Total workers: 0' in result.output

    def test_standalone_not_initialized(self):
        handler = MagicMock()
        handler.is_initialized.return_value = False
        with patch('lithops.scripts.cli._prepare_standalone', return_value=handler):
            result = _cli('job', 'list')
        assert result.exit_code == 0
        handler.list_jobs.assert_not_called()


class TestCleaner:

    def test_import_does_not_redirect_stdout(self):
        dest = getattr(sys.stdout, 'name', None)
        assert dest != cleaner.CLEANER_LOG_FILE

    def test_executor_id_from_jobs(self):
        assert _executor_id_from_jobs({'abc-0-M000'}) == 'abc-0'
        assert _executor_id_from_jobs(set()) is None

    def test_empty_jobs_to_clean_is_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cleaner, 'CLEANER_DIR', str(tmp_path))
        payload = {
            'jobs_to_clean': set(),
            'storage_config': {},
            'clean_cloudobjects': False,
        }
        path = tmp_path / 'job.pkl'
        path.write_bytes(pickle.dumps(payload))
        jobs, cos, fns = _classify_cleaner_files(['job.pkl'])
        assert jobs == {}
        assert cos == []
        assert fns == []
        assert not path.exists()

    def test_classify_groups_jobs_by_executor(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cleaner, 'CLEANER_DIR', str(tmp_path))
        for name, jobs in (
            ('a.pkl', {'ex-0-M000'}),
            ('b.pkl', {'ex-0-M001'}),
            ('c.pkl', {'other-1-M000'}),
        ):
            (tmp_path / name).write_bytes(pickle.dumps({
                'jobs_to_clean': jobs,
                'storage_config': {},
                'clean_cloudobjects': False,
            }))
        (tmp_path / 'cos.pkl').write_bytes(pickle.dumps({
            'cos_to_clean': [],
            'storage_config': {},
        }))
        (tmp_path / 'fn.pkl').write_bytes(pickle.dumps({
            'fn_to_clean': 'ex-0',
            'storage_config': {},
        }))
        jobs, cos, fns = _classify_cleaner_files(
            ['a.pkl', 'b.pkl', 'c.pkl', 'cos.pkl', 'fn.pkl']
        )
        assert set(jobs) == {'ex-0', 'other-1'}
        assert len(jobs['ex-0']) == 2
        assert len(cos) == 1
        assert len(fns) == 1

    def test_clean_executor_jobs_reuses_storage(self, tmp_path):
        files = []
        for name in ('one.pkl', 'two.pkl'):
            path = tmp_path / name
            path.write_text('x')
            files.append({
                'file_location': str(path),
                'data': {
                    'storage_config': {'k': 1},
                    'clean_cloudobjects': True,
                    'jobs_to_clean': {'ex-j0'},
                },
            })
        storage = MagicMock()
        storage.bucket = 'bkt'
        with patch('lithops.scripts.cleaner.Storage', return_value=storage) as st:
            with patch('lithops.scripts.cleaner.clean_bucket') as cb:
                clean_executor_jobs('ex', files)
        st.assert_called_once()
        assert cb.call_count == 4
        prefixes = [c.args[2] for c in cb.call_args_list]
        assert f'{JOBS_PREFIX}/ex-j0/' in prefixes
        assert f'{TEMP_PREFIX}/ex-j0/' in prefixes
        assert not (tmp_path / 'one.pkl').exists()

    def test_clean_cloudobjects_same_backend_only(self, tmp_path):
        path = tmp_path / 'cos.pkl'
        path.write_text('x')
        keep = SimpleNamespace(backend='s3', bucket='b', key='keep')
        drop = SimpleNamespace(backend='localhost', bucket='b', key='drop')
        storage = MagicMock()
        storage.backend = 'localhost'
        with patch('lithops.scripts.cleaner.Storage', return_value=storage):
            clean_cloudobjects({
                'file_location': str(path),
                'data': {
                    'cos_to_clean': [keep, drop],
                    'storage_config': {},
                },
            })
        storage.delete_object.assert_called_once_with('b', 'drop')
        assert not path.exists()

    def test_clean_functions_deletes_keys(self, tmp_path):
        path = tmp_path / 'fn.pkl'
        path.write_text('x')
        storage = MagicMock()
        storage.bucket = 'bkt'
        storage.list_keys.return_value = ['k1']
        with patch('lithops.scripts.cleaner.Storage', return_value=storage):
            clean_functions({
                'file_location': str(path),
                'data': {
                    'fn_to_clean': 'ex-0',
                    'storage_config': {},
                },
            })
        storage.delete_objects.assert_called_once_with('bkt', ['k1'])

    def test_run_clean_tasks_surfaces_exceptions(self):
        with patch(
            'lithops.scripts.cleaner.clean_cloudobjects',
            side_effect=RuntimeError('boom'),
        ):
            with pytest.raises(RuntimeError, match='boom'):
                _run_clean_tasks(
                    {}, [{'file_location': 'a', 'data': {}}], []
                )

    def test_clean_loop_exits_when_idle(self, monkeypatch):
        monkeypatch.setattr(cleaner, '_IDLE_CONFIRM_SECONDS', 0)
        monkeypatch.setattr(cleaner.os, 'listdir', lambda _: [])
        cleaner.clean()

    def test_clean_loop_ignores_log_and_pid_files(self, monkeypatch):
        names = [
            os.path.basename(cleaner.CLEANER_LOG_FILE),
            os.path.basename(cleaner.CLEANER_PID_FILE),
        ]
        monkeypatch.setattr(cleaner, '_IDLE_CONFIRM_SECONDS', 0)
        monkeypatch.setattr(cleaner.os, 'listdir', lambda _: names)
        with patch.object(cleaner, '_run_clean_tasks') as run:
            cleaner.clean()
        run.assert_not_called()

    def test_clean_loop_picks_up_request_dropped_while_idle(self, monkeypatch):
        calls = {'n': 0}

        def listdir(_):
            calls['n'] += 1
            if calls['n'] == 2:
                return ['late.pkl']
            return []

        monkeypatch.setattr(cleaner, '_IDLE_CONFIRM_SECONDS', 0)
        monkeypatch.setattr(cleaner.os, 'listdir', listdir)
        monkeypatch.setattr(cleaner.time, 'sleep', lambda _s: None)
        with patch.object(
            cleaner, '_classify_cleaner_files', return_value=({}, [], [])
        ) as classify:
            with patch.object(cleaner, '_run_clean_tasks'):
                cleaner.clean()
        classify.assert_called_once_with(['late.pkl'])

    def test_classify_discards_unreadable_request(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cleaner, 'CLEANER_DIR', str(tmp_path))
        corrupt = tmp_path / 'half-written'
        corrupt.write_bytes(b'\x80\x05}')

        assert cleaner._classify_cleaner_files(['half-written']) == ({}, [], [])
        assert not corrupt.exists()

    def test_classify_discards_unknown_request(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cleaner, 'CLEANER_DIR', str(tmp_path))
        unknown = tmp_path / 'unknown'
        with unknown.open('wb') as fh:
            pickle.dump({'something_else': 1}, fh)

        assert cleaner._classify_cleaner_files(['unknown']) == ({}, [], [])
        assert not unknown.exists()

    def test_pending_requests_ignore_files_being_written(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(cleaner, 'CLEANER_DIR', str(tmp_path))
        (tmp_path / 'ready').write_text('x')
        (tmp_path / f'staging{cleaner.CLEANER_TMP_SUFFIX}').write_text('x')

        assert cleaner._pending_request_files() == ['ready']

    def test_pending_requests_tolerate_missing_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cleaner, 'CLEANER_DIR', str(tmp_path / 'gone'))
        assert cleaner._pending_request_files() == []

    def test_main_skips_while_another_cleaner_holds_the_lock(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(cleaner, 'CLEANER_PID_FILE', str(tmp_path / 'cleaner.pid'))
        monkeypatch.setattr(cleaner, 'CLEANER_DIR', str(tmp_path))
        monkeypatch.setattr(cleaner, '_LOCK_RETRY_SECONDS', 0)

        held = cleaner._lock_pid_file()
        assert held is not None
        try:
            with patch.object(cleaner, '_configure_cleaner_logging') as cfg:
                cleaner.main()
            cfg.assert_not_called()
        finally:
            os.close(held)

    def test_main_takes_the_lock_a_dead_cleaner_left_behind(
        self, tmp_path, monkeypatch
    ):
        pid = tmp_path / 'cleaner.pid'
        # The pid of a cleaner that died without removing its file. Nothing
        # holds the lock any more, so this run must not be blocked by it
        pid.write_text('999999999')
        monkeypatch.setattr(cleaner, 'CLEANER_PID_FILE', str(pid))
        monkeypatch.setattr(cleaner, 'CLEANER_DIR', str(tmp_path))

        with patch.object(cleaner, '_configure_cleaner_logging'):
            with patch.object(cleaner, 'clean') as clean_fn:
                cleaner.main()

        clean_fn.assert_called_once()
        assert pid.read_text() == str(os.getpid())

    def test_lock_is_released_when_the_cleaner_finishes(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(cleaner, 'CLEANER_PID_FILE', str(tmp_path / 'cleaner.pid'))
        monkeypatch.setattr(cleaner, 'CLEANER_DIR', str(tmp_path))

        with patch.object(cleaner, '_configure_cleaner_logging'):
            with patch.object(cleaner, 'clean'):
                cleaner.main()

        second = cleaner._lock_pid_file()
        assert second is not None
        os.close(second)
