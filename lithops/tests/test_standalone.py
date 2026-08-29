#
# Unit tests for the standalone compute frontend (not cloud backends).
#

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from lithops.standalone import LithopsValidationError, StandaloneHandler
from lithops.standalone import __all__ as standalone_all
from lithops.standalone.keeper import BudgetKeeper
from lithops.standalone.runner import main as runner_main
from lithops.standalone.standalone import StandaloneHandler as HandlerCls
from lithops.standalone.utils import (
    docker_login,
    JobStatus,
    LithopsValidationError as UtilsError,
    StandaloneMode,
    _format_apt_packages_for_shell,
    get_host_setup_script,
    get_master_setup_script,
    get_worker_setup_script,
    is_container_runtime,
    lithops_pip_spec_from_config,
)
from lithops.utils import BackendType
from lithops.version import __version__


def _handler_config(exec_mode='consume', **extra):
    cfg = {
        'backend': 'vm',
        'exec_mode': exec_mode,
        'start_timeout': 5,
        'runtime': 'python3',
        'hard_dismantle_timeout': 60,
        'vm': {'max_workers': 2},
    }
    cfg.update(extra)
    return cfg


def _make_handler(exec_mode='consume', **extra):
    fake_backend = MagicMock()
    fake_module = MagicMock()
    fake_module.StandaloneBackend.return_value = fake_backend
    with patch(
        'lithops.standalone.standalone.importlib.import_module',
        return_value=fake_module,
    ):
        handler = StandaloneHandler(_handler_config(exec_mode, **extra))
    handler.backend = fake_backend
    return handler


def _keeper_config(**extra):
    cfg = {
        'auto_dismantle': True,
        'soft_dismantle_timeout': 10,
        'hard_dismantle_timeout': 20,
        'exec_mode': 'reuse',
    }
    cfg.update(extra)
    return cfg


def _make_keeper(**keeper_kwargs):
    instance = MagicMock()
    instance.name = 'worker-1'
    instance.private_ip = '10.0.0.8'
    instance.instance_id = 'i-1'
    instance.delete_on_dismantle = False
    with patch('lithops.standalone.keeper.StandaloneHandler') as handler_cls:
        handler_cls.return_value.backend.get_instance.return_value = instance
        keeper = BudgetKeeper(_keeper_config(), {'name': 'worker-1'}, **keeper_kwargs)
    keeper.instance = instance
    return keeper, instance


class TestStandaloneExports:

    def test_all_is_string_names(self):
        assert standalone_all == ['StandaloneHandler', 'LithopsValidationError']
        assert LithopsValidationError is UtilsError
        assert HandlerCls is StandaloneHandler


