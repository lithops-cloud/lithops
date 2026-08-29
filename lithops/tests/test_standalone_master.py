#
# Unit tests for the standalone master service (not cloud backends).
#
# The master runs as a Flask service on the master VM, keeps its state in
# redis, and reaches the workers over HTTP, so every test here drives it with
# those three replaced.
#

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from lithops.standalone.utils import JobStatus, StandaloneMode, WorkerStatus
from lithops.version import __version__

pytest.importorskip('flask')
pytest.importorskip('gevent')
pytest.importorskip('redis')

from lithops.standalone import master as sa_master  # noqa: E402


@pytest.fixture(autouse=True)
def master_globals():
    """
    Gives the module its globals back after each test: they are module level
    and the service sets them once, in main()
    """
    saved = (
        sa_master.redis_client,
        sa_master.budget_keeper,
        sa_master.master_ip,
    )
    sa_master.redis_client = MagicMock()
    sa_master.budget_keeper = MagicMock()
    sa_master.master_ip = '10.0.0.1'
    yield
    (
        sa_master.redis_client,
        sa_master.budget_keeper,
        sa_master.master_ip,
    ) = saved


@pytest.fixture
def client():
    return sa_master.app.test_client()


def _worker_instance(name='lithops-worker-1', **extra):
    worker = MagicMock()
    worker.name = name
    worker.private_ip = extra.get('private_ip', '10.0.0.2')
    worker.instance_id = extra.get('instance_id', 'i-1')
    worker.instance_type = extra.get('instance_type', 'big')
    worker.ssh_credentials = {'username': 'ubuntu'}
    worker.config = extra.get('config', {'worker_processes': 2})
    return worker


def _standalone_config(**extra):
    cfg = {
        'backend': 'vm',
        'exec_mode': StandaloneMode.CREATE.value,
        'runtime': 'python3',
        'vm': {'secret': 'do-not-store'},
    }
    cfg.update(extra)
    return cfg


class TestMasterEndpoints:

    def test_ping_answers_with_the_lithops_version(self, client):
        resp = client.get('/ping')
        assert resp.status_code == 200
        assert resp.get_json() == {'response': __version__}

    def test_error_reports_the_message(self):
        with sa_master.app.app_context():
            resp = sa_master.error('nope')
        assert resp.status_code == 404
        assert resp.get_json() == {'error': 'nope'}

    def test_clean_drops_everything_in_redis(self, client):
        resp = client.post('/clean')
        assert resp.status_code == 204
        sa_master.redis_client.flushall.assert_called_once()

    def test_metadata_rejects_a_body_that_is_not_a_dict(self, client):
        resp = client.get('/metadata', json=['not-a-dict'])
        assert resp.status_code == 404
        assert 'dictionary' in resp.get_json()['error']

    def test_metadata_rejects_an_invalid_runtime_name(self, client):
        # A space cannot appear in a container image name
        resp = client.get('/metadata', json={'runtime': 'has space'})
        assert resp.status_code == 404
        assert 'not valid' in resp.get_json()['error']

    def test_metadata_returns_what_the_runtime_reports(self, client):
        handler = MagicMock()
        handler.deploy_runtime.return_value = {
            'lithops_version': __version__, 'preinstalls': []
        }
        with patch.object(
            sa_master, 'LocalhostHandler', return_value=handler
        ):
            resp = client.get('/metadata', json={'runtime': 'python3'})
        assert resp.status_code == 200
        assert resp.get_json()['lithops_version'] == __version__
        handler.init.assert_called_once()
        handler.deploy_runtime.assert_called_once_with('python3')

    def test_job_stop_rejects_a_body_that_is_not_a_list(self, client):
        resp = client.post('/job/stop', json={'not': 'a list'})
        assert resp.status_code == 404
        assert 'list' in resp.get_json()['error']

    def test_job_stop_cancels_in_the_background(self, client):
        with patch.object(sa_master, 'Thread') as thread:
            resp = client.post('/job/stop', json=['sess-0-M000'])
        assert resp.status_code == 204
        thread.assert_called_once()
        assert thread.call_args.kwargs['args'] == (['sess-0-M000'],)


