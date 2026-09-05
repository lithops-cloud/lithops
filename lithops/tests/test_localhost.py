#
# Unit tests for the localhost compute and storage backends.
# No Docker daemon required; subprocess and docker CLI calls are mocked.
#

import copy
import io
import json
import logging
import os
import queue
import shutil
import signal
import subprocess as sp
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import lithops
from lithops.constants import JOBS_PREFIX, TEMP_DIR, USER_TEMP_DIR
from lithops.localhost import LocalhostHandler, LocalhostHandlerV1, LocalhostHandlerV2
from lithops.localhost import config as localhost_config
from lithops.localhost.v1 import localhost as v1
from lithops.localhost.v1 import runner as v1_runner
from lithops.localhost.v2 import localhost as v2
from lithops.localhost.v2 import runner as v2_runner
from lithops.localhost.utils import (
    copy_lithops_package,
    decode_process_output,
    docker_pull_cmd,
    docker_rm_cmd,
    docker_run_cmd,
    log_process_failure,
)
from lithops.storage.backends.localhost.localhost import LocalhostStorageBackend
from lithops.storage.utils import StorageNoSuchKeyError
from lithops.tests.functions import simple_map_function, sleep_seconds
from lithops.utils import BackendType, CountDownLatch
from lithops.version import __version__


def _config(**extra):
    cfg = {
        'runtime': 'python3',
        'max_workers': 1,
        'worker_processes': 2,
    }
    cfg.update(extra)
    return cfg


def _job_payload(**extra):
    payload = {
        'executor_id': 'sess-0',
        'job_id': 'M000',
        'job_key': 'sess-0-M000',
        'call_ids': ['00000', '00001'],
        'data_byte_ranges': [(0, 1), (2, 3)],
        'config': {
            'lithops': {'storage': 'localhost'},
            'localhost': {'storage_bucket': 'storage'},
        },
    }
    payload.update(extra)
    return payload


class TestLocalhostConfig:

    def test_environment_default_for_python_and_paths(self):
        for runtime in (
            'python',
            'python3',
            'python3.12',
            '/usr/bin/python3',
            r'C:\Python\python.exe',
        ):
            assert localhost_config.get_environment(runtime) is (
                localhost_config.LocalhostEnvironment.DEFAULT
            )

    def test_environment_container_for_image_names(self):
        for runtime in (
            'lithopscloud/ibmcf-python-v312',
            'docker.io/lithopscloud/ibmcf-python-v312',
        ):
            assert localhost_config.get_environment(runtime) is (
                localhost_config.LocalhostEnvironment.CONTAINER
            )

    def test_environment_python_tagged_image_is_container(self):
        assert localhost_config.get_environment('python:3.12') is (
            localhost_config.LocalhostEnvironment.CONTAINER
        )

    def test_environment_enum_values(self):
        assert localhost_config.LocalhostEnvironment.DEFAULT.value == 'default'
        assert localhost_config.LocalhostEnvironment.CONTAINER.value == 'container'

    def test_runtime_key_and_info(self):
        assert localhost_config.runtime_key('/python3/') == (
            f'localhost/{__version__}/python3'
        )
        assert localhost_config.runtime_key(r'C:\Python\python.exe') == (
            f'localhost/{__version__}/C:/Python/python.exe'
        )
        assert '\\' not in localhost_config.runtime_key(r'C:\Python\python.exe')
        assert localhost_config.runtime_info(_config(runtime_memory=256)) == {
            'runtime_name': 'python3',
            'runtime_memory': 256,
            'runtime_timeout': None,
            'max_workers': 1,
        }

    def test_load_config_fills_defaults_and_forces_max_workers(self):
        cfg = {'lithops': {}, 'localhost': {'max_workers': 8, 'runtime': 'python3.11'}}
        localhost_config.load_config(cfg)
        assert cfg['localhost']['runtime'] == 'python3.11'
        assert cfg['localhost']['worker_processes'] == (os.cpu_count() or 1)
        assert cfg['localhost']['max_workers'] == 1
        assert cfg['lithops']['execution_timeout'] == (
            localhost_config.LOCALHOST_EXECUTION_TIMEOUT
        )
        assert cfg['lithops']['storage'] == 'localhost'

    def test_load_config_creates_localhost_section(self):
        cfg = {'lithops': {'storage': 's3', 'execution_timeout': 9}}
        localhost_config.load_config(cfg)
        assert cfg['localhost']['runtime'] == localhost_config.DEFAULT_CONFIG_KEYS['runtime']
        assert cfg['lithops']['storage'] == 's3'
        assert cfg['lithops']['execution_timeout'] == 9

    def test_default_handler_is_v2(self):
        assert LocalhostHandler is LocalhostHandlerV2