class TestStandaloneUtils:

    def test_pip_spec_defaults_and_cloud_extras(self):
        assert lithops_pip_spec_from_config(None) == 'lithops'
        assert lithops_pip_spec_from_config({}) == 'lithops'
        assert lithops_pip_spec_from_config({'backend': 'localhost'}) == (
            'lithops[redis]'
        )
        spec = lithops_pip_spec_from_config({'lithops': {'backend': 'aws_ec2'}})
        assert spec == 'lithops[aws,redis]'

    def test_apt_packages_reject_invalid_names(self):
        with pytest.raises(LithopsValidationError, match='apt package'):
            _format_apt_packages_for_shell('foo; rm -rf /')

    def test_docker_login_is_empty_without_credentials(self):
        assert docker_login({'backend': 'vm', 'vm': {}}) == ''
        assert docker_login(
            {'backend': 'vm', 'vm': {'docker_user': 'me'}}
        ) == ''

    def test_docker_login_keeps_the_password_out_of_the_process_list(self):
        script = docker_login({'backend': 'vm', 'vm': {
            'docker_server': 'reg.io',
            'docker_user': 'me',
            'docker_password': 'secret',
        }})
        # -p would show the password to anyone running ps on the VM
        assert '--password-stdin' in script
        assert '-p secret' not in script
        assert 'docker login -u me' in script
        assert '/opt/lithops/setup.log' in script

    def test_docker_login_quotes_the_credentials_it_is_given(self):
        # Unquoted, the ; would run "rd" as a command on the VM
        script = docker_login({'backend': 'vm', 'vm': {
            'docker_server': 'reg.io',
            'docker_user': 'me',
            'docker_password': 'p@ss w;rd',
        }})
        assert "'p@ss w;rd'" in script
        assert '; rd' not in script.replace("'p@ss w;rd'", '')

    def test_container_runtime_detects_docker_tags(self):
        assert is_container_runtime('python3') is False
        assert is_container_runtime('/usr/bin/python3') is False
        assert is_container_runtime('python:3.12') is True
        assert is_container_runtime('lithops/python:3.12') is True

    def test_worker_setup_script_uses_native_python(self):
        script = get_worker_setup_script(
            {'backend': 'vm', 'runtime': 'python3', 'use_gpu': False, 'vm': {}},
            {'master_ip': '10.0.0.1'},
        )
        assert '/usr/bin/python3' in script
        assert 'docker run --rm --name lithops_worker' not in script

    def test_worker_setup_script_uses_docker_for_tagged_python(self):
        script = get_worker_setup_script(
            {
                'backend': 'vm',
                'runtime': 'python:3.12',
                'use_gpu': True,
                'vm': {},
            },
            {'master_ip': '10.0.0.1'},
        )
        assert 'docker run --rm --name lithops_worker' in script
        assert '--gpus all' in script
        assert 'python:3.12' in script
        assert '-v /opt/lithops:/opt/lithops' in script
        assert '-v /tmp:/tmp' in script
        assert '/opt/lithops/worker.py' in script
        assert '\\opt\\lithops' not in script
        assert '\\tmp\\' not in script

    def test_host_and_master_setup_scripts_use_posix_remote_paths(self):
        host = get_host_setup_script()
        assert host.startswith('#!/bin/bash')
        assert 'mkdir -p /opt/lithops' in host
        assert '/opt/lithops/setup.log' in host
        assert '/opt/lithops/setup-done.flag' in host
        assert '\\opt\\lithops' not in host

        master = get_master_setup_script(
            {'backend': 'vm', 'vm': {}},
            {'master_ip': '10.0.0.1'},
        )
        assert 'unzip -o /tmp/lithops_standalone.zip -d /opt/lithops' in master
        assert '/opt/lithops/master.data' in master
        assert '/opt/lithops/config' in master
        assert '\\opt\\lithops' not in master
        assert '\\tmp\\lithops_standalone.zip' not in master


class TestBudgetKeeper:

    def test_running_attribute_and_job_tracking(self):
        keeper, _instance = _make_keeper()
        assert keeper.running is False
        assert not hasattr(keeper, 'runing')
        keeper.add_job('job-a')
        assert keeper.jobs['job-a'] == JobStatus.RUNNING.value
        keeper.set_job_done('job-a')
        assert keeper.jobs['job-a'] == JobStatus.DONE.value
        assert keeper._all_jobs_done() is True

    def test_mark_finished_jobs_survives_a_concurrent_add(self):
        # The service adds jobs from its own threads, so iterating the dict
        # itself would raise "dictionary changed size during iteration" and
        # kill the keeper, leaving the instance running forever
        keeper, _instance = _make_keeper()
        keeper.add_job('job-a')

        real_isfile = os.path.isfile

        def isfile(path):
            keeper.jobs[f'job-{len(keeper.jobs)}'] = JobStatus.RUNNING.value
            return real_isfile(path)

        with patch('lithops.standalone.keeper.os.path.isfile', side_effect=isfile):
            keeper._mark_finished_jobs()
        assert len(keeper.jobs) > 1

    def test_stop_instance_calls_stop_callback(self):
        stop = MagicMock()
        delete = MagicMock()
        keeper, instance = _make_keeper(stop_callback=stop, delete_callback=delete)
        instance.delete_on_dismantle = False
        keeper.stop_instance()
        stop.assert_called_once()
        delete.assert_not_called()
        instance.stop.assert_called_once()
        assert keeper.running is False

    def test_stop_instance_calls_delete_callback(self):
        stop = MagicMock()
        delete = MagicMock()
        keeper, instance = _make_keeper(stop_callback=stop, delete_callback=delete)
        instance.delete_on_dismantle = True
        keeper.stop_instance()
        delete.assert_called_once()
        stop.assert_not_called()