class TestWorkerReachability:

    def test_is_worker_free_when_a_process_is_free(self):
        with patch.object(sa_master.requests, 'get') as get:
            get.return_value.json.return_value = {'free': 2, 'busy': 0}
            assert sa_master.is_worker_free('10.0.0.2') is True

    def test_is_worker_free_is_false_when_every_process_is_busy(self):
        with patch.object(sa_master.requests, 'get') as get:
            get.return_value.json.return_value = {'free': 0, 'busy': 2}
            assert sa_master.is_worker_free('10.0.0.2') is False

    def test_is_worker_free_is_false_when_it_cannot_be_reached(self):
        with patch.object(
            sa_master.requests, 'get', side_effect=OSError('down')
        ):
            assert sa_master.is_worker_free('10.0.0.2') is False

    def test_worker_ttd_of_the_master_comes_from_its_own_keeper(self):
        sa_master.budget_keeper.get_time_to_dismantle.return_value = 42
        assert sa_master.get_worker_ttd('10.0.0.1') == '42'

    def test_worker_ttd_of_another_worker_is_asked_over_http(self):
        with patch.object(sa_master.requests, 'get') as get:
            get.return_value.text = '77'
            assert sa_master.get_worker_ttd('10.0.0.2') == '77'
        assert '10.0.0.2' in get.call_args[0][0]

    def test_worker_ttd_is_unknown_when_it_cannot_be_asked(self):
        with patch.object(
            sa_master.requests, 'get', side_effect=OSError('down')
        ):
            assert sa_master.get_worker_ttd('10.0.0.2') == 'Unknown'


class TestWorkerListing:

    def _worker_data(self, **extra):
        data = {
            'name': 'lithops-worker-1',
            'created': '1700000000',
            'instance_type': 'big',
            'worker_processes': '2',
            'runtime': 'python3',
            'exec_mode': StandaloneMode.REUSE.value,
            'status': WorkerStatus.IDLE.value,
            'private_ip': '10.0.0.2',
            'instance_id': 'i-1',
            'ssh_credentials': '{}',
        }
        data.update(extra)
        return data

    def test_worker_list_builds_a_table_with_a_header(self, client):
        sa_master.redis_client.keys.return_value = ['worker:lithops-worker-1']
        sa_master.redis_client.hgetall.return_value = self._worker_data()
        with patch.object(sa_master, 'get_worker_ttd', return_value='30'):
            resp = client.get('/worker/list')
        table = resp.get_json()
        assert table[0][0] == 'Worker Name'
        assert len(table) == 2
        row = table[1]
        assert row[0] == 'lithops-worker-1'
        assert row[2] == 'big'
        assert row[-1] == '30s'

    def test_worker_list_leaves_a_ttd_word_unsuffixed(self, client):
        sa_master.redis_client.keys.return_value = ['worker:lithops-worker-1']
        sa_master.redis_client.hgetall.return_value = self._worker_data()
        with patch.object(sa_master, 'get_worker_ttd', return_value='Disabled'):
            resp = client.get('/worker/list')
        assert resp.get_json()[1][-1] == 'Disabled'

    def test_worker_list_is_just_a_header_with_no_workers(self, client):
        sa_master.redis_client.keys.return_value = []
        resp = client.get('/worker/list')
        assert len(resp.get_json()) == 1

    def test_worker_get_rejects_a_body_that_is_not_a_dict(self, client):
        sa_master.redis_client.keys.return_value = []
        resp = client.get('/worker/get', json=['nope'])
        assert resp.status_code == 404

    def test_worker_get_returns_only_the_free_workers_of_that_shape(
        self, client
    ):
        wanted = self._worker_data(name='wanted')
        other_type = self._worker_data(name='other', instance_type='small')
        other_rt = self._worker_data(name='other-rt', runtime='python:3.12')
        busy = self._worker_data(name='busy', private_ip='10.0.0.9')
        sa_master.redis_client.keys.return_value = ['w1', 'w2', 'w3', 'w4']
        sa_master.redis_client.hgetall.side_effect = [
            wanted, other_type, other_rt, busy
        ]

        def free(private_ip):
            return private_ip != '10.0.0.9'

        with patch.object(sa_master, 'is_worker_free', side_effect=free):
            resp = client.get('/worker/get', json={
                'worker_instance_type': 'big',
                'worker_processes': 2,
                'runtime_name': 'python3',
            })

        free_workers = resp.get_json()
        assert resp.status_code == 200
        assert [w[0] for w in free_workers] == ['wanted']
        # name, ip, instance id, ssh credentials, instance type, runtime
        assert free_workers[0][-1] == 'python3'


