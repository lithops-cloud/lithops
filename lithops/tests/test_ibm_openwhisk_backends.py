#
# Unit tests for the OpenWhisk, Code Engine and Singularity backend internals.
# No cloud account required; the clients are mocked.
#

import threading
import types
from unittest.mock import MagicMock, create_autospec

import pytest

from lithops.serverless.backends.openwhisk.openwhisk import OpenWhiskBackend

THREAD_TIMEOUT = 10


def _run_in_thread(target, *args):
    """Runs target in a daemon thread so a deadlock or endless loop fails the test instead of hanging it"""
    result = {}

    def run():
        try:
            result['value'] = target(*args)
        except BaseException as e:
            result['error'] = e

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=THREAD_TIMEOUT)
    assert not thread.is_alive(), f'{target.__name__} did not return within {THREAD_TIMEOUT}s'
    return result


def _make_ow_backend():
    backend = OpenWhiskBackend.__new__(OpenWhiskBackend)
    backend.name = 'openwhisk'
    backend.namespace = 'guest'
    backend.package = 'lithops_abcde'
    backend.user_key = 'abcde'
    backend.is_lithops_worker = False
    backend.ow_config = {'runtime_timeout': 300}
    backend.cf_client = MagicMock()
    return backend


def test_runtime_meta_error_is_raised_as_exception():
    backend = _make_ow_backend()
    backend.cf_client.invoke_with_result.side_effect = ValueError('connection refused')

    with pytest.raises(Exception, match='Unable to extract metadata: connection refused') as excinfo:
        backend._generate_runtime_meta('lithops-runtime', 256)

    assert isinstance(excinfo.value.__cause__, ValueError)


# OpenWhisk


@pytest.mark.parametrize('status, message', [(401, 'api_key'), (404, 'not deployed')])
def test_openwhisk_invoke_error_status_is_not_an_activation_id(status, message):
    backend = _make_ow_backend()
    backend.cf_client.invoke.return_value = status

    with pytest.raises(Exception, match=message):
        backend.invoke('lithops-ow-runtime', 256, {})


def test_openwhisk_invoke_returns_activation_id():
    backend = _make_ow_backend()
    backend.cf_client.invoke.return_value = 'activation-id'

    assert backend.invoke('lithops-ow-runtime', 256, {}) == 'activation-id'


def test_openwhisk_invoke_throttled_returns_none():
    backend = _make_ow_backend()
    backend.cf_client.invoke.return_value = None

    assert backend.invoke('lithops-ow-runtime', 256, {}) is None


@pytest.mark.parametrize('image, memory', [
    ('docker.io/lithopscloud/openwhisk-python-v312:latest', 256),
    ('localhost:5000/ns/img:1.2', 512),
    ('user/name', 128),
])
def test_openwhisk_action_name_round_trip(image, memory):
    backend = _make_ow_backend()
    name = backend._format_function_name(image, memory, '3.8.1.dev0')
    assert backend._unformat_function_name(name) == ('3.8.1.dev0', image, memory)


def test_openwhisk_list_runtimes_skips_foreign_actions():
    backend = _make_ow_backend()
    good = backend._format_function_name('docker.io/ns/rt:1', 256, '3.8.0')
    backend.cf_client.list_packages.return_value = [{'name': backend.package}, {'name': 'other'}]
    backend.cf_client.list_actions.return_value = [{'name': good}, {'name': 'hello'}]

    assert backend.list_runtimes() == [('docker.io/ns/rt:1', 256, '3.8.0', good)]


def test_openwhisk_clean_deletes_each_action_once():
    backend = _make_ow_backend()
    backend.cf_client.list_packages.return_value = [{'name': backend.package}]
    backend.cf_client.list_actions.return_value = [{'name': 'a'}, {'name': 'b'}]

    backend.clean()

    assert backend.cf_client.delete_action.call_count == 2
    backend.cf_client.delete_package.assert_called_once_with(backend.package)


def test_openwhisk_build_runtime_uses_the_host_architecture(monkeypatch):
    from lithops.serverless.backends.openwhisk import openwhisk
    backend = _make_ow_backend()
    backend.ow_config = {}
    commands = []
    monkeypatch.setattr(openwhisk.utils, 'get_docker_path', lambda: 'docker')
    monkeypatch.setattr(openwhisk.utils, 'is_podman', lambda path: False)
    monkeypatch.setattr(openwhisk.utils, 'run_command', commands.append)
    backend.build_runtime('user/rt:1', None, ['--platform', 'linux/amd64'])
    assert commands[0] == 'docker build -t user/rt:1 . --platform linux/amd64'
    assert '--platform=linux/amd64' not in commands[0]