class TestLocalhostHandlerV2:

    def test_backend_type_runtime_key_and_info(self):
        handler = LocalhostHandlerV2(_config(runtime_memory=256, runtime_timeout=60))
        assert handler.get_backend_type() == BackendType.BATCH.value
        assert handler.get_runtime_key('/python3/') == (
            f'localhost/{__version__}/python3'
        )
        assert handler.get_runtime_info() == {
            'runtime_name': 'python3',
            'runtime_memory': 256,
            'runtime_timeout': 60,
            'max_workers': 1,
        }
        handler.clean()

    def test_init_selects_default_environment(self):
        handler = LocalhostHandlerV2(_config())
        with patch.object(v2, 'DefaultEnvironment') as env_cls:
            handler.init()
        env_cls.assert_called_once_with(handler.config)
        env_cls.return_value.setup.assert_called_once()
        assert handler.env is env_cls.return_value

    def test_init_selects_container_environment(self):
        handler = LocalhostHandlerV2(_config(runtime='lithops/python:3.12'))
        with patch.object(v2, 'ContainerEnvironment') as env_cls:
            handler.init()
        env_cls.assert_called_once_with(handler.config)
        assert handler.env is env_cls.return_value

    def test_invoke_runs_job_and_starts_manager(self):
        handler = LocalhostHandlerV2(_config())
        handler.env = MagicMock()
        handler.start_manager = MagicMock()
        payload = _job_payload()
        handler.invoke(payload)
        handler.env.run_job.assert_called_once_with(payload)
        handler.start_manager.assert_called_once()
        assert handler.invocation_in_progress is False

    def test_start_manager_is_noop_when_already_running(self):
        handler = LocalhostHandlerV2(_config())
        handler.env = MagicMock()
        handler.job_manager = object()
        handler.start_manager()
        handler.env.start.assert_not_called()

    def test_clear_drains_queue_and_unlocks_jobs(self):
        """
        clear() without a job named is the executor going away, so the
        running tasks are stopped: nothing is waiting on their output,
        and waiting for one would hold up the shutdown for as long as
        it runs
        """
        handler = LocalhostHandlerV2(_config())
        handler.env = MagicMock()
        handler.env.work_queue = queue.Queue()
        handler.env.work_queue.put('task-a')
        handler.env.work_queue.put('task-b')
        latch = CountDownLatch(2)
        handler.env.jobs = {'sess-0-M000': latch}
        handler.clear()
        handler.env.drop_pending_tasks.assert_called_once_with(None)
        handler.env.stop.assert_called_once_with(None)
        handler.env.finish.assert_not_called()
        assert latch.done is True

    def test_clear_of_a_named_job_lets_its_tasks_finish(self):
        """
        A named job that ended cleanly keeps its runner log, so its
        tasks are left to exit on their own
        """
        handler = LocalhostHandlerV2(_config())
        handler.env = MagicMock()
        handler.env.jobs = {}
        handler.clear({'sess-0-M000'})
        handler.env.finish.assert_called_once_with({'sess-0-M000'})
        handler.env.stop.assert_not_called()

    def test_clear_kills_running_tasks_on_exception(self):
        handler = LocalhostHandlerV2(_config())
        handler.env = MagicMock()
        handler.env.jobs = {}
        error = RuntimeError('boom')
        handler.clear(exception=error)
        handler.env.stop.assert_called_once_with(None)
        handler.env.finish.assert_not_called()

    def test_clear_leaves_the_latches_of_other_jobs_alone(self):
        handler = LocalhostHandlerV2(_config())
        handler.env = MagicMock()
        mine, theirs = CountDownLatch(1), CountDownLatch(1)
        handler.env.jobs = {'sess-0-M000': mine, 'sess-0-M001': theirs}
        handler.clear({'sess-0-M000'})
        assert mine.done is True
        assert theirs.done is False


class TestLocalhostHandlerV1:

    def test_backend_type_and_runtime_key_match_v2(self):
        handler = LocalhostHandlerV1(_config())
        assert handler.get_backend_type() == BackendType.BATCH.value
        assert handler.get_runtime_key('python3') == (
            f'localhost/{__version__}/python3'
        )

    def test_init_selects_default_environment(self):
        handler = LocalhostHandlerV1(_config())
        with patch.object(v1, 'DefaultEnvironment') as env_cls:
            handler.init()
        env_cls.assert_called_once_with(handler.config)
        env_cls.return_value.setup.assert_called_once()

    def test_invoke_queues_prepared_job_file(self):
        handler = LocalhostHandlerV1(_config())
        handler.env = MagicMock()
        handler.env.prepare_job_file.return_value = '/tmp/job.json'
        handler.start_manager = MagicMock()
        payload = _job_payload()
        handler.invoke(payload)
        handler.env.prepare_job_file.assert_called_once_with(payload)
        assert handler.job_queue.get_nowait() == (payload, '/tmp/job.json')
        handler.start_manager.assert_called_once()
        assert handler.invocation_in_progress is False

    def test_clear_drains_queue_and_sends_sentinel(self):
        """
        clear() without a job named is the executor going away, so the
        running job is stopped rather than waited for
        """
        handler = LocalhostHandlerV1(_config())
        handler.env = MagicMock()
        handler.job_manager = object()
        handler.job_queue.put(('job', 'file'))
        handler.clear()
        handler.env.stop.assert_called_once_with(None)
        assert handler.job_queue.get_nowait() == (None, None)

    def test_clear_of_a_named_job_lets_it_finish(self):
        handler = LocalhostHandlerV1(_config())
        handler.env = MagicMock()
        handler.job_manager = object()
        handler.clear({'sess-0-M000'})
        handler.env.stop.assert_not_called()

    def test_clear_kills_running_jobs_on_exception(self):
        handler = LocalhostHandlerV1(_config())
        handler.env = MagicMock()
        handler.job_manager = object()
        handler.clear(exception=RuntimeError('boom'))
        handler.env.stop.assert_called_once()
        assert handler.job_queue.get_nowait() == (None, None)

    def test_clear_leaves_the_queued_jobs_of_others_alone(self):
        handler = LocalhostHandlerV1(_config())
        handler.env = MagicMock()
        handler.job_manager = object()
        mine = ({'job_key': 'sess-0-M000'}, 'mine.json')
        theirs = ({'job_key': 'sess-0-M001'}, 'theirs.json')
        handler.job_queue.put(mine)
        handler.job_queue.put(theirs)
        handler.clear({'sess-0-M000'})
        assert handler.job_queue.get_nowait() == theirs
        assert handler.job_queue.get_nowait() == (None, None)
        assert handler.job_queue.empty()


