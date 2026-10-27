#
# Unit tests for the serverless compute frontend and, with fakes, the serverless backends.
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


class TestCodeEngineEntryPoint:

    def _load_entry_point(self):
        pytest.importorskip('ibm_code_engine_sdk')
        import importlib
        import sys
        # Code Engine runs every call as a job run: the entry point needs no web server
        with patch.dict(sys.modules, {'flask': None}):
            sys.modules.pop('lithops.serverless.backends.code_engine.entry_point', None)
            return importlib.import_module('lithops.serverless.backends.code_engine.entry_point')

    def test_run_ce_job_runs_the_calls_of_its_job_index(self, monkeypatch):
        from lithops.utils import dict_to_b64str
        entry_point = self._load_entry_point()
        payload = {
            'log_level': 'INFO',
            'chunksize': 2,
            'call_ids': ['00000', '00001', '00002', '00003', '00004'],
            'data_byte_ranges': [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]],
        }
        monkeypatch.setenv('JOB_INDEX', '1')
        # run_ce_job sets them; registering them restores the environment afterwards
        monkeypatch.setenv('__LITHOPS_ACTIVATION_ID', '')
        monkeypatch.setenv('__LITHOPS_BACKEND', '')
        with patch.object(entry_point, 'setup_lithops_logger'), \
                patch.object(entry_point, 'function_handler') as handler:
            entry_point.run_ce_job('run', dict_to_b64str(payload))

        sent = handler.call_args[0][0]
        assert sent['call_ids'] == ['00002', '00003']
        assert sent['data_byte_ranges'] == [[2, 3], [3, 4]]
        assert 'JOB_INDEX' not in sent

    def test_default_dockerfile_runs_the_job_entry_point(self):
        # The package imports the backend, and with it the Code Engine SDK
        pytest.importorskip('ibm_code_engine_sdk')
        from lithops.serverless.backends.code_engine import config
        assert 'CMD ["python", "lithopsentry.py"]' in config.DOCKERFILE_DEFAULT
        for unused in ('gunicorn', 'flask', 'gevent', 'PORT'):
            assert unused not in config.DOCKERFILE_DEFAULT
        assert config.ENTRYPOINT_SCRIPT == '/lithops/lithopsentry.py'


class TestOracleFunctionsConfig:

    def test_missing_oracle_f_section_is_reported(self):
        pytest.importorskip('oci')
        from lithops.serverless.backends.oracle_f.config import load_config
        config_data = {'oracle': {
            'compartment_id': 'c', 'user': 'u', 'key_file': '/tmp/key.pem',
            'region': 'eu-madrid-1', 'tenancy': 't', 'fingerprint': 'f',
        }}
        with pytest.raises(Exception, match="'oracle_f' section is mandatory"):
            load_config(config_data)

    def test_missing_oracle_section_is_reported(self):
        pytest.importorskip('oci')
        from lithops.serverless.backends.oracle_f.config import load_config
        with pytest.raises(Exception, match="'oracle' section is mandatory"):
            load_config({'oracle_f': {'subnet_id': 's'}})


class TestAliyunZipRuntimeBuild:

    def test_falls_back_to_local_pip_when_docker_is_missing(self, tmp_path):
        pytest.importorskip('alibabacloud_fc20230330')
        from lithops.serverless.backends.aliyun_fc import aliyun_fc, config

        backend = aliyun_fc.AliyunFunctionComputeBackend.__new__(aliyun_fc.AliyunFunctionComputeBackend)
        backend.deploy_mode = 'zip'
        requirements = tmp_path / 'requirements.txt'
        requirements.write_text('numpy\n')

        with patch.object(config, 'BUILD_DIR', str(tmp_path / 'build')), \
                patch.object(aliyun_fc.utils, 'get_docker_path', side_effect=Exception('docker not found')), \
                patch.object(aliyun_fc.utils, 'is_linux_system', return_value=True), \
                patch.object(aliyun_fc.utils, 'run_command') as run_command, \
                patch.object(aliyun_fc.shutil, 'copytree'), \
                patch.object(aliyun_fc.os, 'chdir'):
            backend.build_runtime('myruntime', str(requirements))

        commands = [c[0][0] for c in run_command.call_args_list]
        assert any('-m pip install -t' in cmd for cmd in commands)
        assert not any(' run --platform' in cmd for cmd in commands)