class TestStandaloneHandler:

    def test_backend_type_and_runtime_info(self):
        handler = _make_handler()
        assert handler.get_backend_type() == BackendType.BATCH.value
        assert handler.exec_mode is StandaloneMode.CONSUME
        assert handler.get_runtime_info() == {
            'runtime_name': 'python3',
            'runtime_memory': None,
            'runtime_timeout': 60,
            'max_workers': 2,
        }

    def test_build_image_defaults_extra_args_to_empty_list(self):
        handler = _make_handler()
        handler.build_image('img', None, False, None)
        handler.backend.build_image.assert_called_once_with(
            'img', None, False, None, []
        )

    def test_get_runtime_key_delegates_to_backend(self):
        handler = _make_handler()
        handler.backend.get_runtime_key.return_value = 'key'
        assert handler.get_runtime_key('python3', None) == 'key'
        handler.backend.get_runtime_key.assert_called_once_with(
            'python3', __version__
        )

    def test_master_ready_rejects_version_mismatch(self):
        handler = _make_handler()
        handler._make_request = MagicMock(return_value={'response': '0.0.0'})
        with pytest.raises(LithopsValidationError, match='doesn\'t match'):
            handler._is_master_service_ready()

    def test_create_workers_zero_is_noop(self):
        handler = _make_handler('create')
        assert handler._create_workers(0, 'e', 'M000') == []
        handler.backend.create_worker.assert_not_called()

    def test_invoke_consume_uses_master_as_worker(self):
        handler = _make_handler('consume')
        master = MagicMock()
        master.name = 'master'
        master.private_ip = '10.0.0.2'
        master.instance_id = 'i-m'
        master.ssh_credentials = {'username': 'ubuntu'}
        master.instance_type = 'unused'
        handler.backend.master = master
        handler._is_master_service_ready = MagicMock(return_value=True)
        handler._make_request = MagicMock()
        payload = {
            'executor_id': 'sess-0',
            'job_id': 'M000',
            'job_key': 'sess-0-M000',
            'total_calls': 2,
            'worker_processes': 1,
            'config': {'lithops': {'backend': 'vm'}, 'vm': {'ssh_key_filename': 'k'}},
        }
        handler.invoke(payload)
        assert payload['worker_instances'] == [{
            'name': 'master',
            'private_ip': '10.0.0.2',
            'instance_id': 'i-m',
            'ssh_credentials': {'username': 'ubuntu'},
            'instance_type': 'unused',
        }]
        assert 'ssh_key_filename' not in payload['config']['vm']
        handler._make_request.assert_called_once_with('POST', 'job/run', payload)
        assert handler.jobs == ['sess-0-M000']

    def _create_payload(self, **extra):
        payload = {
            'executor_id': 'sess-0',
            'job_id': 'M000',
            'job_key': 'sess-0-M000',
            'total_calls': 5,
            'worker_processes': 2,
            'max_workers': 10,
            'runtime_name': 'python3',
            'config': {'lithops': {'backend': 'vm'}, 'vm': {}},
        }
        payload.update(extra)
        return payload

    def _ready_handler(self, mode):
        handler = _make_handler(mode)
        handler.backend.get_worker_instance_type.return_value = 'big'
        handler.backend.get_worker_cpu_count.return_value = 2
        handler._is_master_service_ready = MagicMock(return_value=True)
        handler._make_request = MagicMock(return_value=[])
        return handler

    def test_invoke_create_rounds_workers_up(self):
        handler = self._ready_handler('create')
        created = []

        def create_workers(count, executor_id, job_id):
            created.append((count, executor_id, job_id))
            return [MagicMock(name=f'w{n}') for n in range(count)]

        handler._create_workers = MagicMock(side_effect=create_workers)
        payload = self._create_payload()
        handler.invoke(payload)
        # 5 calls over 2 processes per worker needs 3 workers
        assert created == [(3, 'sess-0', 'M000')]
        assert payload['worker_instance_type'] == 'big'
        assert len(payload['worker_instances']) == 3

    def test_invoke_create_caps_workers_at_max_workers(self):
        handler = self._ready_handler('create')
        handler._create_workers = MagicMock(return_value=[MagicMock()])
        handler.invoke(self._create_payload(total_calls=100, max_workers=4))
        assert handler._create_workers.call_args[0][0] == 4

    def test_invoke_create_resolves_auto_worker_processes(self):
        handler = self._ready_handler('create')
        handler._create_workers = MagicMock(return_value=[MagicMock()])
        payload = self._create_payload(worker_processes='AUTO')
        handler.invoke(payload)
        assert payload['worker_processes'] == 2
        assert payload['config']['vm']['worker_processes'] == 2

    def test_invoke_reuse_only_creates_the_missing_workers(self):
        handler = self._ready_handler('reuse')
        handler._get_workers_on_master = MagicMock(return_value=['w1'])
        handler._create_workers = MagicMock(return_value=[MagicMock()])
        handler.invoke(self._create_payload())
        # 3 needed, 1 already free on the master
        assert handler._create_workers.call_args[0][0] == 2

    def test_invoke_reuse_creates_nothing_when_enough_workers(self):
        handler = self._ready_handler('reuse')
        handler._get_workers_on_master = MagicMock(
            return_value=['w1', 'w2', 'w3']
        )
        handler._create_workers = MagicMock()
        payload = self._create_payload()
        handler.invoke(payload)
        handler._create_workers.assert_not_called()
        assert payload['worker_instances'] == []

    def test_invoke_raises_when_no_worker_could_be_created(self):
        handler = self._ready_handler('create')
        handler._create_workers = MagicMock(return_value=[])
        with pytest.raises(Exception, match='not possible to create any workers'):
            handler.invoke(self._create_payload())

    def test_invoke_sets_up_the_master_when_it_is_not_ready(self):
        handler = self._ready_handler('consume')
        handler._is_master_service_ready = MagicMock(return_value=False)
        handler._validate_master_service_setup = MagicMock()
        handler._wait_master_service_ready = MagicMock()
        handler.invoke(self._create_payload(worker_processes=1))
        handler.backend.master.create.assert_called_once_with(check_if_exists=True)
        handler.backend.master.wait_ready.assert_called_once()
        handler._validate_master_service_setup.assert_called_once()
        handler._wait_master_service_ready.assert_called_once()

    def test_request_from_worker_uses_lithops_master_host(self):
        handler = _make_handler()
        handler.is_lithops_worker = True
        with patch('lithops.standalone.standalone.requests.get') as get:
            get.return_value.json.return_value = {'response': __version__}
            assert handler._make_request('GET', 'ping') == {
                'response': __version__
            }
        assert 'lithops-master' in get.call_args[0][0]

    def test_request_from_worker_accepts_an_empty_post_body(self):
        handler = _make_handler()
        handler.is_lithops_worker = True
        with patch('lithops.standalone.standalone.requests.post') as post:
            post.return_value.content = b''
            assert handler._make_request(
                'POST', 'job/stop', ['sess-0-M000']
            ) is None
        post.return_value.raise_for_status.assert_called_once()

    def test_request_via_ssh_accepts_an_empty_response(self):
        # /job/stop and /clean answer 204 with no body. curl used to print
        # its progress meter on stderr, which was raised as a failure
        handler = _make_handler()
        ssh = handler.backend.master.get_ssh_client.return_value
        ssh.run_remote_command.return_value = ('', '')
        assert handler._make_request(
            'POST', 'job/stop', ['sess-0-M000']
        ) is None
        cmd = ssh.run_remote_command.call_args[0][0]
        assert cmd.startswith('curl -sS ')
        assert 'job/stop' in cmd

    def test_request_via_ssh_raises_when_curl_prints_an_error(self):
        handler = _make_handler()
        ssh = handler.backend.master.get_ssh_client.return_value
        ssh.run_remote_command.return_value = (
            '', 'curl: (7) Failed to connect'
        )
        with pytest.raises(ValueError, match='Failed to connect'):
            handler._make_request('POST', 'job/stop', ['sess-0-M000'])

    def test_request_via_ssh_parses_a_json_body(self):
        handler = _make_handler()
        ssh = handler.backend.master.get_ssh_client.return_value
        ssh.run_remote_command.return_value = ('{"response": "ok"}', '')
        assert handler._make_request('GET', 'ping') == {'response': 'ok'}

    def test_clear_logs_that_jobs_were_stopped(self):
        handler = _make_handler('reuse')
        handler.jobs = ['sess-0-M000']
        handler._make_request = MagicMock(return_value=None)
        with patch('lithops.standalone.standalone.logger') as log:
            handler.clear()
        handler._make_request.assert_called_once_with(
            'POST', 'job/stop', ['sess-0-M000']
        )
        log.debug.assert_called_once_with('Jobs stopped on the master')
        handler.backend.clear.assert_not_called()

    def test_clear_logs_when_the_master_cannot_be_reached(self):
        handler = _make_handler('reuse')
        handler._make_request = MagicMock(side_effect=ValueError('down'))
        with patch('lithops.standalone.standalone.logger') as log:
            handler.clear()
        log.debug.assert_called_once()
        assert log.debug.call_args[0][0].startswith(
            'Could not stop the jobs on the master:'
        )