class TestV2Environment:

    def test_run_job_splits_payload_per_call(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.localhost.v2.localhost.JOBS_DIR', str(tmp_path))
        env = v2.ExecutionEnvironment(_config(worker_processes=1))
        env.run_job(_job_payload())
        assert env.jobs['sess-0-M000'].count == 2
        first = json.loads(env.work_queue.get_nowait())
        second = json.loads(env.work_queue.get_nowait())
        assert first['call_ids'] == ['00000']
        assert first['data_byte_ranges'] == [[0, 1]]
        assert second['call_ids'] == ['00001']
        assert second['data_byte_ranges'] == [[2, 3]]

    def test_start_is_noop_when_consumers_already_running(self):
        env = v2.ExecutionEnvironment(_config(worker_processes=1))
        existing = object()
        env.consumer_threads = [existing]
        env.start()
        assert env.consumer_threads == [existing]

    def test_consumer_writes_task_file_then_unlocks(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.localhost.v2.localhost.JOBS_DIR', str(tmp_path))
        env = v2.ExecutionEnvironment(_config(worker_processes=1))
        env.run_task = MagicMock()
        env.run_job(_job_payload(call_ids=['00000'], data_byte_ranges=[(0, 1)]))
        env.start()
        try:
            env.jobs['sess-0-M000'].wait()
            env.run_task.assert_called_once_with('sess-0-M000', '00000')
            assert not (tmp_path / 'sess-0-M000' / '00000.task').exists()
        finally:
            env.stop()
        assert env.consumer_threads == []

    def test_copy_lithops_skips_inside_worker_when_runner_exists(
        self, tmp_path, monkeypatch
    ):
        runner = tmp_path / 'localhost-runner.py'
        runner.write_text('# runner\n')
        monkeypatch.setattr('lithops.localhost.v2.localhost.RUNNER_FILE', str(runner))
        monkeypatch.setattr(
            'lithops.localhost.v2.localhost.is_lithops_worker', lambda: True
        )
        env = v2.ExecutionEnvironment(_config())
        with patch('lithops.localhost.v2.localhost.copy_lithops_package') as copy_pkg:
            env._copy_lithops_to_tmp()
        copy_pkg.assert_not_called()

    def test_copy_lithops_uses_v2_runner(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'lithops.localhost.v2.localhost.LITHOPS_TEMP_DIR', str(tmp_path)
        )
        monkeypatch.setattr(
            'lithops.localhost.v2.localhost.RUNNER_FILE',
            str(tmp_path / 'localhost-runner.py'),
        )
        monkeypatch.setattr(
            'lithops.localhost.v2.localhost.is_lithops_worker', lambda: False
        )
        env = v2.ExecutionEnvironment(_config())
        with patch('lithops.localhost.v2.localhost.copy_lithops_package') as copy_pkg:
            env._copy_lithops_to_tmp()
        runner_src = copy_pkg.call_args[0][1]
        assert runner_src.endswith(os.path.join('localhost', 'v2', 'runner.py'))
        assert copy_pkg.call_args[0][2] == str(tmp_path / 'localhost-runner.py')
        assert copy_pkg.call_args[0][3] == str(tmp_path)

    def test_default_run_task_invokes_runner_and_drops_process(self):
        env = v2.DefaultEnvironment(_config())
        proc = MagicMock()
        proc.returncode = 1
        proc.communicate.return_value = (b'', b'Traceback: boom\n')
        with patch('lithops.localhost.v2.localhost.sp.Popen', return_value=proc) as popen, \
                patch('lithops.localhost.v2.localhost.log_process_failure') as log_fail:
            env.run_task('sess-0-M000', '00000')
        cmd = popen.call_args[0][0]
        assert cmd[0] == 'python3'
        assert cmd[2:] == [
            'run_job',
            os.path.join(v2.JOBS_DIR, 'sess-0-M000', '00000.task'),
        ]
        proc.communicate.assert_called_once()
        assert 'sess-0-M000-00000' not in env.task_processes
        log_fail.assert_called_once()
        assert log_fail.call_args.kwargs['stderr'] == b'Traceback: boom\n'

    def test_default_run_task_does_not_dump_logs_when_signalled(self):
        env = v2.DefaultEnvironment(_config())
        proc = MagicMock()
        proc.returncode = -9
        proc.communicate.return_value = (b'', b'')
        with patch('lithops.localhost.v2.localhost.sp.Popen', return_value=proc), \
                patch('lithops.localhost.v2.localhost.log_process_failure') as log_fail:
            env.run_task('sess-0-M000', '00000')
        log_fail.assert_not_called()
        assert 'sess-0-M000-00000' not in env.task_processes

    def test_default_stop_kills_matching_process_group(self):
        env = v2.DefaultEnvironment(_config(worker_processes=1))
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 123
        env.task_processes['sess-0-M000-00000'] = proc
        env.jobs = {'sess-0-M000': CountDownLatch(0)}
        env.is_unix_system = True
        with patch('lithops.localhost.utils.os.getpgid', return_value=9), \
                patch('lithops.localhost.utils.os.killpg') as killpg, \
                patch.object(v2.ExecutionEnvironment, '_teardown'):
            env.stop(['sess-0-M000'])
        killpg.assert_called_once_with(9, signal.SIGKILL)
        assert 'sess-0-M000-00000' not in env.task_processes

    def test_teardown_sends_one_sentinel_per_running_consumer(self):
        env = v2.DefaultEnvironment(_config(worker_processes=3))
        # No consumer running: a sentinel would sit in the queue and kill the
        # next consumer that starts
        env.stop()
        assert env.work_queue.empty()

        env.consumer_threads = [MagicMock(), MagicMock()]
        env._teardown()
        assert env.work_queue.qsize() == 2
        assert env.consumer_threads == []

    def test_stop_keeps_consumers_while_another_job_runs(self):
        env = v2.DefaultEnvironment(_config(worker_processes=1))
        env.jobs = {
            'sess-0-M000': CountDownLatch(0),
            'sess-0-M001': CountDownLatch(1),
        }
        threads = [MagicMock()]
        env.consumer_threads = list(threads)
        env.stop(['sess-0-M000'])
        assert env.consumer_threads == threads
        assert env.work_queue.empty()
        threads[0].join.assert_not_called()

        # Once that job is done too, the environment is torn down
        env.jobs['sess-0-M001'].unlock()
        env.stop(['sess-0-M001'])
        assert env.consumer_threads == []

    def test_finish_keeps_consumers_while_another_job_runs(self):
        env = v2.DefaultEnvironment(_config(worker_processes=1))
        env.jobs = {
            'sess-0-M000': CountDownLatch(0),
            'sess-0-M001': CountDownLatch(1),
        }
        threads = [MagicMock()]
        env.consumer_threads = list(threads)
        env.finish(['sess-0-M000'])
        assert env.consumer_threads == threads
        threads[0].join.assert_not_called()

    def test_finish_tears_down_without_killing(self):
        env = v2.DefaultEnvironment(_config(worker_processes=1))
        proc = MagicMock()
        proc.poll.return_value = None
        env.task_processes['sess-0-M000-00000'] = proc
        env.jobs = {'sess-0-M000': CountDownLatch(0)}
        env.consumer_threads = [MagicMock()]
        with patch('lithops.localhost.utils.os.killpg') as killpg:
            env.finish(['sess-0-M000'])
        killpg.assert_not_called()
        assert 'sess-0-M000-00000' in env.task_processes
        assert env.consumer_threads == []

    def test_drop_pending_tasks_keeps_the_other_jobs_tasks(self):
        env = v2.DefaultEnvironment(_config(worker_processes=1))
        mine = json.dumps({'job_key': 'sess-0-M000'})
        theirs = json.dumps({'job_key': 'sess-0-M001'})
        env.work_queue.put(mine)
        env.work_queue.put(theirs)
        env.work_queue.put(None)
        env.drop_pending_tasks({'sess-0-M000'})
        assert env.work_queue.get_nowait() == theirs
        assert env.work_queue.empty()

    def test_drop_pending_tasks_empties_the_queue_for_every_job(self):
        env = v2.DefaultEnvironment(_config(worker_processes=1))
        env.work_queue.put(json.dumps({'job_key': 'sess-0-M000'}))
        env.work_queue.put(None)
        env.drop_pending_tasks()
        assert env.work_queue.empty()

    def test_task_process_not_started_when_job_was_stopped(self):
        env = v2.DefaultEnvironment(_config(worker_processes=1))
        env.stopped_jobs.add('sess-0-M000')
        with patch('lithops.localhost.v2.localhost.sp.Popen') as popen:
            env._run_task_process('sess-0-M000-00000', ['cmd'])
        popen.assert_not_called()
        assert 'sess-0-M000-00000' not in env.task_processes

    def test_stop_marks_the_job_and_run_job_clears_it(self):
        env = v2.DefaultEnvironment(_config(worker_processes=1))
        env.jobs = {'sess-0-M000': CountDownLatch(1)}
        with patch.object(v2.ExecutionEnvironment, '_teardown'):
            env.stop(['sess-0-M000'])
        assert 'sess-0-M000' in env.stopped_jobs

        payload = {
            'job_key': 'sess-0-M000',
            'call_ids': ['00000'],
            'data_byte_ranges': [None],
        }
        with patch('lithops.localhost.v2.localhost.os.makedirs'):
            env.run_job(payload)
        assert 'sess-0-M000' not in env.stopped_jobs

    def test_container_metadata_command_uses_runner_and_user(self):
        with patch.object(v2, 'get_docker_path', return_value='/bin/docker'), \
                patch.object(v2, 'is_podman', return_value=False):
            env = v2.ContainerEnvironment(_config(runtime='img:tag'))
        env.is_unix_system = True
        env.uid = 1000
        env.gid = 1000
        result = MagicMock()
        result.stdout = '{"preinstalls": []}\n'
        with patch('lithops.localhost.v2.localhost.os.path.isfile', return_value=True), \
                patch('lithops.localhost.v2.localhost.sp.run', return_value=result) as run:
            assert env.get_metadata() == {'preinstalls': []}
        cmd = run.call_args[0][0]
        joined = ' '.join(cmd)
        assert cmd[0] == '/bin/docker'
        assert '--user' in cmd
        assert '1000:1000' in joined
        assert 'get_metadata' in joined
        # Taken from the constant, not spelled out: the runner name
        # carries the localhost version, and v1 and v2 must differ
        assert v2.DOCKER_RUNNER_FILE in joined
        assert f'/tmp/{USER_TEMP_DIR}/' in v2.DOCKER_RUNNER_FILE

    def test_container_run_task_uses_docker_exec(self):
        with patch.object(v2, 'get_docker_path', return_value='docker'), \
                patch.object(v2, 'is_podman', return_value=False):
            env = v2.ContainerEnvironment(_config(runtime='img:tag'))
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate.return_value = (b'', b'')
        with patch('lithops.localhost.v2.localhost.sp.Popen', return_value=proc) as popen:
            env.run_task('sess-0-M000', '00000')
        joined = ' '.join(popen.call_args[0][0])
        assert f'docker exec {env.container_name}' in joined
        assert 'run_job' in joined
        assert f'/tmp/{USER_TEMP_DIR}/jobs/sess-0-M000/00000.task' in joined
        assert 'sess-0-M000-00000' not in env.task_processes

    def test_container_setup_pulls_with_docker_path(self):
        with patch.object(v2, 'get_docker_path', return_value='/bin/podman'), \
                patch.object(v2, 'is_podman', return_value=True):
            env = v2.ContainerEnvironment(
                _config(runtime='img:tag', pull_runtime=True)
            )
        with patch.object(env, '_copy_lithops_to_tmp'), \
                patch('lithops.localhost.v2.localhost.sp.run') as run:
            env.setup()
        assert run.call_args[0][0][:3] == ['/bin/podman', 'pull', 'img:tag']

    def test_container_docker_volume_is_posix_and_skips_user_on_windows(self):
        with patch.object(v2, 'get_docker_path', return_value='docker'), \
                patch.object(v2, 'is_podman', return_value=False), \
                patch.object(v2, 'is_unix_system', return_value=False):
            env = v2.ContainerEnvironment(_config(runtime='img:tag'))
        assert env.uid is None
        assert env.gid is None
        cmd = env._container_run_cmd('lithops_win')
        assert '--user' not in cmd
        volume = cmd[cmd.index('-v') + 1]
        assert volume == f'{Path(TEMP_DIR).as_posix()}:/tmp'
        assert '\\' not in volume


class TestV1Environment:

    def test_job_process_not_started_when_job_was_stopped(self):
        env = v1.DefaultEnvironment(_config())
        env.stopped_jobs.add('sess-0-M000')
        with patch('lithops.localhost.v1.localhost.sp.Popen') as popen:
            assert env._start_job_process('sess-0-M000', ['cmd']) is None
        popen.assert_not_called()
        assert 'sess-0-M000' not in env.jobs

    def test_stop_marks_the_job_and_prepare_job_file_clears_it(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            'lithops.localhost.v1.localhost.LITHOPS_TEMP_DIR', str(tmp_path)
        )
        env = v1.DefaultEnvironment(_config())
        proc = MagicMock()
        proc.pid = 42
        env.jobs = {'sess-0-M000': proc}
        with patch('lithops.localhost.utils.kill_process'):
            env.stop(['sess-0-M000'])
        assert 'sess-0-M000' in env.stopped_jobs
        assert 'sess-0-M000' not in env.jobs

        env.prepare_job_file(_job_payload())
        assert 'sess-0-M000' not in env.stopped_jobs

    def test_prepare_job_file_writes_payload_and_returns_local_path(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            'lithops.localhost.v1.localhost.LITHOPS_TEMP_DIR', str(tmp_path)
        )
        env = v1.DefaultEnvironment(_config())
        payload = _job_payload()
        filename = env.prepare_job_file(payload)
        assert filename == os.path.join(
            str(tmp_path), 'storage', JOBS_PREFIX, 'sess-0-M000-job.json'
        )
        with open(filename) as fh:
            assert json.load(fh)['job_key'] == 'sess-0-M000'

    def test_prepare_job_file_returns_docker_path_for_container(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            'lithops.localhost.v1.localhost.LITHOPS_TEMP_DIR', str(tmp_path)
        )
        with patch.object(v1, 'get_docker_path', return_value='docker'), \
                patch.object(v1, 'is_podman', return_value=False):
            env = v1.ContainerEnvironment(_config(runtime='img:tag'))
        filename = env.prepare_job_file(_job_payload())
        assert filename == (
            f'/tmp/{USER_TEMP_DIR}/storage/{JOBS_PREFIX}/sess-0-M000-job.json'
        )
        assert '\\' not in filename
        local = os.path.join(
            str(tmp_path), 'storage', JOBS_PREFIX, 'sess-0-M000-job.json'
        )
        assert os.path.isfile(local)

    def test_default_run_job_stores_process(self):
        env = v1.DefaultEnvironment(_config())
        proc = MagicMock()
        with patch('lithops.localhost.v1.localhost.os.path.isfile', return_value=True), \
                patch('lithops.localhost.v1.localhost.sp.Popen', return_value=proc) as popen:
            assert env.run_job('sess-0-M000', '/tmp/job.json') is proc
        assert popen.call_args[0][0] == [
            'python3', v1.RUNNER_FILE, 'run_job', '/tmp/job.json'
        ]
        assert env.jobs['sess-0-M000'] is proc

    def test_container_run_job_names_container_after_job_key(self):
        with patch.object(v1, 'get_docker_path', return_value='docker'), \
                patch.object(v1, 'is_podman', return_value=False):
            env = v1.ContainerEnvironment(
                _config(runtime='img:tag', use_gpu=True)
            )
        proc = MagicMock()
        with patch('lithops.localhost.v1.localhost.os.path.isfile', return_value=True), \
                patch('lithops.localhost.v1.localhost.sp.Popen', return_value=proc) as popen:
            env.run_job('sess-0-M000', '/tmp/job.json')
        joined = ' '.join(popen.call_args[0][0])
        assert '--name lithops_sess-0-M000' in joined
        assert '--gpus all' in joined
        assert 'run_job /tmp/job.json' in joined
        assert env.jobs['sess-0-M000'] is proc

    def test_container_setup_pulls_with_docker_path(self):
        with patch.object(v1, 'get_docker_path', return_value='/bin/podman'), \
                patch.object(v1, 'is_podman', return_value=True):
            env = v1.ContainerEnvironment(
                _config(runtime='img:tag', pull_runtime=True)
            )
        with patch.object(env, '_copy_lithops_to_tmp'), \
                patch('lithops.localhost.v1.localhost.sp.run') as run:
            env.setup()
        assert run.call_args[0][0][:3] == ['/bin/podman', 'pull', 'img:tag']

    def test_container_docker_volume_is_posix_and_skips_user_on_windows(self):
        with patch.object(v1, 'get_docker_path', return_value='docker'), \
                patch.object(v1, 'is_podman', return_value=False), \
                patch.object(v1, 'is_unix_system', return_value=False):
            env = v1.ContainerEnvironment(_config(runtime='img:tag'))
        assert env.uid is None
        assert env.gid is None
        cmd = env._container_cmd('lithops_win', ['/tmp/job.json'])
        assert '--user' not in cmd
        volume = cmd[cmd.index('-v') + 1]
        assert volume == f'{Path(TEMP_DIR).as_posix()}:/tmp'
        assert '\\' not in volume
        assert '/tmp/job.json' in cmd

    def test_copy_lithops_uses_v1_runner(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'lithops.localhost.v1.localhost.LITHOPS_TEMP_DIR', str(tmp_path)
        )
        monkeypatch.setattr(
            'lithops.localhost.v1.localhost.RUNNER_FILE',
            str(tmp_path / 'localhost-runner.py'),
        )
        monkeypatch.setattr(
            'lithops.localhost.v1.localhost.is_lithops_worker', lambda: False
        )
        env = v1.ExecutionEnvironment(_config())
        with patch('lithops.localhost.v1.localhost.copy_lithops_package') as copy_pkg:
            env._copy_lithops_to_tmp()
        runner_src = copy_pkg.call_args[0][1]
        assert runner_src.endswith(os.path.join('localhost', 'v1', 'runner.py'))

    def test_stop_kills_process_group(self):
        env = v1.DefaultEnvironment(_config())
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 77
        env.jobs['sess-0-M000'] = proc
        env.is_unix_system = True
        with patch('lithops.localhost.utils.os.getpgid', return_value=5), \
                patch('lithops.localhost.utils.os.killpg') as killpg:
            env.stop(['sess-0-M000'])
        killpg.assert_called_once_with(5, signal.SIGKILL)
        assert 'sess-0-M000' not in env.jobs


class TestLocalhostUtils:

    def test_docker_command_helpers(self):
        assert docker_pull_cmd('/bin/podman', 'img:tag') == [
            '/bin/podman', 'pull', 'img:tag'
        ]
        assert docker_rm_cmd('docker', 'lithops_abc') == [
            'docker', 'rm', '-f', 'lithops_abc'
        ]

    def test_docker_run_cmd_volume_is_posix_and_user_is_unix_only(self):
        cmd = docker_run_cmd(
            'docker',
            'img:tag',
            name='lithops_job',
            tmp_path=Path(TEMP_DIR).as_posix(),
        )
        volume = cmd[cmd.index('-v') + 1]
        assert volume == f'{Path(TEMP_DIR).as_posix()}:/tmp'
        assert '\\' not in volume
        assert '--user' not in cmd

        unix_cmd = docker_run_cmd(
            'docker',
            'img:tag',
            name='lithops_job',
            tmp_path='/var/folders/xx/T',
            uid=1000,
            gid=1000,
        )
        assert unix_cmd[unix_cmd.index('--user') + 1] == '1000:1000'
        assert '-v' in unix_cmd
        assert unix_cmd[unix_cmd.index('-v') + 1] == '/var/folders/xx/T:/tmp'

    def test_copy_lithops_package_skips_pycache(self, tmp_path):
        src = tmp_path / 'src' / 'lithops'
        src.mkdir(parents=True)
        (src / 'mod.py').write_text('x = 1\n')
        cache = src / '__pycache__'
        cache.mkdir()
        (cache / 'mod.cpython-312.pyc').write_bytes(b'pyc')
        runner_src = tmp_path / 'runner.py'
        runner_src.write_text('# runner\n')
        dest_root = tmp_path / 'dest'
        copy_lithops_package(
            str(src), str(runner_src), str(dest_root / 'runner.py'), str(dest_root)
        )
        copied = dest_root / 'lithops'
        assert (copied / 'mod.py').is_file()
        assert not (copied / '__pycache__').exists()
        assert (dest_root / 'runner.py').read_text() == '# runner\n'

    def test_copy_lithops_package_always_installs_the_given_runner(
        self, tmp_path
    ):
        """
        The v1 and v2 backends copy a different runner to the same
        destination, so switching between them in one process has to
        replace it. The package tree itself is only copied once
        """
        from lithops.localhost import utils as localhost_utils

        src = tmp_path / 'src' / 'lithops'
        src.mkdir(parents=True)
        (src / 'mod.py').write_text('x = 1\n')
        runner_a = tmp_path / 'a.py'
        runner_a.write_text('# runner A\n')
        runner_b = tmp_path / 'b.py'
        runner_b.write_text('# runner B\n')
        dest_root = tmp_path / 'dest'
        installed = dest_root / 'runner.py'

        copies = []
        real_copytree = localhost_utils.shutil.copytree

        def counting(*args, **kwargs):
            copies.append(1)
            return real_copytree(*args, **kwargs)

        with patch.object(localhost_utils.shutil, 'copytree', counting):
            for runner in (runner_a, runner_b, runner_a):
                copy_lithops_package(
                    str(src), str(runner), str(installed), str(dest_root)
                )
                assert installed.read_text() == runner.read_text()

        assert len(copies) == 1, 'the package tree was copied more than once'
        assert (dest_root / 'lithops' / 'mod.py').is_file()

    def test_copy_lithops_package_recopies_a_changed_source(self, tmp_path):
        """
        A development install changes under a running process, and a cache
        keyed on the path alone would keep serving the tree as it was when
        the first executor of the session started
        """
        from lithops.localhost import utils as localhost_utils

        src = tmp_path / 'src' / 'lithops'
        src.mkdir(parents=True)
        (src / 'mod.py').write_text('x = 1\n')
        runner_src = tmp_path / 'runner.py'
        runner_src.write_text('# runner\n')
        dest_root = tmp_path / 'dest'
        args = (
            str(src), str(runner_src),
            str(dest_root / 'runner.py'), str(dest_root),
        )

        copies = []
        real_copytree = localhost_utils.shutil.copytree

        def counting(*a, **kw):
            copies.append(1)
            return real_copytree(*a, **kw)

        with patch.object(localhost_utils.shutil, 'copytree', counting):
            copy_lithops_package(*args)
            copy_lithops_package(*args)
            assert len(copies) == 1

            (src / 'mod.py').write_text('x = 2\n')
            os.utime(src / 'mod.py', (time.time() + 10, time.time() + 10))
            copy_lithops_package(*args)
            assert len(copies) == 2

        assert (dest_root / 'lithops' / 'mod.py').read_text() == 'x = 2\n'

    def test_copy_lithops_package_recopies_a_missing_tree(self, tmp_path):
        src = tmp_path / 'src' / 'lithops'
        src.mkdir(parents=True)
        (src / 'mod.py').write_text('x = 1\n')
        runner_src = tmp_path / 'runner.py'
        runner_src.write_text('# runner\n')
        dest_root = tmp_path / 'dest'
        args = (
            str(src), str(runner_src),
            str(dest_root / 'runner.py'), str(dest_root),
        )
        copy_lithops_package(*args)
        shutil.rmtree(dest_root / 'lithops')
        copy_lithops_package(*args)
        assert (dest_root / 'lithops' / 'mod.py').is_file()


class TestLocalhostRunners:

    def test_import_does_not_open_log_stream(self):
        assert getattr(v1_runner, 'log_file_stream', None) is None
        assert getattr(v2_runner, 'log_file_stream', None) is None

    def _patch_runner_paths(self, runner, tmp_path, monkeypatch):
        monkeypatch.setattr(runner, 'LITHOPS_TEMP_DIR', str(tmp_path))
        monkeypatch.setattr(runner, 'JOBS_DIR', str(tmp_path / 'jobs'))
        monkeypatch.setattr(runner, 'LOGS_DIR', str(tmp_path / 'logs'))
        monkeypatch.setattr(runner, 'RN_LOG_FILE', str(tmp_path / 'runner.log'))
        monkeypatch.setattr(runner, '_set_fork_start_method', lambda: None)

    def test_v1_unknown_command_exits(self, tmp_path, monkeypatch):
        self._patch_runner_paths(v1_runner, tmp_path, monkeypatch)
        monkeypatch.setattr(sys, 'argv', ['runner.py', 'not-a-command'])
        with pytest.raises(SystemExit) as exc:
            v1_runner.main()
        assert exc.value.code == 1

    def test_v2_unknown_command_exits(self, tmp_path, monkeypatch):
        self._patch_runner_paths(v2_runner, tmp_path, monkeypatch)
        monkeypatch.setattr(sys, 'argv', ['runner.py', 'not-a-command'])
        with pytest.raises(SystemExit) as exc:
            v2_runner.main()
        assert exc.value.code == 1

    def test_v1_run_job_reads_text_json(self, tmp_path, monkeypatch):
        self._patch_runner_paths(v1_runner, tmp_path, monkeypatch)
        job_file = tmp_path / 'job.json'
        job_file.write_text(json.dumps(_job_payload(call_ids=['00000'])))
        monkeypatch.setattr(sys, 'argv', ['runner.py', 'run_job', str(job_file)])
        with patch.object(v1_runner, 'function_handler') as handler:
            v1_runner.main()
        handler.assert_called_once()
        assert handler.call_args[0][0]['job_key'] == 'sess-0-M000'
        assert not job_file.exists()
        assert (tmp_path / 'jobs' / 'sess-0-M000.done').is_file()

    def test_v2_run_job_forces_single_worker_process(self, tmp_path, monkeypatch):
        self._patch_runner_paths(v2_runner, tmp_path, monkeypatch)
        task_file = tmp_path / '00000.task'
        task_file.write_text(json.dumps(_job_payload(call_ids=['00000'])))
        monkeypatch.setattr(sys, 'argv', ['runner.py', 'run_job', str(task_file)])
        with patch.object(v2_runner, 'function_handler') as handler:
            v2_runner.main()
        assert handler.call_args[0][0]['worker_processes'] == 1

    def test_v1_run_job_prints_exception_on_failure(self, tmp_path, monkeypatch):
        self._patch_runner_paths(v1_runner, tmp_path, monkeypatch)
        job_file = tmp_path / 'job.json'
        job_file.write_text(json.dumps(_job_payload(call_ids=['00000'])))
        monkeypatch.setattr(sys, 'argv', ['runner.py', 'run_job', str(job_file)])
        err = io.StringIO()
        monkeypatch.setattr(v1_runner.sys, '__stderr__', err)
        with patch.object(
            v1_runner, 'function_handler', side_effect=RuntimeError('boom')
        ):
            with pytest.raises(SystemExit) as exc:
                v1_runner.main()
        assert exc.value.code == 1
        assert 'RuntimeError: boom' in err.getvalue()


class TestLogProcessFailure:

    def test_decode_bytes_and_str(self):
        assert decode_process_output(b' err \n') == 'err'
        assert decode_process_output(' out ') == 'out'
        assert decode_process_output(None) == ''
        assert decode_process_output(object()) == ''

    def test_logs_stderr_before_runner_file(self, caplog, tmp_path):
        log_file = tmp_path / 'runner.log'
        log_file.write_text('stale runner output\n')
        with caplog.at_level(logging.ERROR):
            log_process_failure(
                logging.getLogger('test-fail'),
                'process failed with return code 1',
                stdout=b'ignored stdout',
                stderr=b'Traceback: boom',
                log_file=str(log_file),
            )
        assert 'process failed with return code 1' in caplog.text
        assert 'Traceback: boom' in caplog.text
        assert 'stale runner output' not in caplog.text

    def test_falls_back_to_runner_log_tail(self, caplog, tmp_path):
        log_file = tmp_path / 'runner.log'
        log_file.write_text('ModuleNotFoundError: numcodecs\n')
        with caplog.at_level(logging.ERROR):
            log_process_failure(
                logging.getLogger('test-fail'),
                'process failed with return code 1',
                stdout=b'',
                stderr=b'',
                log_file=str(log_file),
            )
        assert 'Runner log' in caplog.text
        assert 'numcodecs' in caplog.text


class TestLocalhostStorageBackend:

    @pytest.fixture
    def backend(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'lithops.storage.backends.localhost.localhost.LITHOPS_TEMP_DIR',
            str(tmp_path),
        )
        return LocalhostStorageBackend({}), tmp_path

    def test_put_get_bytes_str_and_stream(self, backend):
        storage, _ = backend
        storage.put_object('bucket', 'bytes.bin', b'abc')
        storage.put_object('bucket', 'text.txt', 'hello')
        storage.put_object('bucket', 'stream.bin', io.BytesIO(b'xyz'))
        assert storage.get_object('bucket', 'bytes.bin') == b'abc'
        assert storage.get_object('bucket', 'text.txt') == b'hello'
        stream = storage.get_object('bucket', 'stream.bin', stream=True)
        assert stream.read() == b'xyz'

    def test_get_missing_key_raises(self, backend):
        storage, _ = backend
        with pytest.raises(StorageNoSuchKeyError):
            storage.get_object('bucket', 'missing')

    def test_boto3_client_wraps_put_get_and_list(self, backend):
        storage, _ = backend
        client = storage.get_client()
        client.put_object(Bucket='bucket', Key='k', Body=b'v')
        assert client.get_object(Bucket='bucket', Key='k')['Body'].read() == b'v'
        listed = client.list_objects(Bucket='bucket', Prefix='k')
        listed_v2 = client.list_objects_v2(Bucket='bucket', Prefix='k')
        assert listed == listed_v2
        assert listed[0]['Key'] == 'k'
        assert listed[0]['Size'] == 1

    def test_upload_and_download_file(self, backend, tmp_path):
        storage, _ = backend
        src = tmp_path / 'src.txt'
        src.write_bytes(b'file-data')
        assert storage.upload_file(str(src), 'bucket') is True
        dest = tmp_path / 'out' / 'dest.txt'
        assert storage.download_file('bucket', 'src.txt', str(dest)) is True
        assert dest.read_bytes() == b'file-data'
        assert storage.upload_file(str(tmp_path / 'missing.txt'), 'bucket') is False
        assert storage.download_file('bucket', 'nope', str(tmp_path / 'x')) is False

    def test_head_object_and_bucket(self, backend):
        storage, tmp_path = backend
        with pytest.raises(StorageNoSuchKeyError):
            storage.head_bucket('bucket')
        storage.put_object('bucket', 'dir/key', b'abcd')
        assert storage.head_bucket('bucket')['ResponseMetadata']['HTTPStatusCode'] == 200
        assert storage.head_object('bucket', 'dir/key') == {'content-length': '4'}
        with pytest.raises(StorageNoSuchKeyError):
            storage.head_object('bucket', 'missing')

    def test_delete_object_removes_empty_parents_but_keeps_bucket(self, backend):
        storage, tmp_path = backend
        storage.put_object('bucket', 'a/b/c.txt', b'x')
        storage.delete_object('bucket', 'a/b/c.txt')
        bucket_dir = tmp_path / 'bucket'
        assert bucket_dir.is_dir()
        assert not (bucket_dir / 'a').exists()


class TestLocalhostV1Live:
    """Live check that version=1 still runs a job end to end."""

    def test_map_with_localhost_v1(self):
        cfg = copy.deepcopy(pytest.lithops_config)
        cfg.setdefault('localhost', {})
        cfg['localhost']['version'] = 1
        fexec = lithops.FunctionExecutor(config=cfg)
        assert isinstance(fexec.compute_handler, LocalhostHandlerV1)
        fexec.map(simple_map_function, [(1, 1)])
        assert fexec.get_result(timeout=20) == [2]

    def test_second_job_survives_the_cleanup_of_the_first(self):
        cfg = copy.deepcopy(pytest.lithops_config)
        cfg.setdefault('localhost', {})
        cfg['localhost']['version'] = 1
        fexec = lithops.FunctionExecutor(config=cfg)
        # v1 runs one job at a time, so the second waits for the first. The
        # scoped drain itself is covered by the unit tests: here the window
        # where the second job is still queued is too narrow to force
        first = fexec.map(sleep_seconds, [1])
        second = fexec.map(simple_map_function, [(2, 2)])
        assert fexec.get_result(fs=first, timeout=20) == [1]
        assert fexec.get_result(fs=second, timeout=20) == [4]

    def test_map_with_localhost_v1_multi_worker(self):
        cfg = copy.deepcopy(pytest.lithops_config)
        cfg.setdefault('localhost', {})
        cfg['localhost']['version'] = 1
        cfg['localhost']['worker_processes'] = 2
        fexec = lithops.FunctionExecutor(config=cfg)
        fexec.map(simple_map_function, [(1, 1), (2, 2)])
        assert fexec.get_result(timeout=20) == [2, 4]


class TestLocalhostV2Live:
    """Live checks that version=2 keeps running jobs across cleanups."""

    def test_map_after_wait_and_get_result(self):
        # Every wait() cleans its jobs up, and a cleanup used to leave
        # sentinels in the work queue that killed the next consumers
        cfg = copy.deepcopy(pytest.lithops_config)
        cfg.setdefault('localhost', {})
        cfg['localhost']['version'] = 2
        fexec = lithops.FunctionExecutor(config=cfg)
        assert isinstance(fexec.compute_handler, LocalhostHandlerV2)
        fexec.map(simple_map_function, [(1, 1)])
        fexec.wait()
        assert fexec.get_result(timeout=20) == [2]
        fexec.map(simple_map_function, [(2, 2)])
        assert fexec.get_result(timeout=20) == [4]

    def test_second_job_survives_the_cleanup_of_the_first(self):
        cfg = copy.deepcopy(pytest.lithops_config)
        cfg.setdefault('localhost', {})
        cfg['localhost']['version'] = 2
        cfg['localhost']['worker_processes'] = 1
        fexec = lithops.FunctionExecutor(config=cfg)
        first = fexec.map(simple_map_function, [(1, 1)])
        # More tasks than consumers, so some are still queued when the first
        # job is cleaned up: that cleanup must not drop them
        second = fexec.map(sleep_seconds, [1, 1, 1])
        assert fexec.get_result(fs=first, timeout=20) == [2]
        assert fexec.get_result(fs=second, timeout=30) == [1, 1, 1]


def _container_cli():
    return shutil.which('docker') or shutil.which('podman')


def _docker_daemon_available():
    cli = _container_cli()
    if not cli:
        return False
    try:
        sp.run(
            [cli, 'info'],
            check=True,
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
            timeout=15,
        )
        return True
    except Exception:
        return False


def _python_hub_image():
    return f'python:{sys.version_info.major}.{sys.version_info.minor}'


def _ensure_localhost_python_image():
    """Official python:X.Y plus the worker packages Lithops imports at runtime."""
    cli = _container_cli()
    base = _python_hub_image()
    tag = f'lithops-pytest-{base}'
    inspect = sp.run(
        [cli, 'image', 'inspect', tag],
        stdout=sp.DEVNULL,
        stderr=sp.DEVNULL,
    )
    if inspect.returncode == 0:
        return tag
    dockerfile = '\n'.join([
        f'FROM {base}',
        'RUN pip install --no-cache-dir '
        'cloudpickle tblib pika PyYAML requests tqdm six psutil ps-mem',
    ])
    sp.run(
        [cli, 'build', '-t', tag, '-'],
        input=dockerfile,
        check=True,
        text=True,
    )
    return tag


@pytest.mark.skipif(
    not _docker_daemon_available(),
    reason='docker/podman is not installed or the daemon is not running',
)
class TestLocalhostContainerLive:
    """Live localhost jobs inside a Docker Hub python:X.Y container."""

    def test_map_in_python_container(self):
        image = _ensure_localhost_python_image()
        cfg = copy.deepcopy(pytest.lithops_config)
        cfg.setdefault('lithops', {})
        cfg['lithops']['backend'] = 'localhost'
        cfg['lithops']['mode'] = 'localhost'
        cfg['lithops']['storage'] = 'localhost'
        cfg['lithops']['monitoring'] = 'storage'
        cfg.setdefault('localhost', {})
        cfg['localhost']['runtime'] = image
        cfg['localhost']['pull_runtime'] = False

        with lithops.FunctionExecutor(config=cfg) as fexec:
            assert (
                fexec.compute_handler.environment
                is localhost_config.LocalhostEnvironment.CONTAINER
            )
            fexec.map(simple_map_function, [(2, 3), (4, 5)])
            assert fexec.get_result(timeout=180) == [5, 9]