class TestWorkerRegistration:

    def test_redis_field_flattens_what_a_hash_cannot_hold(self):
        assert sa_master._redis_field({'a': 1}) == '{"a": 1}'
        assert sa_master._redis_field([1, 2]) == '[1, 2]'
        assert sa_master._redis_field(True) == 'True'
        assert sa_master._redis_field('text') == 'text'
        assert sa_master._redis_field(7) == 7

    def test_save_worker_keeps_the_backend_section_out_of_redis(self):
        worker = _worker_instance()
        sa_master.save_worker(worker, _standalone_config(), 'wq:sess-0-M000')
        mapping = sa_master.redis_client.hset.call_args.kwargs['mapping']
        assert mapping['name'] == worker.name
        assert mapping['status'] == WorkerStatus.STARTING.value
        assert mapping['queue_name'] == 'wq:sess-0-M000'
        assert mapping['worker_processes'] == 2
        assert 'vm' not in mapping
        assert 'do-not-store' not in json.dumps(mapping)

    def test_save_worker_resolves_auto_worker_processes(self):
        worker = _worker_instance(config={'worker_processes': 'AUTO'})
        sa_master.save_worker(worker, _standalone_config(), 'wq')
        mapping = sa_master.redis_client.hset.call_args.kwargs['mapping']
        assert mapping['worker_processes'] == sa_master.CPU_COUNT

    def test_save_worker_tolerates_an_instance_with_no_ip_yet(self):
        worker = _worker_instance(private_ip=None, instance_id=None)
        sa_master.save_worker(worker, _standalone_config(), 'wq')
        mapping = sa_master.redis_client.hset.call_args.kwargs['mapping']
        assert mapping['private_ip'] == ''
        assert mapping['instance_id'] == ''

    def test_worker_vm_data_carries_the_master_and_the_queue(self):
        data = sa_master._worker_vm_data(_worker_instance(), 'wq:sess-0-M000')
        assert data['master_ip'] == '10.0.0.1'
        assert data['work_queue_name'] == 'wq:sess-0-M000'
        assert data['lithops_version'] == __version__
        assert data['name'] == 'lithops-worker-1'

    def test_mark_worker_error_records_the_reason(self):
        sa_master._mark_worker_error('lithops-worker-1', 'boom')
        args, kwargs = sa_master.redis_client.hset.call_args
        assert args[0] == 'worker:lithops-worker-1'
        assert kwargs['mapping'] == {
            'status': WorkerStatus.ERROR.value, 'err': 'boom'
        }

    def test_worker_setup_script_installs_the_host_first(self):
        handler = MagicMock()
        handler.config = _standalone_config()
        with patch.object(
            sa_master, 'get_host_setup_script', return_value='HOST;'
        ), patch.object(
            sa_master, 'get_worker_setup_script', return_value='WORKER;'
        ):
            script = sa_master._worker_setup_script(handler, {'name': 'w'})
        assert script == 'HOST;WORKER;'