class TestAzureContainerAppDeploy:

    @pytest.fixture
    def backend(self, tmp_path):
        pytest.importorskip('azure.storage.queue')
        from lithops.serverless.backends.azure_containers import azure_containers, config

        backend = azure_containers.AzureContainerAppBackend.__new__(azure_containers.AzureContainerAppBackend)
        backend.name = 'azure_containers'
        backend.trigger = 'pub/sub'
        backend.resource_group = 'LithopsResourceGroup'
        backend.storage_account_name = 'lithopssa'
        backend.location = 'westeurope'
        backend.environment = 'lithops'
        backend.ac_config = {'max_workers': 10}
        backend.queue_service = MagicMock()
        backend._wait_until_containerapp_idle = MagicMock(return_value=None)

        with patch.object(config, 'CA_JSON_LOCATION', str(tmp_path / 'containerapp.yaml')), \
                patch.object(azure_containers.time, 'sleep') as sleep:
            backend.sleep = sleep
            yield backend

    @staticmethod
    def _az(create_errors):
        """Fakes _run_az_command: `az containerapp create` raises the given errors in order"""
        create_errors = list(create_errors)
        calls = []

        def run(cmd, return_json=False, return_result=False):
            calls.append(cmd)
            if cmd.startswith('az containerapp env show'):
                return '/subscriptions/s/resourceGroups/LithopsResourceGroup/managedEnvironments/lithops'
            if cmd.startswith('az storage account show-connection-string'):
                return 'connection-string'
            if cmd.startswith('az containerapp create') and create_errors:
                raise Exception(create_errors.pop(0))
            return None

        return run, calls

    def test_missing_environment_fails_at_once(self, backend):
        error = ('Azure CLI command failed: az containerapp create\n'
                 "ERROR: (ManagedEnvironmentNotFound) The environment 'lithops' does not exist")
        backend._run_az_command, calls = self._az([error] * 10)

        with pytest.raises(Exception) as excinfo:
            backend._create_app('docker.io/user/runtime:01', 2048, 600)

        assert len([c for c in calls if c.startswith('az containerapp create')]) == 1
        backend.sleep.assert_not_called()
        msg = str(excinfo.value)
        assert "'lithops'" in msg
        assert "'LithopsResourceGroup'" in msg
        assert "'westeurope'" in msg
        assert 'compute_config/azure_containers.html' in msg
        assert 'environment_id' in msg

    def test_environment_lookup_not_found_is_reported(self, backend):
        def run(cmd, return_json=False, return_result=False):
            raise Exception("Azure CLI command failed: az containerapp env show\n"
                            "ERROR: (ResourceNotFound) The Resource 'Microsoft.App/managedEnvironments/lithops' "
                            "under resource group 'LithopsResourceGroup' was not found.")
        backend._run_az_command = run

        with pytest.raises(Exception, match="environment 'lithops' was not found in resource group"):
            backend._get_managed_environment_id()

    def test_other_non_retryable_errors_fail_at_once(self, backend):
        backend._run_az_command, calls = self._az(['ERROR: (AuthorizationFailed) no permission'] * 10)

        with pytest.raises(Exception, match='AuthorizationFailed'):
            backend._create_app('docker.io/user/runtime:01', 2048, 600)

        assert len([c for c in calls if c.startswith('az containerapp create')]) == 1

    def test_transient_errors_are_retried(self, backend):
        backend._run_az_command, calls = self._az([
            'ERROR: (ContainerAppOperationInProgress) another operation is in progress',
            'ERROR: something transient',
        ])

        backend._create_app('docker.io/user/runtime:01', 2048, 600)

        assert len([c for c in calls if c.startswith('az containerapp create')]) == 3
        backend.sleep.assert_called_once_with(15)

    def test_az_error_code_is_captured_at_debug_level(self, backend):
        import logging
        import subprocess as sp
        from lithops.serverless.backends.azure_containers import azure_containers

        def fake_run(cmd, **kwargs):
            stderr = "ERROR: (ManagedEnvironmentNotFound) no environment" if kwargs.get('stderr') is sp.PIPE else None
            raise sp.CalledProcessError(1, cmd, stderr=stderr)

        backend._check_az_cli = MagicMock()
        with patch.object(azure_containers.logger, 'getEffectiveLevel', return_value=logging.DEBUG), \
                patch.object(azure_containers.sp, 'run', side_effect=fake_run):
            with pytest.raises(Exception, match='ManagedEnvironmentNotFound'):
                backend._run_az_command('az containerapp create --name app')