class TestStandaloneRunner:

    def test_import_does_not_open_log_stream(self):
        from lithops.standalone import runner as sa_runner
        assert getattr(sa_runner, 'log_file_stream', None) is None

    def test_run_job_reads_text_json(self, tmp_path, monkeypatch):
        from lithops.standalone import runner as sa_runner
        monkeypatch.setattr(sa_runner, 'RN_LOG_FILE', str(tmp_path / 'rn.log'))
        task = tmp_path / 'task.json'
        task.write_text(json.dumps({
            'executor_id': 'sess-0',
            'job_id': 'M000',
            'call_ids': ['00000'],
        }))
        monkeypatch.setattr(sys, 'argv', ['runner.py', 'aws_ec2', str(task)])
        monkeypatch.setenv('__LITHOPS_BACKEND', '')
        monkeypatch.setenv('__LITHOPS_ACTIVATION_ID', '')
        with patch.object(sa_runner, 'function_handler') as handler:
            runner_main()
        payload = handler.call_args[0][0]
        assert payload['worker_processes'] == 1
        assert os.environ['__LITHOPS_BACKEND'] == 'AWS EC2'


class TestStandaloneMasterWorkerHttp:
    """These tests need flask, which is not required for localhost runs."""

    @pytest.fixture(autouse=True)
    def _need_flask(self):
        pytest.importorskip('flask')

    def test_master_rejects_non_dict_metadata(self):
        from lithops.standalone import master as sa_master
        sa_master.budget_keeper = MagicMock()
        client = sa_master.app.test_client()
        resp = client.get('/metadata', json=['not-a-dict'])
        assert resp.status_code == 404
        assert 'dictionary' in resp.get_json()['error']

    def test_master_map_if_any_reports_failures_without_raising(self):
        from lithops.standalone import master as sa_master

        def boom(item):
            raise RuntimeError(f'no {item}')

        with patch.object(sa_master, 'logger') as log:
            sa_master._map_if_any(boom, ['worker:a', 'worker:b'])
        assert log.error.call_count == 2
        assert 'no worker:a' in log.error.call_args_list[0][0][0]

    def test_master_cancel_job_survives_an_emptied_queue(self):
        from lithops.standalone import master as sa_master
        redis_client = MagicMock()
        redis_client.hget.return_value = 'wq:sess-0-M000'
        # A worker took the last task between llen() and rpop()
        redis_client.llen.return_value = 1
        redis_client.rpop.return_value = None
        redis_client.keys.return_value = []
        with patch.object(sa_master, 'redis_client', redis_client):
            sa_master.cancel_job_process(['sess-0-M000'])
        redis_client.rpop.assert_called_once()

    def test_master_cancel_job_skips_a_job_with_no_queue(self):
        from lithops.standalone import master as sa_master
        redis_client = MagicMock()
        redis_client.hget.return_value = None
        with patch.object(sa_master, 'redis_client', redis_client):
            sa_master.cancel_job_process(['sess-0-M000'])
        redis_client.llen.assert_not_called()

    def test_worker_ping_counts_idle_and_busy(self):
        from lithops.standalone import worker as sa_worker
        from lithops.standalone.utils import WorkerStatus
        sa_worker.worker_threads = {
            0: {'status': WorkerStatus.IDLE.value},
            1: {'status': WorkerStatus.BUSY.value},
            2: {'status': WorkerStatus.IDLE.value},
        }
        client = sa_worker.app.test_client()
        assert client.get('/ping').get_json() == {'busy': 1, 'free': 2}

    def test_worker_stop_survives_a_concurrent_task_registration(self):
        from lithops.standalone import worker as sa_worker
        # The consumer threads add and remove entries while this route runs,
        # so iterating the dict itself raised "dictionary changed size during
        # iteration" and failed the stop request
        proc = MagicMock()
        proc.pid = 7
        sa_worker.job_processes = {'sess-0-M000-00000': proc}
        sa_worker.canceled = []

        def kill(process):
            sa_worker.job_processes['sess-0-M000-00001'] = MagicMock()

        client = sa_worker.app.test_client()
        with patch.object(sa_worker, '_kill_process_group', side_effect=kill), \
                patch.object(sa_worker.Path, 'touch'):
            resp = client.post('/stop/sess-0-M000')

        assert resp.status_code == 200
        assert 'sess-0-M000' in sa_worker.canceled
        assert 'sess-0-M000-00000' not in sa_worker.job_processes

    def test_worker_ttd_disabled_without_keeper(self):
        from lithops.standalone import worker as sa_worker
        sa_worker.budget_keeper = None
        client = sa_worker.app.test_client()
        resp = client.get('/ttd')
        assert resp.status_code == 200
        assert resp.get_data(as_text=True) == 'Disabled'

    def test_wait_for_task_in_reuse_mode_polls_with_a_timeout(self):
        from lithops.standalone import worker as sa_worker
        redis_client = MagicMock()
        redis_client.brpop.return_value = None
        with patch.object(sa_worker, 'redis_client', redis_client):
            assert sa_worker._wait_for_task(
                'wq:t3.micro-2-python3', StandaloneMode.REUSE.value
            ) is None
        redis_client.brpop.assert_called_once_with(
            'wq:t3.micro-2-python3', timeout=sa_worker._QUEUE_POLL_TIMEOUT
        )
        redis_client.rpop.assert_not_called()

    def test_wait_for_task_in_reuse_mode_returns_the_payload(self):
        from lithops.standalone import worker as sa_worker
        redis_client = MagicMock()
        redis_client.brpop.return_value = ('wq', '{"call_ids": ["00000"]}')
        with patch.object(sa_worker, 'redis_client', redis_client):
            assert sa_worker._wait_for_task(
                'wq', StandaloneMode.CONSUME.value
            ) == '{"call_ids": ["00000"]}'

    def test_wait_for_task_in_create_mode_stops_on_an_empty_queue(self):
        from lithops.standalone import worker as sa_worker
        redis_client = MagicMock()
        redis_client.rpop.return_value = None
        with patch.object(sa_worker, 'redis_client', redis_client):
            assert sa_worker._wait_for_task(
                'wq', StandaloneMode.CREATE.value
            ) is None
        redis_client.rpop.assert_called_once_with('wq')
        redis_client.brpop.assert_not_called()

    def test_consumer_stays_idle_across_empty_reuse_polls(self):
        from lithops.standalone import worker as sa_worker
        from lithops.standalone.utils import WorkerStatus

        class StopConsumer(BaseException):
            pass

        sa_worker.worker_threads = {0: {'status': None}}
        polls = {'n': 0}

        def wait(queue_name, exec_mode):
            polls['n'] += 1
            assert sa_worker.worker_threads[0]['status'] == WorkerStatus.IDLE.value
            if polls['n'] < 3:
                return None
            raise StopConsumer

        with patch.object(sa_worker, '_wait_for_task', side_effect=wait):
            try:
                sa_worker.redis_queue_consumer(
                    0, 'wq', StandaloneMode.REUSE.value, 'aws_ec2'
                )
            except StopConsumer:
                pass

        assert polls['n'] == 3
        assert sa_worker.worker_threads[0]['status'] == WorkerStatus.IDLE.value

    def test_consumer_retries_after_a_lost_redis_connection(self):
        from lithops.standalone import worker as sa_worker
        from lithops.standalone.utils import WorkerStatus

        class StopConsumer(BaseException):
            pass

        sa_worker.worker_threads = {0: {'status': None}}
        polls = {'n': 0}

        def wait(queue_name, exec_mode):
            polls['n'] += 1
            if polls['n'] == 1:
                raise ConnectionError('timed out')
            raise StopConsumer

        with patch.object(sa_worker, '_wait_for_task', side_effect=wait), \
                patch.object(sa_worker.time, 'sleep'):
            try:
                sa_worker.redis_queue_consumer(
                    0, 'wq', StandaloneMode.REUSE.value, 'aws_ec2'
                )
            except StopConsumer:
                pass

        assert polls['n'] == 2
        assert sa_worker.worker_threads[0]['status'] == WorkerStatus.IDLE.value