class TestWorkerSetup:

    def _handler(self, **cfg):
        handler = MagicMock()
        handler.config = _standalone_config(**cfg)
        return handler

    def test_setup_skips_a_worker_that_is_already_active(self):
        handler = self._handler()
        handler.backend.get_instance.return_value = _worker_instance()
        sa_master.redis_client.hget.return_value = WorkerStatus.ACTIVE.value
        sa_master.setup_worker_create_reuse(handler, {'name': 'w'}, 'wq')
        sa_master.redis_client.hset.assert_not_called()

    def test_setup_installs_and_leaves_the_worker_installing(self):
        handler = self._handler()
        worker = _worker_instance()
        handler.backend.get_instance.return_value = worker
        sa_master.redis_client.hget.return_value = WorkerStatus.STARTING.value

        with patch.object(
            sa_master, '_worker_setup_script', return_value='SCRIPT'
        ):
            sa_master.setup_worker_create_reuse(handler, {'name': 'w'}, 'wq')

        worker.wait_ready.assert_called_once()
        worker.validate_capabilities.assert_called_once()
        ssh = worker.get_ssh_client.return_value
        ssh.upload_local_file.assert_called_once()
        ssh.upload_data_to_file.assert_called_once_with(
            'SCRIPT', '/tmp/install_lithops.sh'
        )
        # The install runs in the background: the worker reports back itself
        assert ssh.run_remote_command.call_args.kwargs['run_async'] is True
        worker.del_ssh_client.assert_called_once()
        statuses = [
            (
                c.kwargs.get('mapping', {}).get('status')
                or (c.args[2] if len(c.args) > 2 else None)
            )
            for c in sa_master.redis_client.hset.call_args_list
        ]
        assert WorkerStatus.INSTALLING.value in statuses

    def test_setup_recreates_a_worker_that_does_not_come_up(self):
        handler = self._handler()
        worker = _worker_instance(config={
            'worker_processes': 2, 'worker_create_retries': 2
        })
        worker.wait_ready.side_effect = [TimeoutError('slow'), None]
        handler.backend.get_instance.return_value = worker
        sa_master.redis_client.hget.return_value = WorkerStatus.STARTING.value

        with patch.object(
            sa_master, '_worker_setup_script', return_value='SCRIPT'
        ):
            sa_master.setup_worker_create_reuse(handler, {'name': 'w'}, 'wq')

        worker.delete.assert_called_once()
        worker.create.assert_called_once()
        assert worker.wait_ready.call_count == 2

    def test_setup_gives_up_when_the_worker_never_comes_up(self):
        handler = self._handler()
        worker = _worker_instance(config={
            'worker_processes': 2, 'worker_create_retries': 1
        })
        worker.wait_ready.side_effect = TimeoutError('slow')
        handler.backend.get_instance.return_value = worker
        sa_master.redis_client.hget.return_value = WorkerStatus.STARTING.value

        with pytest.raises(TimeoutError):
            sa_master.setup_worker_create_reuse(handler, {'name': 'w'}, 'wq')

        errors = [
            c.kwargs['mapping']['err']
            for c in sa_master.redis_client.hset.call_args_list
            if 'mapping' in c.kwargs and 'err' in c.kwargs['mapping']
            and c.kwargs['mapping']['err']
        ]
        assert any('Timeout' in e for e in errors)

    def test_setup_records_why_the_installation_failed(self):
        handler = self._handler()
        worker = _worker_instance()
        worker.get_ssh_client.return_value.upload_local_file.side_effect = (
            OSError('no route')
        )
        handler.backend.get_instance.return_value = worker
        sa_master.redis_client.hget.return_value = WorkerStatus.STARTING.value

        with pytest.raises(OSError):
            sa_master.setup_worker_create_reuse(handler, {'name': 'w'}, 'wq')

        errors = [
            c.kwargs['mapping'].get('err')
            for c in sa_master.redis_client.hset.call_args_list
            if 'mapping' in c.kwargs
        ]
        assert any(e and 'no route' in e for e in errors)

    def test_consume_setup_runs_the_script_on_this_instance(self, tmp_path):
        handler = self._handler(exec_mode=StandaloneMode.CONSUME.value)
        instance = _worker_instance()
        handler.backend.get_instance.return_value = instance
        sa_master.redis_client.hget.return_value = WorkerStatus.STARTING.value
        script_path = str(tmp_path / 'install_lithops.sh')
        real_open = open

        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch.object(
                sa_master, '_worker_setup_script', return_value='SCRIPT'
            ))
            system = enter(
                patch.object(sa_master.os, 'system', return_value=0)
            )
            chmod = enter(patch.object(sa_master.os, 'chmod'))
            remove = enter(patch.object(sa_master.os, 'remove'))
            enter(patch(
                'builtins.open',
                side_effect=lambda *a, **k: real_open(script_path, 'w'),
            ))
            sa_master.setup_worker_consume(handler, {'name': 'w'}, 'wq')

        assert instance.private_ip == '10.0.0.1'
        system.assert_called_once()
        assert system.call_args[0][0].startswith('sudo ')
        chmod.assert_called_once()
        remove.assert_called_once()

    def test_consume_setup_reports_a_failing_script(self, tmp_path):
        handler = self._handler(exec_mode=StandaloneMode.CONSUME.value)
        handler.backend.get_instance.return_value = _worker_instance()
        sa_master.redis_client.hget.return_value = WorkerStatus.STARTING.value
        script_path = str(tmp_path / 'install_lithops.sh')
        real_open = open

        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch.object(
                sa_master, '_worker_setup_script', return_value='SCRIPT'
            ))
            enter(patch.object(sa_master.os, 'system', return_value=256))
            enter(patch.object(sa_master.os, 'chmod'))
            enter(patch.object(sa_master.os, 'remove'))
            enter(patch(
                'builtins.open',
                side_effect=lambda *a, **k: real_open(script_path, 'w'),
            ))
            log = enter(patch.object(sa_master, 'logger'))
            sa_master.setup_worker_consume(handler, {'name': 'w'}, 'wq')

        assert any(
            'wait status' in str(c) for c in log.error.call_args_list
        )


