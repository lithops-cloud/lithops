#
# Unit tests for the serverless compute frontend (not cloud backends).
#

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lithops.serverless import ServerlessHandler
from lithops.serverless import __all__ as serverless_all
from lithops.utils import BackendType


def _config(**extra):
    cfg = {
        'backend': 'aws_lambda',
        'aws_lambda': {'region': 'us-east-1'},
    }
    cfg.update(extra)
    return cfg


def _make_handler(backend=None):
    fake_backend = backend or MagicMock()
    fake_backend.type = BackendType.FAAS.value
    fake_module = MagicMock()
    fake_module.ServerlessBackend.return_value = fake_backend
    storage = MagicMock()
    with patch(
        'lithops.serverless.serverless.importlib.import_module',
        return_value=fake_module,
    ) as importer:
        handler = ServerlessHandler(_config(), storage)
    fake_module.ServerlessBackend.assert_called_once_with(
        {'region': 'us-east-1'}, storage
    )
    importer.assert_called_once_with('lithops.serverless.backends.aws_lambda')
    handler.backend = fake_backend
    return handler, fake_backend


class TestServerlessExports:

    def test_all_exports_handler(self):
        assert serverless_all == ['ServerlessHandler']


class TestServerlessHandler:

    def test_loads_named_backend_and_reports_type(self):
        handler, backend = _make_handler()
        assert handler.backend_name == 'aws_lambda'
        assert handler.get_backend_type() == BackendType.FAAS.value
        handler.init()
        backend.init.assert_not_called()

    def test_backend_import_failure_is_logged_and_reraised(self):
        with patch(
            'lithops.serverless.serverless.importlib.import_module',
            side_effect=ImportError('missing extra'),
        ):
            with pytest.raises(ImportError, match='missing extra'):
                ServerlessHandler(_config(), MagicMock())

    def test_invoke_passes_runtime_fields(self):
        handler, backend = _make_handler()
        payload = {
            'runtime_name': 'lithops/python:3.12',
            'runtime_memory': 256,
            'call_ids': ['00000'],
        }
        backend.invoke.return_value = {'ok': True}
        assert handler.invoke(payload) == {'ok': True}
        backend.invoke.assert_called_once_with(
            'lithops/python:3.12', 256, payload
        )

    def test_pre_invoke_and_clear_are_optional(self):
        class MinimalBackend:
            type = BackendType.BATCH.value

        handler, _ = _make_handler(MinimalBackend())
        handler.pre_invoke(
            SimpleNamespace(runtime_name='rt', runtime_memory=128)
        )
        handler.clear(['job-1'])

    def test_pre_invoke_and_clear_delegate_when_present(self):
        handler, backend = _make_handler()
        job = SimpleNamespace(runtime_name='rt', runtime_memory=128)
        handler.pre_invoke(job)
        backend.pre_invoke.assert_called_once_with('rt', 128)
        handler.clear(['job-1'], exception=RuntimeError('x'))
        backend.clear.assert_called_once_with(['job-1'])

    def test_build_runtime_defaults_extra_args_to_empty_list(self):
        handler, backend = _make_handler()
        handler.build_runtime('rt', None)
        backend.build_runtime.assert_called_once_with('rt', None, [])

    def test_runtime_lifecycle_delegates(self):
        handler, backend = _make_handler()
        backend.deploy_runtime.return_value = {'preinstalls': []}
        backend.list_runtimes.return_value = ['rt']
        backend.get_runtime_key.return_value = 'key'
        backend.get_runtime_info.return_value = {'runtime_name': 'rt'}

        assert handler.deploy_runtime('rt', 256, 60) == {'preinstalls': []}
        backend.deploy_runtime.assert_called_once_with('rt', 256, timeout=60)

        handler.delete_runtime('rt', 256, '3.0.0')
        backend.delete_runtime.assert_called_once_with('rt', 256, '3.0.0')

        handler.clean(all=True)
        backend.clean.assert_called_once_with(all=True)

        assert handler.list_runtimes() == ['rt']
        backend.list_runtimes.assert_called_once_with('all')

        assert handler.get_runtime_key('rt', 256, '3.0.0') == 'key'
        assert handler.get_runtime_info() == {'runtime_name': 'rt'}