def test_openwhisk_runtime_meta_waits_once():
    backend = _make_ow_backend()
    backend.cf_client.invoke_with_result.return_value = {'preinstalls': ['requests']}

    assert backend._generate_runtime_meta('ns/rt:1', 256) == {'preinstalls': ['requests']}

    _, kwargs = backend.cf_client.invoke_with_result.call_args
    assert kwargs['timeout'] == 480
    assert backend.cf_client.invoke_with_result.call_count == 1


# Code Engine


@pytest.fixture
def ce():
    pytest.importorskip('ibm_code_engine_sdk')
    from ibm_cloud_sdk_core import ApiException
    from ibm_code_engine_sdk.code_engine_v2 import CodeEngineV2
    from lithops.serverless.backends.code_engine import code_engine

    backend = code_engine.CodeEngineBackend.__new__(code_engine.CodeEngineBackend)
    backend.name = 'code_engine'
    backend.config = {'runtime_timeout': 600, 'runtime_cpu': 0.125}
    backend.project_id = 'project-id'
    backend.project_name = 'lithops-test'
    backend.user_key = 'abcd'
    backend.jobs = []
    backend.ce_client = create_autospec(CodeEngineV2, instance=True)
    return types.SimpleNamespace(backend=backend, module=code_engine, ApiException=ApiException)


def test_code_engine_lists_jobs_past_the_first_page(ce):
    ce.backend.ce_client.list_jobs.side_effect = [
        MagicMock(**{'get_result.return_value': {'jobs': [{'name': 'a'}], 'next': {'start': 's'}}}),
        MagicMock(**{'get_result.return_value': {'jobs': [{'name': 'b'}]}}),
    ]
    assert [job['name'] for job in ce.backend._list_jobs()] == ['a', 'b']
    assert ce.backend.ce_client.list_jobs.call_args_list[1].kwargs['start'] == 's'


def test_code_engine_clear_removes_all_jobs(ce, monkeypatch):
    monkeypatch.setattr(ce.backend, '_get_or_create_namespace', MagicMock(return_value='ns'))
    ce.backend.jobs = ['A1-00', 'A1-01', 'A1-02', 'A1-03']

    ce.backend.clear()

    assert ce.backend.jobs == []
    assert ce.backend.ce_client.delete_job_run.call_count == 4
    assert ce.backend.ce_client.delete_config_map.call_count == 4


def test_code_engine_replace_existing_config_map(ce):
    ce.backend.ce_client.create_config_map.side_effect = ce.ApiException(409, message='already exists')

    assert ce.backend._create_config_map('lithops-a1-00', {'key': 'value'}) == 'lithops-a1-00'

    ce.backend.ce_client.replace_config_map.assert_called_once()
    _, kwargs = ce.backend.ce_client.replace_config_map.call_args
    assert kwargs['if_match'] == '*'
    assert 'lithops.payload' in kwargs['data']


@pytest.mark.parametrize('stuck', ['api_error', 'pending'])
def test_code_engine_wait_for_job_run_times_out(ce, monkeypatch, stuck):
    monkeypatch.setattr(ce.module.config, 'JOB_RUN_TIMEOUT', 0.2)
    monkeypatch.setattr(ce.module.config, 'JOB_RUN_POLL_INTERVAL', 0.01)
    if stuck == 'api_error':
        ce.backend.ce_client.get_job_run.side_effect = ce.ApiException(500, message='internal error')
    else:
        ce.backend.ce_client.get_job_run.return_value.get_result.return_value = {'status': 'pending'}

    result = _run_in_thread(ce.backend._wait_for_job_run, 'lithops-runtime-metadata')

    assert 'Timed out' in str(result.get('error'))


def test_code_engine_job_definition_delete_times_out(ce, monkeypatch):
    monkeypatch.setattr(ce.module.config, 'JOB_DEF_DELETE_TIMEOUT', 0.2)

    result = _run_in_thread(ce.backend._create_job_definition, 'docker.io/user/runtime:1', 256)

    assert 'Timed out' in str(result.get('error'))
    ce.backend.ce_client.create_job.assert_not_called()


# Singularity