class TestHandleWorkers:

    def test_handle_workers_does_nothing_without_workers(self):
        with patch.object(sa_master, 'StandaloneHandler') as handler:
            sa_master.handle_workers({'config': {}}, [], 'wq')
        handler.assert_not_called()

    def test_handle_workers_sets_each_created_worker_up(self):
        payload = {'config': {'standalone': {}}}
        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch.object(
                sa_master, 'extract_standalone_config',
                return_value=_standalone_config(),
            ))
            enter(patch.object(sa_master, 'StandaloneHandler'))
            setup = enter(
                patch.object(sa_master, 'setup_worker_create_reuse')
            )
            sa_master.handle_workers(
                payload, [{'name': 'a'}, {'name': 'b'}], 'wq'
            )
        assert setup.call_count == 2

    def test_handle_workers_counts_a_failed_worker_as_one_less(self):
        payload = {'config': {'standalone': {}}}
        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch.object(
                sa_master, 'extract_standalone_config',
                return_value=_standalone_config(),
            ))
            enter(patch.object(sa_master, 'StandaloneHandler'))
            enter(patch.object(
                sa_master, 'setup_worker_create_reuse',
                side_effect=[None, OSError('boom')],
            ))
            log = enter(patch.object(sa_master, 'logger'))
            sa_master.handle_workers(
                payload, [{'name': 'a'}, {'name': 'b'}], 'wq'
            )
        assert log.error.called
        assert any('1 of 2' in str(c) for c in log.debug.call_args_list)

    def test_handle_workers_uses_the_master_in_consume_mode(self):
        payload = {'config': {'standalone': {}}}
        cfg = _standalone_config(exec_mode=StandaloneMode.CONSUME.value)
        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch.object(
                sa_master, 'extract_standalone_config', return_value=cfg
            ))
            enter(patch.object(sa_master, 'StandaloneHandler'))
            consume = enter(patch.object(sa_master, 'setup_worker_consume'))
            create = enter(
                patch.object(sa_master, 'setup_worker_create_reuse')
            )
            sa_master.handle_workers(payload, [{'name': 'a'}], 'wq')
        consume.assert_called_once()
        create.assert_not_called()