class TestCloudRunArtifactRegistryPermission:

    IMAGE = 'us-east1-docker.pkg.dev/my-project/lithops/runtime:01'
    PERMISSION = 'artifactregistry.repositories.uploadArtifacts'

    @pytest.fixture
    def backend(self):
        pytest.importorskip('googleapiclient')
        from lithops.serverless.backends.gcp_cloudrun import cloudrun

        backend = cloudrun.GCPCloudRunBackend.__new__(cloudrun.GCPCloudRunBackend)
        backend.credentials_path = None
        backend.service_account = 'lithops@my-project.iam.gserviceaccount.com'
        backend._ar_resource = MagicMock()
        return backend

    def _granted(self, backend, permissions):
        repositories = backend._ar_resource.projects.return_value.locations.return_value.repositories.return_value
        repositories.testIamPermissions.return_value.execute.return_value = {'permissions': permissions}
        return repositories.testIamPermissions

    def test_missing_permission_names_the_service_account_and_repository(self, backend):
        test_permissions = self._granted(backend, [])

        with pytest.raises(Exception) as excinfo:
            backend._ensure_artifact_registry_upload_permission(self.IMAGE)

        resource = 'projects/my-project/locations/us-east1/repositories/lithops'
        test_permissions.assert_called_once_with(resource=resource, body={'permissions': [self.PERMISSION]})
        msg = str(excinfo.value)
        assert '"lithops@my-project.iam.gserviceaccount.com"' in msg
        assert f'"{resource}"' in msg
        assert 'roles/artifactregistry.writer' in msg

    def test_unknown_principal_is_reported_generically(self, backend):
        self._granted(backend, [])
        backend.service_account = None

        with pytest.raises(Exception, match='"current credentials principal"'):
            backend._ensure_artifact_registry_upload_permission(self.IMAGE)

    def test_granted_permission_passes(self, backend):
        self._granted(backend, [self.PERMISSION])
        backend._ensure_artifact_registry_upload_permission(self.IMAGE)

    def test_other_registries_are_not_checked(self, backend):
        test_permissions = self._granted(backend, [])
        backend._ensure_artifact_registry_upload_permission('docker.io/me/runtime:01')
        test_permissions.assert_not_called()


class TestGcpFunctionDeletion:

    def test_only_a_missing_function_ends_the_wait(self):
        pytest.importorskip('googleapiclient')
        from googleapiclient.errors import HttpError
        from lithops.serverless.backends.gcp_functions.gcp_functions import GCPFunctionsBackend
        backend = GCPFunctionsBackend.__new__(GCPFunctionsBackend)
        backend.num_retries = 0
        backend.retry_sleep = 0
        backend._api_resource = MagicMock()
        get = (
            backend._api_resource.projects.return_value
            .locations.return_value.functions.return_value.get
        )

        def http_error(status):
            return HttpError(MagicMock(status=status, reason='no'), b'no')

        get.return_value.execute.side_effect = http_error(503)
        with pytest.raises(HttpError):
            backend._wait_function_deleted('projects/p/locations/l/functions/f')
        get.return_value.execute.side_effect = http_error(404)
        backend._wait_function_deleted('projects/p/locations/l/functions/f')