def test_singularity_runtime_meta_timeout_message(monkeypatch):
    pytest.importorskip('pika')
    from lithops.serverless.backends.singularity import singularity

    monkeypatch.setattr(singularity, 'time', types.SimpleNamespace(sleep=lambda seconds: None))
    backend = singularity.SingularityBackend.__new__(singularity.SingularityBackend)
    backend.channel = MagicMock()
    backend.internal_storage = MagicMock()
    backend.internal_storage.storage.config = {}
    backend.internal_storage.get_data.side_effect = Exception('NoSuchKey')

    with pytest.raises(Exception, match='Failed getting runtime metadata'):
        backend._generate_runtime_meta('singularity-runtime')


@pytest.mark.parametrize('already_deleted', [False, True])
def test_code_engine_project_is_permanently_reclaimed(ce, monkeypatch, already_deleted):
    if already_deleted:
        ce.backend.ce_client.delete_project.side_effect = ce.ApiException(404, message='gone')
    controller = MagicMock()
    monkeypatch.setattr(ce.module, 'BaseService', MagicMock(return_value=controller))
    monkeypatch.setattr(ce.module.time, 'sleep', lambda seconds: None)
    controller.prepare_request.side_effect = lambda method, url, **kwargs: {'method': method, 'url': url, **kwargs}
    controller.send.side_effect = [
        MagicMock(**{'get_result.return_value': {'state': 'pending_reclamation'}}),
        MagicMock(**{'get_result.return_value': {'resources': []}}),
        MagicMock(**{'get_result.return_value': {'state': 'pending_reclamation'}}),
        MagicMock(**{'get_result.return_value': {'resources': [
            {'id': 'unrelated', 'resource_instance_id': 'other-project'},
            {'id': 'reclamation-id', 'resource_instance_id': 'project-id'},
        ]}}),
        MagicMock(),
        MagicMock(**{'get_result.return_value': {'state': 'removed'}}),
    ]
    ce.backend._hard_delete_project('project-id')
    ce.backend.ce_client.delete_project.assert_called_once_with(id='project-id')
    requests = [call.args[0] for call in controller.send.call_args_list]
    posts = [request for request in requests if request['method'] == 'POST']
    assert posts == [{
        'method': 'POST', 'url': '/v1/reclamations/reclamation-id/actions/reclaim',
        'headers': {'Content-Type': 'application/json'}, 'data': {},
    }]
    assert requests[1]['params'] == {'resource_instance_id': 'project-id'}


@pytest.mark.parametrize('all_clean', [False, True])
@pytest.mark.parametrize('active', [False, True])
def test_code_engine_clean_hard_deletes_only_with_all(ce, monkeypatch, tmp_path, all_clean, active):
    backend = ce.backend
    backend.cache_file = str(tmp_path / 'cache')
    ce.module.dump_yaml_config(backend.cache_file, {'project_id': 'project-id'})

    def namespace(**kwargs):
        if not active:
            backend.project_id = None
        return 'namespace' if active else None

    monkeypatch.setattr(backend, '_get_or_create_namespace', namespace)
    monkeypatch.setattr(backend, 'clear', MagicMock())
    monkeypatch.setattr(backend, 'list_runtimes', lambda: [])
    monkeypatch.setattr(backend, '_delete_lithops_config_maps', MagicMock())
    hard_delete = MagicMock()
    monkeypatch.setattr(backend, '_hard_delete_project', hard_delete)
    backend.clean(all=all_clean)
    if all_clean:
        hard_delete.assert_called_once_with('project-id')
    else:
        hard_delete.assert_not_called()


@pytest.mark.parametrize('failure', ['permission', 'timeout'])
def test_code_engine_failed_hard_delete_keeps_cache(ce, monkeypatch, tmp_path, failure):
    backend = ce.backend
    backend.cache_file = str(tmp_path / 'cache')
    ce.module.dump_yaml_config(backend.cache_file, {'project_id': 'project-id'})
    monkeypatch.setattr(backend, '_get_or_create_namespace', lambda **kwargs: 'namespace')
    monkeypatch.setattr(backend, 'clear', MagicMock())
    monkeypatch.setattr(backend, 'list_runtimes', lambda: [])
    monkeypatch.setattr(backend, '_delete_lithops_config_maps', MagicMock())
    controller = MagicMock()
    monkeypatch.setattr(ce.module, 'BaseService', MagicMock(return_value=controller))
    if failure == 'permission':
        controller.send.side_effect = ce.ApiException(403, message='forbidden')
        expected = ce.ApiException
    else:
        monkeypatch.setattr(ce.module.config, 'PROJECT_READY_TIMEOUT', 0)
        expected = TimeoutError
    with pytest.raises(expected):
        backend.clean(all=True)
    assert (tmp_path / 'cache').exists()