def _job_payload(**extra):
    payload = {
        'job_key': 'sess-0-M000',
        'executor_id': 'sess-0',
        'job_id': 'M000',
        'host_submit_tstamp': 1700000000.0,
        'func_name': 'add',
        'runtime_name': 'python3',
        'worker_instance_type': 'big',
        'worker_processes': 2,
        'call_ids': ['00000', '00001'],
        'data_byte_ranges': [(0, 9), (10, 19)],
        'worker_instances': [],
        'config': {'standalone': {'exec_mode': StandaloneMode.CREATE.value}},
    }
    payload.update(extra)
    return payload


class TestJobHandling:

    def test_handle_job_registers_it_and_queues_one_task_per_call(self):
        sa_master.handle_job(_job_payload(), 'wq:sess-0-M000')

        mapping = sa_master.redis_client.hset.call_args.kwargs['mapping']
        assert mapping['job_key'] == 'sess-0-M000'
        assert mapping['status'] == JobStatus.SUBMITTED.value
        assert mapping['total_tasks'] == 2
        assert mapping['queue_name'] == 'wq:sess-0-M000'

        pushes = sa_master.redis_client.lpush.call_args_list
        assert len(pushes) == 2
        first = json.loads(pushes[0][0][1])
        second = json.loads(pushes[1][0][1])
        # Each task carries only its own call and its own data range
        assert first['call_ids'] == ['00000']
        assert first['data_byte_ranges'] == [[0, 9]]
        assert second['call_ids'] == ['00001']
        assert second['data_byte_ranges'] == [[10, 19]]

    def test_job_list_builds_a_table_with_the_progress(self, client):
        sa_master.redis_client.keys.return_value = ['job:sess-0-M000']
        sa_master.redis_client.hgetall.return_value = {
            'job_key': 'sess-0-M000',
            'status': JobStatus.RUNNING.value,
            'submitted': '1700000000',
            'func_name': 'add',
            'worker_type': 'big',
            'runtime_name': 'python3',
            'exec_mode': StandaloneMode.CREATE.value,
            'total_tasks': '4',
        }
        sa_master.redis_client.llen.return_value = 3
        table = client.get('/job/list').get_json()
        assert table[0][0] == 'Job ID'
        assert table[1][0] == 'sess-0-M000'
        assert table[1][1] == 'add()'
        assert table[1][3] == 'big'
        assert table[1][5] == '3/4'

    def test_job_list_calls_the_worker_type_vm_in_consume_mode(self, client):
        sa_master.redis_client.keys.return_value = ['job:sess-0-M000']
        sa_master.redis_client.hgetall.return_value = {
            'job_key': 'sess-0-M000',
            'status': JobStatus.RUNNING.value,
            'submitted': '1700000000',
            'func_name': 'add',
            'worker_type': 'ignored',
            'runtime_name': 'python3',
            'exec_mode': StandaloneMode.CONSUME.value,
            'total_tasks': '1',
        }
        sa_master.redis_client.llen.return_value = 0
        assert client.get('/job/list').get_json()[1][3] == 'VM'