class TestGcpFunctionsDeploy:

    @pytest.fixture(autouse=True)
    def _need_gcp(self):
        pytest.importorskip('googleapiclient')
        pytest.importorskip('google_auth_httplib2')
        pytest.importorskip('google.cloud.pubsub_v1')

    def _backend(self):
        from lithops.serverless.backends.gcp_functions.gcp_functions import GCPFunctionsBackend
        backend = GCPFunctionsBackend.__new__(GCPFunctionsBackend)
        backend.trigger = 'https'
        backend.internal_storage = MagicMock()
        backend.internal_storage.storage.config = {}
        return backend

    def test_runtime_metadata_is_read_once(self):
        backend = self._backend()
        backend.invoke = MagicMock(return_value={'preinstalls': ['x']})
        assert backend._generate_runtime_meta('rt', 256) == {'preinstalls': ['x']}
        backend.invoke.assert_called_once()

    def test_metadata_without_preinstalls_is_not_read_again(self):
        backend = self._backend()
        backend.invoke = MagicMock(return_value={})
        with pytest.raises(Exception, match='Failed getting runtime metadata'):
            backend._generate_runtime_meta('rt', 256)
        backend.invoke.assert_called_once()

    def test_a_metadata_failure_deletes_the_function(self, tmp_path, monkeypatch):
        from lithops.serverless.backends.gcp_functions import config as gcf_config
        zip_path = tmp_path / 'rt.zip'
        zip_path.write_bytes(b'zip')
        monkeypatch.setattr(gcf_config, 'FH_ZIP_LOCATION', str(tmp_path / '{}.zip'))
        backend = self._backend()
        backend._get_default_runtime_name = MagicMock(return_value='other')
        backend._get_runtime_bin_location = MagicMock(return_value='bin')
        backend._create_function = MagicMock()
        backend._generate_runtime_meta = MagicMock(side_effect=Exception('metadata down'))
        backend.delete_runtime = MagicMock()
        with pytest.raises(Exception, match='metadata down'):
            backend.deploy_runtime('rt', 256, 60)
        backend.delete_runtime.assert_called_once_with('rt', 256)
        assert not zip_path.exists()

    def test_the_metadata_error_survives_a_failed_cleanup(self, tmp_path, monkeypatch):
        from lithops.serverless.backends.gcp_functions import config as gcf_config
        (tmp_path / 'rt.zip').write_bytes(b'zip')
        monkeypatch.setattr(gcf_config, 'FH_ZIP_LOCATION', str(tmp_path / '{}.zip'))
        backend = self._backend()
        backend._get_default_runtime_name = MagicMock(return_value='other')
        backend._get_runtime_bin_location = MagicMock(return_value='bin')
        backend._create_function = MagicMock()
        backend._generate_runtime_meta = MagicMock(side_effect=Exception('metadata down'))
        backend.delete_runtime = MagicMock(side_effect=Exception('cleanup'))
        with pytest.raises(Exception, match='metadata down'):
            backend.deploy_runtime('rt', 256, 60)

    def test_https_invoke_waits_as_long_as_the_runtime(self, monkeypatch):
        backend = self._backend()
        backend.gcf_config = {'runtime_timeout': 300}
        backend._format_function_name = lambda runtime_name, memory: 'fn'
        backend._get_token = lambda function_name: ('https://fn', 'tok')
        seen = {}

        def post(url, data, headers, timeout):
            seen['timeout'] = timeout
            return SimpleNamespace(status_code=202, json=lambda: {'activationId': 'act'})

        monkeypatch.setattr(
            'lithops.serverless.backends.gcp_functions.gcp_functions.requests.post', post
        )
        assert backend.invoke('rt', 256, {}) == 'act'
        assert seen['timeout'] == 330

    def test_functions_past_the_first_page_are_listed(self):
        pytest.importorskip('googleapiclient')
        from lithops.serverless.backends.gcp_functions.gcp_functions import GCPFunctionsBackend
        backend = GCPFunctionsBackend.__new__(GCPFunctionsBackend)
        backend.num_retries = 0
        backend.project_name = 'p'
        backend.region = 'l'
        backend._api_resource = MagicMock()
        list_call = (
            backend._api_resource.projects.return_value.locations.return_value
            .functions.return_value.list
        )

        def fn(name):
            return {
                'name': f'projects/p/locations/l/functions/{name}',
                'labels': {
                    'type': 'lithops-runtime',
                    'lithops_version': '3-8-1-dev0',
                    'runtime_name': 'rt',
                },
                'serviceConfig': {'availableMemory': '256M'},
            }

        list_call.return_value.execute.side_effect = [
            {'functions': [fn('a')], 'nextPageToken': 'tok'},
            {'functions': [fn('b')]},
        ]
        assert [row[3] for row in backend.list_runtimes()] == ['a', 'b']
        assert list_call.call_args_list[1].kwargs['pageToken'] == 'tok'

    @pytest.mark.parametrize('service_config', [None, {}, {'availableMemory': '512Mi'}])
    def test_clean_deletes_incomplete_functions(self, service_config):
        backend = self._backend()
        function = {
            'name': 'projects/p/locations/l/functions/failed-runtime',
            'state': 'UNKNOWN',
            'labels': {
                'type': 'lithops-runtime',
                'lithops_version': '3-8-1-dev0',
                'runtime_name': 'rt',
            },
        }
        if service_config is not None:
            function['serviceConfig'] = service_config
        backend._list_functions = MagicMock(return_value=[
            {'name': 'unrelated-function'}, {'labels': None}, function,
        ])
        memory = 512 if service_config else None
        assert backend.list_runtimes() == [('rt', memory, '3.8.1.dev0', 'failed-runtime')]
        assert backend.list_runtimes('other') == []
        backend.delete_runtime = MagicMock()
        backend.clean()
        backend.delete_runtime.assert_called_once_with(
            'rt', memory, '3.8.1.dev0', function_name='failed-runtime'
        )


