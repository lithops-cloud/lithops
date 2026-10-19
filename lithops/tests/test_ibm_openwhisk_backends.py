#
# Unit tests for the IBM Cloud Functions, OpenWhisk, Code Engine and Singularity
# backend internals. No cloud account required; the clients are mocked.
#

import threading
import types
from unittest.mock import MagicMock, create_autospec

import pytest

from lithops.serverless.backends.ibm_cf import config as cf_config
from lithops.serverless.backends.ibm_cf import ibm_cf
from lithops.serverless.backends.ibm_cf.ibm_cf import IBMCloudFunctionsBackend
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


def _make_cf_backend():
    backend = IBMCloudFunctionsBackend.__new__(IBMCloudFunctionsBackend)
    backend.name = 'ibm_cf'
    backend.config = {'runtime_timeout': 600, 'token_expiry_time': 'expiry'}
    backend.is_lithops_worker = False
    backend.package = 'lithops_abcd'
    backend.namespace_id = 'ns-id'
    backend.invoke_error = None
    backend.token_manager = MagicMock()
    backend.token_manager.get_token.return_value = ('token', 'expiry')
    backend.cf_client = MagicMock()
    return backend


def _make_ow_backend():
    backend = OpenWhiskBackend.__new__(OpenWhiskBackend)
    backend.name = 'openwhisk'
    backend.namespace = 'guest'
    backend.package = 'lithops_abcde'
    backend.is_lithops_worker = False
    backend.cf_client = MagicMock()
    return backend


# IBM Cloud Functions


def _cf_mutex_is_free():
    if not ibm_cf.cf_mutex.acquire(timeout=1):
        return False
    ibm_cf.cf_mutex.release()
    return True


def test_ibm_cf_redeploy_on_404_does_not_deadlock(monkeypatch, tmp_path):
    monkeypatch.setattr(cf_config, 'FH_ZIP_LOCATION', str(tmp_path / 'lithops_cf.zip'))
    backend = _make_cf_backend()
    backend.cf_client.invoke.side_effect = [404, 'activation-id']
    backend.cf_client.invoke_with_result.return_value = {'preinstalls': []}

    result = _run_in_thread(backend.invoke, 'lithops-cf-runtime', 256, {})

    assert result == {'value': 'activation-id'}
    backend.cf_client.create_action.assert_called_once()
    assert backend.invoke_error is None
    assert _run_in_thread(_cf_mutex_is_free) == {'value': True}


def test_ibm_cf_redeploy_failure_releases_lock(monkeypatch):
    backend = _make_cf_backend()
    backend.cf_client.invoke.return_value = 404
    monkeypatch.setattr(backend, 'deploy_runtime', MagicMock(side_effect=RuntimeError('deploy failed')))

    result = _run_in_thread(backend.invoke, 'lithops-cf-runtime', 256, {})
    assert isinstance(result.get('error'), RuntimeError)

    assert _run_in_thread(_cf_mutex_is_free) == {'value': True}


@pytest.mark.parametrize('make_backend', [_make_cf_backend, _make_ow_backend])
def test_runtime_meta_error_is_raised_as_exception(make_backend):
    backend = make_backend()
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