class TestJobRun:

    def test_run_rejects_a_body_that_is_not_a_dict(self, client):
        resp = client.post('/job/run', json=['nope'])
        assert resp.status_code == 404

    def test_run_rejects_an_invalid_runtime_name(self, client):
        resp = client.post(
            '/job/run', json=_job_payload(runtime_name='has space')
        )
        assert resp.status_code == 404

    def test_run_accepts_the_job_and_answers_with_an_activation_id(
        self, client
    ):
        with patch.object(sa_master, 'Thread') as thread:
            resp = client.post('/job/run', json=_job_payload())
        assert resp.status_code == 202
        assert len(resp.get_json()['activationId']) == 12
        # One thread queues the job, another sets the workers up
        assert thread.call_count == 2
        sa_master.budget_keeper.add_job.assert_called_once_with('sess-0-M000')

    def _queue_name_for(self, client, payload):
        with patch.object(sa_master, 'Thread') as thread:
            client.post('/job/run', json=payload)
        return thread.call_args_list[0].kwargs['args'][1]

    def test_create_mode_gives_the_job_its_own_queue(self, client):
        payload = _job_payload()
        assert self._queue_name_for(client, payload) == 'wq:sess-0-m000'

    def test_consume_mode_queues_by_runtime(self, client):
        payload = _job_payload(
            runtime_name='lithops/Python:3.12',
            config={'standalone': {
                'exec_mode': StandaloneMode.CONSUME.value
            }},
        )
        assert self._queue_name_for(client, payload) == (
            'wq:localhost:lithops-python:3.12'
        )

    def test_reuse_mode_queues_by_worker_shape(self, client):
        payload = _job_payload(
            config={'standalone': {'exec_mode': StandaloneMode.REUSE.value}}
        )
        assert self._queue_name_for(client, payload) == 'wq:big-2-python3'

    def test_run_takes_the_worker_instances_out_of_the_payload(self, client):
        payload = _job_payload(worker_instances=[{'name': 'w'}])
        with patch.object(sa_master, 'Thread') as thread:
            client.post('/job/run', json=payload)
        # The job payload the workers receive carries no instance list
        queued_payload = thread.call_args_list[0].kwargs['args'][0]
        assert 'worker_instances' not in queued_payload
        assert thread.call_args_list[1].kwargs['args'][1] == [{'name': 'w'}]


class TestCancelJob:

    def test_cancel_requeues_the_tasks_of_other_jobs(self):
        mine = json.dumps({'job_key': 'sess-0-M000'})
        theirs = json.dumps({'job_key': 'sess-0-M001'})
        sa_master.redis_client.hget.return_value = 'wq:sess-0-M000'
        sa_master.redis_client.llen.side_effect = [1, 1, 0]
        sa_master.redis_client.rpop.side_effect = [mine, theirs]
        sa_master.redis_client.keys.return_value = []

        with patch.object(sa_master.Path, 'touch'):
            sa_master.cancel_job_process(['sess-0-M000'])

        pushed = [c[0][1] for c in sa_master.redis_client.lpush.call_args_list]
        assert pushed == [theirs]

    def test_cancel_marks_the_job_canceled_and_leaves_a_done_file(self):
        sa_master.redis_client.hget.side_effect = [
            'wq:sess-0-M000', JobStatus.RUNNING.value
        ]
        sa_master.redis_client.llen.return_value = 0
        sa_master.redis_client.keys.return_value = []

        with patch.object(sa_master.Path, 'touch') as touch:
            sa_master.cancel_job_process(['sess-0-M000'])

        touch.assert_called_once()
        assert sa_master.redis_client.hset.call_args[0][2] == (
            JobStatus.CANCELED.value
        )

    def test_cancel_leaves_an_already_done_job_alone(self):
        sa_master.redis_client.hget.side_effect = [
            'wq:sess-0-M000', JobStatus.DONE.value
        ]
        sa_master.redis_client.llen.return_value = 0
        sa_master.redis_client.keys.return_value = []

        with patch.object(sa_master.Path, 'touch'):
            sa_master.cancel_job_process(['sess-0-M000'])

        sa_master.redis_client.hset.assert_not_called()

    def test_cancel_tells_every_worker_to_stop_the_job(self):
        sa_master.redis_client.hget.return_value = 'wq:sess-0-M000'
        sa_master.redis_client.llen.return_value = 0
        sa_master.redis_client.keys.return_value = ['worker:w1']
        sa_master.redis_client.hgetall.return_value = {
            'private_ip': '10.0.0.2'
        }

        with patch.object(sa_master.Path, 'touch'), \
                patch.object(sa_master.requests, 'post') as post:
            sa_master.cancel_job_process(['sess-0-M000'])

        assert '/stop/sess-0-M000' in post.call_args[0][0]

    def test_cancel_reports_a_worker_that_cannot_be_told(self):
        sa_master.redis_client.hget.return_value = 'wq:sess-0-M000'
        sa_master.redis_client.llen.return_value = 0
        sa_master.redis_client.keys.return_value = ['worker:w1']
        sa_master.redis_client.hgetall.return_value = {
            'private_ip': '10.0.0.2'
        }

        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch.object(sa_master.Path, 'touch'))
            enter(patch.object(
                sa_master.requests, 'post', side_effect=OSError('down')
            ))
            log = enter(patch.object(sa_master, 'logger'))
            sa_master.cancel_job_process(['sess-0-M000'])

        assert log.error.called