class TestCloudRunDeployAndDelete:

    def _backend(self):
        pytest.importorskip('googleapiclient')
        from lithops.serverless.backends.gcp_cloudrun.cloudrun import GCPCloudRunBackend
        backend = GCPCloudRunBackend.__new__(GCPCloudRunBackend)
        backend.project_name = 'proj'
        backend._api_resource = MagicMock()
        return backend

    @staticmethod
    def _http_error(status):
        from googleapiclient.errors import HttpError
        return HttpError(MagicMock(status=status, reason='no'), b'no')

    def test_a_metadata_failure_deletes_the_service(self):
        backend = self._backend()
        backend._get_default_runtime_image_name = MagicMock(return_value='other')
        backend._create_service = MagicMock()
        backend._generate_runtime_meta = MagicMock(side_effect=Exception('metadata down'))
        backend.delete_runtime = MagicMock()
        with pytest.raises(Exception, match='metadata down'):
            backend.deploy_runtime('docker.io/me/runtime:1', 256, 60)
        backend.delete_runtime.assert_called_once_with('docker.io/me/runtime:1', 256)

    def test_the_metadata_error_survives_a_failed_cleanup(self):
        backend = self._backend()
        backend._get_default_runtime_image_name = MagicMock(return_value='other')
        backend._create_service = MagicMock()
        backend._generate_runtime_meta = MagicMock(side_effect=Exception('metadata down'))
        backend.delete_runtime = MagicMock(side_effect=Exception('cleanup'))
        with pytest.raises(Exception, match='metadata down'):
            backend.deploy_runtime('docker.io/me/runtime:1', 256, 60)

    def test_only_a_missing_service_ends_the_wait(self):
        backend = self._backend()
        services = backend._api_resource.namespaces.return_value.services.return_value
        services.delete.return_value.execute.return_value = {}
        services.get.return_value.execute.side_effect = self._http_error(503)
        with pytest.raises(Exception):
            backend._delete_service('svc')
        services.get.return_value.execute.side_effect = [
            {},
            self._http_error(404),
        ]
        with patch('lithops.serverless.backends.gcp_cloudrun.cloudrun.time.sleep'):
            backend._delete_service('svc')

    def test_a_missing_service_is_already_gone(self):
        backend = self._backend()
        services = backend._api_resource.namespaces.return_value.services.return_value
        services.delete.return_value.execute.side_effect = self._http_error(404)
        backend._delete_service('svc')
        services.get.assert_not_called()

    def test_a_failed_delete_is_raised(self):
        backend = self._backend()
        services = backend._api_resource.namespaces.return_value.services.return_value
        services.delete.return_value.execute.side_effect = self._http_error(403)
        with pytest.raises(Exception):
            backend._delete_service('svc')
        services.get.assert_not_called()

    def test_invoke_waits_as_long_as_the_runtime(self, monkeypatch):
        backend = self._backend()
        backend.cr_config = {'runtime_timeout': 300}
        backend._format_image_name = lambda runtime_name: 'img'
        backend._format_service_name = lambda img_name, memory: 'svc'
        backend._get_url_and_token = lambda service_name: ('https://svc', 'tok')
        seen = {}

        def post(url, data, headers, timeout):
            seen['timeout'] = timeout
            return SimpleNamespace(status_code=202, json=lambda: {'activationId': 'act'})

        monkeypatch.setattr(
            'lithops.serverless.backends.gcp_cloudrun.cloudrun.requests.post', post
        )
        assert backend.invoke('rt', 256, {}) == 'act'
        assert seen['timeout'] == 330

    def test_services_past_the_first_page_are_listed(self):
        backend = self._backend()
        services = backend._api_resource.namespaces.return_value.services.return_value

        def item(name):
            return {
                'metadata': {'name': name},
                'spec': {'template': {
                    'metadata': {'labels': {
                        'type': 'lithops-runtime', 'lithops-version': '3-8-1-dev0',
                    }},
                    'spec': {'containers': [{
                        'image': f'img-{name}',
                        'resources': {'limits': {'memory': '256Mi'}},
                    }]},
                }},
            }

        services.list.return_value.execute.side_effect = [
            {'items': [item('a')], 'metadata': {'continue': 'tok'}},
            {'items': [item('b')]},
        ]
        assert [row[3] for row in backend.list_runtimes()] == ['a', 'b']
        assert services.list.call_args_list[1].kwargs['continue_'] == 'tok'