class TestJobMonitor:

    def test_monitor_reports_progress_and_marks_a_job_complete(self):
        sa_master.redis_client.keys.return_value = ['job:sess-0-M000']
        sa_master.redis_client.hgetall.return_value = {'total_tasks': '2'}
        # One task done on the first pass, both on the second
        sa_master.redis_client.llen.side_effect = [1, 2]

        rounds = []

        def sleep(_seconds):
            rounds.append(1)
            if len(rounds) > 2:
                raise KeyboardInterrupt

        with patch.object(sa_master.time, 'sleep', side_effect=sleep), \
                patch.object(sa_master.Path, 'touch') as touch, \
                patch.object(sa_master, 'logger') as log:
            with pytest.raises(KeyboardInterrupt):
                sa_master.job_monitor()

        sa_master.budget_keeper.add_job.assert_called_once_with('sess-0-M000')
        touch.assert_called_once()
        messages = [str(c) for c in log.debug.call_args_list]
        assert any('Tasks done: 1/2' in m for m in messages)
        assert any('Completed!' in m for m in messages)

    def test_monitor_stops_looking_at_a_job_that_is_done(self):
        sa_master.redis_client.keys.return_value = ['job:sess-0-M000']
        sa_master.redis_client.hgetall.return_value = {'total_tasks': '1'}
        sa_master.redis_client.llen.side_effect = [1]

        rounds = []

        def sleep(_seconds):
            rounds.append(1)
            if len(rounds) > 3:
                raise KeyboardInterrupt

        with patch.object(sa_master.time, 'sleep', side_effect=sleep), \
                patch.object(sa_master.Path, 'touch'), \
                patch.object(sa_master, 'logger'):
            with pytest.raises(KeyboardInterrupt):
                sa_master.job_monitor()

        # llen is only asked while the job still has tasks pending
        assert sa_master.redis_client.llen.call_count == 1


class TestMasterMain:

    def test_main_wires_the_keeper_the_monitor_and_the_server(self, tmp_path):
        config_file = tmp_path / 'config'
        config_file.write_text(json.dumps(_standalone_config()))
        data_file = tmp_path / 'master.data'
        data_file.write_text(json.dumps({
            'name': 'lithops-master', 'private_ip': '10.1.2.3'
        }))

        keeper = MagicMock()
        server = MagicMock()
        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch.object(
                sa_master, 'SA_CONFIG_FILE', str(config_file)
            ))
            enter(patch.object(
                sa_master, 'SA_MASTER_DATA_FILE', str(data_file)
            ))
            enter(patch.object(sa_master, '_configure_logging'))
            keeper_cls = enter(patch.object(
                sa_master, 'BudgetKeeper', return_value=keeper
            ))
            redis_cls = enter(patch.object(sa_master.redis, 'Redis'))
            thread = enter(patch.object(sa_master, 'Thread'))
            server_cls = enter(patch.object(
                sa_master, 'WSGIServer', return_value=server
            ))
            sa_master.main()

        assert sa_master.master_ip == '10.1.2.3'
        keeper_cls.assert_called_once()
        keeper.start.assert_called_once()
        redis_cls.assert_called_once_with(decode_responses=True)
        # The job monitor runs in the background, the server in the foreground
        assert thread.call_args.kwargs['target'] is sa_master.job_monitor
        assert thread.call_args.kwargs['daemon'] is True
        assert server_cls.call_args[0][0] == (
            '0.0.0.0', sa_master.SA_MASTER_SERVICE_PORT
        )
        server.serve_forever.assert_called_once()