@pytest.mark.parametrize('backend_name', ['gcp_functions', 'gcp_cloudrun'])
@pytest.mark.parametrize('explicit_project', [None, 'explicit-project'])
@pytest.mark.parametrize('use_file', [False, True])
def test_gcp_project_override_and_credentials_fallback(monkeypatch, backend_name, explicit_project, use_file, tmp_path):
    import importlib

    filename, class_name, config_attr = {
        'gcp_functions': ('gcp_functions', 'GCPFunctionsBackend', 'gcf_config'),
        'gcp_cloudrun': ('cloudrun', 'GCPCloudRunBackend', 'cr_config'),
    }[backend_name]
    pytest.importorskip('googleapiclient')
    pytest.importorskip('google_auth_httplib2')
    if backend_name == 'gcp_functions':
        pytest.importorskip('google.cloud.pubsub_v1')
    module = importlib.import_module(f'lithops.serverless.backends.{backend_name}.{filename}')
    backend = getattr(module, class_name).__new__(getattr(module, class_name))
    backend.region = 'us-east1'
    credentials_file = tmp_path / 'credentials.json'
    credentials_file.write_text('{}')
    backend.credentials_path = str(credentials_file) if use_file else None
    setattr(backend, config_attr, {'project_name': explicit_project})
    credentials = MagicMock(project_id='credentials-project', service_account_email='service@example.com')
    monkeypatch.setattr(module.google.auth, 'default', lambda **kwargs: (credentials, 'adc-project'))
    monkeypatch.setattr(module.service_account.Credentials, 'from_service_account_file', lambda *a, **kw: credentials)
    monkeypatch.setattr(module, 'AuthorizedHttp', MagicMock())
    monkeypatch.setattr(module, 'build', MagicMock())
    if backend_name == 'gcp_functions':
        monkeypatch.setattr(module.pubsub_v1, 'PublisherClient', MagicMock())
        monkeypatch.setattr(module.jwt.Credentials, 'from_service_account_file', MagicMock())
    backend._build_api_resource()
    assert backend.project_name == (explicit_project or ('credentials-project' if use_file else 'adc-project'))
    assert getattr(backend, config_attr)['project_name'] == backend.project_name
