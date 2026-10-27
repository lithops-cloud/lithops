#
# Unit tests for the standalone compute frontend (not cloud backends).
#

import json
import os
import sys
import warnings
from contextlib import ExitStack
from types import SimpleNamespace
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
from lithops.utils import BackendType, is_unix_system
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

    def test_container_runtime_keeps_suffixed_interpreters_native(self):
        for runtime in ('python3.13t', 'python3.12d', 'python3-intel64'):
            assert is_container_runtime(runtime) is False, runtime
        assert is_container_runtime('registry/python') is True

    def test_worker_setup_script_uses_native_python(self):
        script = get_worker_setup_script(
            {'backend': 'vm', 'runtime': 'python3', 'use_gpu': False, 'vm': {}},
            {'master_ip': '10.0.0.1'},
        )
        assert '/usr/bin/python3' in script
        assert 'docker run --rm --name lithops_worker' not in script

    @pytest.mark.skipif(
        not is_unix_system(),
        reason='the docker worker script is built from the client uid/gid',
    )
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


class TestVMConfig:

    def test_the_documented_config_loads(self):
        """The vm.md config has no standalone section, and runtime sits under vm"""
        from lithops.config import default_config
        config = default_config(
            config_data={
                'lithops': {'backend': 'vm'},
                'vm': {'ip_address': '1.2.3.4', 'ssh_username': 'u', 'runtime': 'img:1'},
            },
            load_storage_config=False,
        )
        standalone = config['standalone']
        assert standalone['exec_mode'] == 'consume'
        assert standalone['runtime'] == 'img:1'
        assert standalone['start_timeout'] == 300
        assert standalone['auto_dismantle'] is False
        assert 'runtime' not in config['vm']


class TestAzureSpotWorkers:

    @staticmethod
    def _created_vm(tmp_path, public, spot):
        pytest.importorskip('azure.identity')
        pytest.importorskip('azure.mgmt.compute')
        pytest.importorskip('azure.mgmt.network')
        from lithops.standalone.backends.azure_vms.azure_vms import VMInstance
        key = tmp_path / 'id_rsa'
        (tmp_path / 'id_rsa.pub').write_text('ssh-rsa AAAA')
        instance = VMInstance.__new__(VMInstance)
        instance.name = 'lithops-worker-1'
        instance.location = 'westeurope'
        instance.instance_type = 'Standard_D2s_v3'
        instance.public = public
        instance.public_ip = '1.2.3.4'
        instance.spot_instance = spot
        instance.ssh_credentials = {'username': 'ubuntu', 'key_filename': str(key)}
        instance.config = {
            'resource_group': 'rg', 'subnet_id': 's', 'security_group_id': 'sg',
            'floating_ip_id': 'ip', 'vnet_name': 'vnet',
        }
        instance.network_client = MagicMock()
        instance.compute_client = MagicMock()
        instance._create_instance()
        return instance.compute_client.virtual_machines.begin_create_or_update.call_args[0][2]

    def test_workers_are_spot_vms_when_requested(self, tmp_path):
        vm = self._created_vm(tmp_path, public=False, spot=True)
        assert vm.priority == 'Spot'
        assert vm.eviction_policy == 'Deallocate'
        assert vm.billing_profile.max_price == -1

    @pytest.mark.parametrize('public, spot', [(True, True), (False, False)])
    def test_the_master_and_unrequested_workers_are_regular_vms(self, tmp_path, public, spot):
        vm = self._created_vm(tmp_path, public=public, spot=spot)
        assert vm.priority is None


class TestAzureVMs:

    @pytest.fixture(autouse=True)
    def _need_azure(self):
        pytest.importorskip('azure.identity')
        pytest.importorskip('azure.mgmt.compute')
        pytest.importorskip('azure.mgmt.network')

    @staticmethod
    def _config(**extra):
        from lithops.standalone.backends.azure_vms.config import load_config
        config_data = {'azure_vms': {'resource_group': 'rg', 'subscription_id': 's', 'region': 'westeurope'}}
        config_data['azure_vms'].update(extra)
        load_config(config_data)
        return config_data['azure_vms']

    def test_workers_are_not_deleted_on_dismantle_by_default(self):
        # The docs and the config template say False, as True is not supported
        assert self._config()['delete_on_dismantle'] is False

    @pytest.mark.parametrize('ssh_username, home_dir', [
        ('ubuntu', '/home/ubuntu'), ('azureuser', '/home/azureuser'), ('root', '/root'),
    ])
    def test_the_home_dir_belongs_to_the_ssh_user(self, ssh_username, home_dir):
        from lithops.standalone.backends.azure_vms.azure_vms import VMInstance
        with patch.object(VMInstance, 'create_client'):
            instance = VMInstance('lithops-master', self._config(ssh_username=ssh_username))
        assert instance.home_dir == home_dir

    @staticmethod
    def _stoppable_vm():
        from lithops.standalone.backends.azure_vms.azure_vms import VMInstance
        instance = VMInstance.__new__(VMInstance)
        instance.name = 'lithops-worker-1'
        instance.public = False
        instance.private_ip = '10.0.0.4'
        instance.delete_on_dismantle = False
        instance.config = {'resource_group': 'rg'}
        instance.compute_client = MagicMock()
        return instance

    def test_stop_deallocates_the_vm(self):
        # A VM that is only powered off is still billed
        instance = self._stoppable_vm()
        instance.stop()
        vms = instance.compute_client.virtual_machines
        vms.begin_deallocate.assert_called_once_with('rg', 'lithops-worker-1')
        vms.begin_power_off.assert_not_called()

    def test_stop_inside_the_vm_powers_off_when_it_cannot_deallocate(self):
        from lithops.standalone.backends.azure_vms import azure_vms
        instance = self._stoppable_vm()
        instance.compute_client.virtual_machines.begin_deallocate.side_effect = Exception('no credentials')
        with patch.object(azure_vms.os.path, 'isfile', return_value=True), \
                patch.object(azure_vms.os, 'system') as system:
            instance.stop()
        system.assert_called_once_with('shutdown -h now')

    def test_stop_from_the_client_reports_a_vm_it_cannot_deallocate(self):
        from lithops.standalone.backends.azure_vms import azure_vms
        instance = self._stoppable_vm()
        instance.compute_client.virtual_machines.begin_deallocate.side_effect = Exception('forbidden')
        with patch.object(azure_vms.os.path, 'isfile', return_value=False), \
                patch.object(azure_vms.os, 'system') as system, \
                patch.object(azure_vms, 'logger') as log:
            instance.stop()
        system.assert_not_called()
        assert 'forbidden' in log.warning.call_args[0][0]


class _FakeMasterSSH:
    """Answers like the master service of a VM that is already set up"""

    def __init__(self, ip_address, ssh_credentials):
        self.ip_address = ip_address
        self.ssh_credentials = ssh_credentials
        self.commands = []
        self.downloads = []

    def run_remote_command(self, cmd, run_async=False):
        self.commands.append(cmd)
        if '/ping' in cmd:
            return json.dumps({'response': __version__}), ''
        if '/job/run' in cmd:
            return json.dumps({'activationId': 'abc'}), ''
        return '', ''

    def upload_local_file(self, local_src, remote_dst):
        pass

    def upload_data_to_file(self, data, remote_dst):
        pass

    def download_remote_file(self, remote_src, local_dst):
        self.downloads.append((remote_src, local_dst))

    def close(self):
        pass


class TestVMBackend:

    @staticmethod
    def _config(**vm_extra):
        from lithops.config import default_config
        vm = {'ip_address': '1.2.3.4', 'ssh_username': 'alice'}
        vm.update(vm_extra)
        config = default_config(
            config_data={'lithops': {'backend': 'vm'}, 'vm': vm}, load_storage_config=False
        )
        return config

    def _handler(self, **vm_extra):
        from lithops.config import extract_standalone_config
        config = self._config(**vm_extra)
        handler = StandaloneHandler(extract_standalone_config(config))
        return config, handler

    @pytest.mark.parametrize('ssh_username, home_dir', [('alice', '/home/alice'), ('root', '/root')])
    def test_the_master_uses_the_documented_ssh_username(self, ssh_username, home_dir):
        _, handler = self._handler(ssh_username=ssh_username)
        handler.init()
        master = handler.backend.master
        assert master.ssh_credentials['username'] == ssh_username
        assert master.home_dir == home_dir
        with patch('lithops.standalone.backends.vm.vm.SSHClient', _FakeMasterSSH):
            assert master.get_ssh_client().ssh_credentials['username'] == ssh_username

    def test_a_job_runs_and_is_cleared_through_the_handler(self):
        config, handler = self._handler()
        handler.init()
        payload = {
            'executor_id': 'sess-0', 'job_id': 'M000', 'job_key': 'sess-0-M000',
            'total_calls': 2, 'worker_processes': 'AUTO', 'config': config,
        }
        with patch('lithops.standalone.backends.vm.vm.SSHClient', _FakeMasterSSH):
            handler.invoke(payload)
            ssh = handler.backend.master.get_ssh_client()
            handler.clear({'sess-0-M000'})
            handler.clear()
        assert payload['worker_instances'][0]['name'] == handler.backend.master.name
        assert payload['worker_instances'][0]['ssh_credentials']['username'] == 'alice'
        assert any('/job/run' in cmd for cmd in ssh.commands)
        assert any('/job/stop' in cmd and 'sess-0-M000' in cmd for cmd in ssh.commands)
        assert handler.jobs == []

    def test_the_master_service_setup_fetches_the_key_of_the_ssh_user(self, tmp_path):
        _, handler = self._handler()
        handler.init()

        def handler_zip(path, files):
            open(path, 'w').close()

        with patch('lithops.standalone.backends.vm.vm.SSHClient', _FakeMasterSSH), \
                patch('lithops.standalone.standalone.TEMP_DIR', str(tmp_path)), \
                patch('lithops.standalone.standalone.create_handler_zip', side_effect=handler_zip):
            handler._setup_master_service()
            ssh = handler.backend.master.get_ssh_client()
        remote, local = ssh.downloads[0]
        assert remote == '/home/alice/.ssh/lithops_id_rsa.pub'
        assert local.startswith(handler.backend.cache_dir)

    def test_the_budget_keeper_gets_the_vm_it_runs_on(self):
        from lithops.config import extract_standalone_config
        standalone_config = extract_standalone_config(self._config())
        master_data = {
            'name': 'lithops-consume', 'instance_id': '0af1', 'private_ip': '1.2.3.4',
            'delete_on_dismantle': False, 'lithops_version': __version__,
        }
        keeper = BudgetKeeper(standalone_config, master_data)
        assert keeper.instance.name == 'lithops-consume'
        assert keeper.instance.private_ip == '1.2.3.4'
        assert keeper.instance.delete_on_dismantle is False

    def test_the_master_gets_the_instance_a_job_runs_on(self):
        _, handler = self._handler()
        worker_info = {
            'name': 'lithops-consume', 'private_ip': '1.2.3.4', 'instance_id': '0af1',
            'ssh_credentials': {'username': 'alice'}, 'instance_type': 'VM',
        }
        instance = handler.backend.get_instance(**worker_info, public=False)
        assert instance.name == 'lithops-consume'
        assert instance.instance_type == 'VM'
        assert instance.config['worker_processes'] == 'AUTO'


class TestIBMVPCRetries:

    @staticmethod
    def _wrapped(name, side_effect):
        pytest.importorskip('ibm_vpc')
        from lithops.standalone.backends.ibm_vpc.ibm_vpc import vpc_retry_on_except
        func = MagicMock(side_effect=side_effect)
        func.__name__ = name
        return func, vpc_retry_on_except(func)

    def test_an_ignored_404_is_not_retried(self):
        from ibm_cloud_sdk_core import ApiException
        func, wrapped = self._wrapped('delete_instance', ApiException(404, message='gone'))
        assert wrapped('i-1') is None
        func.assert_called_once_with('i-1')

    def test_a_404_on_another_method_is_raised(self):
        from ibm_cloud_sdk_core import ApiException
        func, wrapped = self._wrapped('get_instance', ApiException(404, message='gone'))
        with patch('lithops.standalone.backends.ibm_vpc.ibm_vpc.time.sleep'):
            with pytest.raises(ApiException):
                wrapped('i-1')
        assert func.call_count == 5

    def test_the_status_is_read_without_the_deprecated_attribute(self):
        from ibm_cloud_sdk_core import ApiException
        func, wrapped = self._wrapped('delete_instance', ApiException(404, message='gone'))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            assert wrapped('i-1') is None
        func.assert_called_once_with('i-1')
        assert not [w for w in caught if issubclass(w.category, DeprecationWarning)]

    def test_an_sdk_without_status_code_still_ignores_the_404(self):
        from ibm_cloud_sdk_core import ApiException

        class OldApiException(ApiException):
            # SDK versions before status_code only had a plain code attribute
            code = None

            def __init__(self, code, message=None):
                Exception.__init__(self, message)
                self.code = code

        func, wrapped = self._wrapped('delete_instance', OldApiException(404, message='gone'))
        assert wrapped('i-1') is None
        func.assert_called_once_with('i-1')


def _aws_backend_for_init():
    pytest.importorskip('boto3')
    from lithops.standalone.backends.aws_ec2.aws_ec2 import AWSEC2Backend
    backend = AWSEC2Backend.__new__(AWSEC2Backend)
    backend.mode = 'create'
    backend.config = {}
    backend.ec2_data = {}
    backend.user_key = 'abcd'
    backend.vpc_data_type = 'created'
    backend._init_created = None
    client = backend.ec2_client = MagicMock()
    client.describe_vpcs.return_value = {'Vpcs': []}
    client.create_vpc.return_value = {'Vpc': {'VpcId': 'vpc-0123456789'}}

    def deletes():
        return {
            name: getattr(client, name).call_count
            for name in ('delete_security_group', 'delete_internet_gateway',
                         'delete_subnet', 'delete_vpc', 'delete_key_pair')
        }
    return backend, '_load_ec2_data', '_create_vpc', '_create_subnets', {'delete_vpc': 1}, deletes


def _gcp_backend_for_init():
    pytest.importorskip('googleapiclient')
    pytest.importorskip('google_auth_httplib2')
    from lithops.standalone.backends.gcp_compute_engine.gcp_compute_engine import GCPComputeEngineBackend
    backend = GCPComputeEngineBackend.__new__(GCPComputeEngineBackend)
    backend.mode = 'create'
    backend.config = {'network_cidr': '10.0.0.0/16', 'subnet_cidr': '10.0.0.0/20'}
    backend.gce_data = {}
    backend.project_name = 'project'
    backend.region = 'us-east1'
    backend.network_name = None
    backend.network_key = None
    backend.vpc_data_type = 'created'
    backend._init_created = None
    backend._wait_operation = MagicMock()
    backend._resource_exists = MagicMock(return_value=False)
    client = backend.compute_client = MagicMock()
    # The network, its subnet and both firewalls are created, then the Cloud NAT router fails
    client.routers.return_value.insert.side_effect = Exception('quota')

    def deletes():
        return {
            name: getattr(client, name).return_value.delete.call_count
            for name in ('networks', 'subnetworks', 'firewalls', 'routers')
        }
    deleted = {'networks': 1, 'subnetworks': 1, 'firewalls': 2}
    return backend, '_load_gce_data', '_create_network', '_create_ssh_key', deleted, deletes


def _azure_backend_for_init():
    pytest.importorskip('azure.identity')
    pytest.importorskip('azure.mgmt.compute')
    pytest.importorskip('azure.mgmt.network')
    from lithops.standalone.backends.azure_vms.azure_vms import AzureVMSBackend
    backend = AzureVMSBackend.__new__(AzureVMSBackend)
    backend.mode = 'create'
    backend.config = {'resource_group': 'rg'}
    backend.azure_data = {}
    backend.location = 'westeurope'
    backend.vnet_name = None
    backend.vnet_key = None
    backend.vnet_data_type = 'created'
    backend._init_created = None
    client = backend.network_client = MagicMock()
    client.virtual_networks.list.return_value = []
    vnet = client.virtual_networks.begin_create_or_update.return_value.result.return_value
    vnet.id = '/vnets/lithops-vnet-abc123'
    vnet.name = 'lithops-vnet-abc123'

    def deletes():
        return {
            name: getattr(client, name).begin_delete.call_count
            for name in ('public_ip_addresses', 'network_security_groups', 'subnets', 'virtual_networks')
        }
    return backend, '_load_azure_vms_data', '_create_vnet', '_create_subnet', {'virtual_networks': 1}, deletes


def _ibm_backend_for_init():
    pytest.importorskip('ibm_vpc')
    from lithops.standalone.backends.ibm_vpc.ibm_vpc import IBMVPCBackend
    backend = IBMVPCBackend.__new__(IBMVPCBackend)
    backend.mode = 'create'
    backend.config = {'resource_group_id': 'rg'}
    backend.vpc_data = {}
    backend.vpc_name = None
    backend.vpc_key = None
    backend.iam_api_key = 'abcd'
    backend.verify_resources = True
    backend.vpc_data_type = 'created'
    backend._init_created = None
    client = backend.vpc_cli = MagicMock()
    client.list_vpcs.return_value.get_result.return_value = {'vpcs': []}
    client.create_vpc.return_value.result = {'id': 'r006-vpc123456', 'default_security_group': {'id': 'sg'}}
    client.get_security_group.return_value.get_result.return_value = {'rules': []}

    def deletes():
        return {
            name: getattr(client, name).call_count
            for name in ('unset_subnet_public_gateway', 'delete_public_gateway',
                         'delete_subnet', 'delete_vpc', 'delete_key')
        }
    return backend, '_load_vpc_data', '_create_vpc', '_create_ssh_key', {'delete_vpc': 1}, deletes


class TestVMInitRollback:
    """
    A failed init() deletes what that init() created, and only that
    """

    BACKENDS = [_aws_backend_for_init, _gcp_backend_for_init, _azure_backend_for_init, _ibm_backend_for_init]

    @pytest.mark.parametrize('make_backend', BACKENDS)
    def test_a_failure_before_creating_anything_only_drops_the_cache(self, make_backend):
        backend, load_data, first_step, _, _, deletes = make_backend()
        with patch.object(backend, load_data), \
                patch.object(backend, '_delete_vpc_data') as delete_vpc_data, \
                patch.object(backend, first_step, side_effect=Exception('boom')):
            with pytest.raises(Exception, match='boom'):
                backend.init()
        delete_vpc_data.assert_called_once()
        assert not any(deletes().values())
        assert backend._init_created is None

    @pytest.mark.parametrize('make_backend', BACKENDS)
    def test_a_failure_after_creating_network_resources_deletes_them(self, make_backend):
        backend, load_data, _, next_step, deleted, deletes = make_backend()
        with patch.object(backend, load_data), \
                patch.object(backend, '_delete_vpc_data') as delete_vpc_data, \
                patch.object(backend, next_step, side_effect=Exception('quota')):
            with pytest.raises(Exception, match='quota'):
                backend.init()
        delete_vpc_data.assert_called_once()
        assert {name: count for name, count in deletes().items() if count} == deleted
        assert backend._init_created is None

    # A resource is rolled back even when the call that fails comes right after
    # creating it, in the same step

    @staticmethod
    def _failed_init(backend, load_data, *skipped_steps):
        with ExitStack() as stack:
            stack.enter_context(patch.object(backend, load_data))
            stack.enter_context(patch.object(backend, '_delete_vpc_data'))
            for step in skipped_steps:
                stack.enter_context(patch.object(backend, step))
            with pytest.raises(Exception, match='quota'):
                backend.init()

    @staticmethod
    def _local_ssh_keys(stack, tmp_path):
        (tmp_path / '.ssh').mkdir()

        def ssh_keygen(cmd):
            key_filename = cmd.split(' -f ')[1].split(' ')[0]
            for path in (key_filename, f'{key_filename}.pub'):
                with open(path, 'w') as f:
                    f.write('ssh-rsa AAAA')
            return 0
        stack.enter_context(patch('os.system', side_effect=ssh_keygen))
        stack.enter_context(patch('os.path.expanduser', side_effect=lambda p: p.replace('~', str(tmp_path))))
        return tmp_path / '.ssh'

    @pytest.mark.parametrize('failing, deleted', [
        ('subnetworks', {'networks': 1}),
        ('firewall', {'networks': 1, 'subnetworks': 1}),
        ('internal_firewall', {'networks': 1, 'subnetworks': 1, 'firewalls': 1}),
    ])
    def test_gcp_deletes_the_network_resources_created_before_a_failure(self, failing, deleted):
        backend, load_data, _, _, _, deletes = _gcp_backend_for_init()
        client = backend.compute_client
        client.routers.return_value.insert.side_effect = None
        if failing == 'subnetworks':
            client.subnetworks.return_value.insert.side_effect = Exception('quota')
        else:
            first = Exception('quota') if failing == 'firewall' else MagicMock()
            client.firewalls.return_value.insert.side_effect = [first, Exception('quota')]
        self._failed_init(backend, load_data)
        assert {name: count for name, count in deletes().items() if count} == deleted

    def test_aws_deletes_a_vpc_that_could_not_be_tagged(self):
        backend, load_data, _, _, _, deletes = _aws_backend_for_init()
        backend.ec2_client.create_tags.side_effect = Exception('quota')
        self._failed_init(backend, load_data)
        assert {name: count for name, count in deletes().items() if count} == {'delete_vpc': 1}

    def test_aws_deletes_an_internet_gateway_that_could_not_be_attached(self):
        backend, load_data, _, _, _, deletes = _aws_backend_for_init()
        from botocore.exceptions import ClientError
        client = backend.ec2_client
        client.describe_internet_gateways.return_value = {'InternetGateways': []}
        client.create_internet_gateway.return_value = {'InternetGateway': {'InternetGatewayId': 'igw-1'}}
        client.attach_internet_gateway.side_effect = Exception('quota')
        client.detach_internet_gateway.side_effect = ClientError(
            {'Error': {'Code': 'Gateway.NotAttached', 'Message': 'not attached'}}, 'DetachInternetGateway'
        )
        with patch('lithops.standalone.backends.aws_ec2.aws_ec2.logger') as logger:
            self._failed_init(backend, load_data, '_create_subnets')
        assert {name: count for name, count in deletes().items() if count} == {
            'delete_internet_gateway': 1, 'delete_vpc': 1
        }
        # A gateway that never got attached is not worth a warning
        logger.warning.assert_not_called()

    def test_aws_deletes_a_security_group_whose_rules_could_not_be_added(self):
        backend, load_data, _, _, _, deletes = _aws_backend_for_init()
        client = backend.ec2_client
        client.describe_security_groups.return_value = {'SecurityGroups': []}
        client.create_security_group.return_value = {'GroupId': 'sg-1'}
        client.authorize_security_group_ingress.side_effect = Exception('quota')
        self._failed_init(backend, load_data, '_create_subnets', '_create_internet_gateway', '_create_routing_tables')
        assert {name: count for name, count in deletes().items() if count} == {
            'delete_security_group': 1, 'delete_vpc': 1
        }

    def test_aws_deletes_a_local_ssh_key_that_could_not_be_imported(self, tmp_path):
        backend, load_data, _, _, _, _ = _aws_backend_for_init()
        backend.name = 'aws_ec2'
        backend.ec2_client.import_key_pair.side_effect = Exception('quota')
        with ExitStack() as stack:
            ssh_dir = self._local_ssh_keys(stack, tmp_path)
            self._failed_init(
                backend, load_data, '_create_subnets', '_create_internet_gateway',
                '_create_routing_tables', '_create_security_group'
            )
        assert list(ssh_dir.iterdir()) == []

    def test_ibm_deletes_a_floating_ip_it_allocated(self):
        backend, load_data, _, _, _, _ = _ibm_backend_for_init()
        backend.config['vpc_id'] = 'r006-vpc123456'
        backend.config['zone_name'] = 'eu-de-1'
        backend.vpc_cli.list_floating_ips.return_value.get_result.return_value = {
            'floating_ips': []
        }
        backend.vpc_cli.create_floating_ip.return_value.result = {
            'address': '1.2.3.4', 'id': 'fip-new'
        }
        with patch.object(backend, '_request_image_id', side_effect=Exception('quota')):
            self._failed_init(
                backend, load_data,
                '_create_vpc', '_create_ssh_key', '_create_subnet', '_create_gateway',
            )
        backend.vpc_cli.delete_floating_ip.assert_called_once_with(id='fip-new')

    def test_aws_spot_price_without_history_raises(self):
        pytest.importorskip('boto3')
        from lithops.standalone.backends.aws_ec2.aws_ec2 import AWSEC2Backend
        backend = AWSEC2Backend.__new__(AWSEC2Backend)
        backend.config = {
            'request_spot_instances': True,
            'worker_instance_type': 't2.micro',
        }
        backend.ec2_client = MagicMock()
        backend.ec2_client.describe_spot_price_history.return_value = {
            'SpotPriceHistory': []
        }
        with pytest.raises(ValueError, match='No spot price history for worker instance type t2.micro'):
            backend._request_spot_price()

    def test_delete_vms_reads_every_page_of_instances(self):
        pytest.importorskip('boto3')
        from lithops.standalone.backends.aws_ec2.aws_ec2 import AWSEC2Backend
        backend = AWSEC2Backend.__new__(AWSEC2Backend)
        backend.vpc_name = 'lithops-vpc'
        backend.ec2_data = {
            'vpc_id': 'vpc-1', 'vpc_data_type': 'provided', 'master_name': 'master',
        }
        backend.cache_dir = '/tmp'
        backend.ec2_client = MagicMock()

        def instance(instance_id, name):
            return {
                'InstanceId': instance_id,
                'State': {'Name': 'running'},
                'VpcId': 'vpc-1',
                'Tags': [{'Key': 'Name', 'Value': name}],
            }

        backend.ec2_client.get_paginator.return_value.paginate.return_value = [
            {'Reservations': [{'Instances': [instance('i-1', 'lithops-worker-a')]}]},
            {'Reservations': [{'Instances': [
                instance('i-2', 'lithops-worker-b'), instance('i-3', 'other'),
            ]}]},
        ]
        backend._delete_vm_instances()
        backend.ec2_client.terminate_instances.assert_called_once_with(
            InstanceIds=['i-1', 'i-2']
        )

    def test_gcp_clean_reads_every_page_of_instances(self):
        pytest.importorskip('googleapiclient')
        pytest.importorskip('google_auth_httplib2')
        from lithops.standalone.backends.gcp_compute_engine.gcp_compute_engine import GCPComputeEngineBackend
        backend = GCPComputeEngineBackend.__new__(GCPComputeEngineBackend)
        backend.network_name = 'lithops-net'
        backend.project_name = 'project'
        backend.zone = 'us-east1-b'
        backend.compute_client = MagicMock()
        backend._wait_operation = MagicMock()

        first = MagicMock()
        first.execute.return_value = {
            'items': [{'name': 'lithops-worker-a'}], 'nextPageToken': 'tok',
        }
        second = MagicMock()
        second.execute.return_value = {'items': [
            {'name': 'lithops-worker-b'}, {'name': 'other'},
        ]}
        empty = MagicMock()
        empty.execute.return_value = {'items': []}
        instances = backend.compute_client.instances.return_value
        instances.list.side_effect = [first, empty]
        instances.list_next.side_effect = [second, None, None]
        instances.delete.return_value.execute.return_value = {'name': 'op'}

        backend._delete_vm_instances()

        deleted = [
            call.kwargs['instance']
            for call in instances.delete.call_args_list
        ]
        assert deleted == ['lithops-worker-a', 'lithops-worker-b']

    @staticmethod
    def _vpc_page(items, key, start=None):
        result = {key: items}
        if start:
            result['next'] = {
                'href': f'https://example/v1/{key}?limit=50&start={start}'
            }
        response = MagicMock()
        response.get_result.return_value = result
        return response

    def test_ibm_clean_reads_every_page_of_instances(self):
        pytest.importorskip('ibm_vpc')
        from lithops.standalone.backends.ibm_vpc.ibm_vpc import IBMVPCBackend
        backend = IBMVPCBackend.__new__(IBMVPCBackend)
        backend.vpc_name = 'lithops-vpc'
        backend.vpc_data = {
            'vpc_id': 'vpc-1', 'vpc_data_type': 'provided', 'master_name': 'master',
        }
        backend.cache_dir = '/tmp'
        backend.vpc_cli = MagicMock()
        backend.vpc_cli.list_instances.side_effect = [
            self._vpc_page(
                [{'name': 'lithops-worker-a', 'id': 'i-1', 'vpc': {'id': 'vpc-1'}}],
                'instances', start='tok',
            ),
            self._vpc_page([
                {'name': 'lithops-worker-b', 'id': 'i-2', 'vpc': {'id': 'vpc-1'}},
                {'name': 'other', 'id': 'i-3', 'vpc': {'id': 'vpc-1'}},
            ], 'instances'),
            self._vpc_page([], 'instances'),
        ]

        backend._delete_vm_instances()

        assert backend.vpc_cli.list_instances.call_args_list[1].kwargs['start'] == 'tok'
        deleted = {call.args[0] for call in backend.vpc_cli.delete_instance.call_args_list}
        assert deleted == {'i-1', 'i-2'}

    def test_ibm_image_lookup_reads_the_page_after_the_first(self):
        pytest.importorskip('ibm_vpc')
        from lithops.standalone.backends.ibm_vpc.ibm_vpc import IBMVPCBackend
        backend = IBMVPCBackend.__new__(IBMVPCBackend)
        backend.config = {'resource_group_id': 'rg'}
        backend.vpc_data = {}
        backend.vpc_cli = MagicMock()
        backend.vpc_cli.list_images.side_effect = [
            self._vpc_page([{'id': 'img-win', 'name': 'ibm-windows-1'}], 'images', start='tok'),
            self._vpc_page(
                [{'id': 'img-ubuntu', 'name': 'ibm-ubuntu-24-04-amd64-1'}], 'images'
            ),
            self._vpc_page([], 'images'),
        ]

        backend._request_image_id()

        assert backend.config['image_id'] == 'img-ubuntu'
        assert backend.vpc_cli.list_images.call_args_list[1].kwargs['start'] == 'tok'

    def test_ibm_reuses_a_floating_ip_past_the_first_page(self):
        pytest.importorskip('ibm_vpc')
        from lithops.standalone.backends.ibm_vpc.ibm_vpc import IBMVPCBackend
        backend = IBMVPCBackend.__new__(IBMVPCBackend)
        backend.config = {'zone_name': 'eu-de-1', 'resource_group_id': 'rg'}
        backend.vpc_cli = MagicMock()
        free = {
            'name': 'lithops-recyclable-abcd', 'id': 'fip-1', 'address': '1.2.3.4',
            'zone': {'name': 'eu-de-1'},
        }
        backend.vpc_cli.list_floating_ips.side_effect = [
            self._vpc_page([], 'floating_ips', start='tok'),
            self._vpc_page([free], 'floating_ips'),
        ]

        assert backend._get_or_create_floating_ip() == ('1.2.3.4', 'fip-1')
        backend.vpc_cli.create_floating_ip.assert_not_called()
        assert backend.vpc_cli.list_floating_ips.call_args_list[1].kwargs['start'] == 'tok'

    def test_ibm_deletes_a_local_ssh_key_that_could_not_be_registered(self, tmp_path):
        backend, load_data, _, _, _, deletes = _ibm_backend_for_init()
        from ibm_cloud_sdk_core import ApiException
        backend.name = 'ibm_vpc'
        backend.config['vpc_id'] = 'r006-vpc123456'
        backend.vpc_cli.create_key.side_effect = ApiException(500, message='quota')
        with ExitStack() as stack:
            ssh_dir = self._local_ssh_keys(stack, tmp_path)
            self._failed_init(backend, load_data)
        assert list(ssh_dir.iterdir()) == []
        assert not any(deletes().values())


class TestAWSDeleteVPC:

    @staticmethod
    def _backend(**errors):
        pytest.importorskip('boto3')
        from lithops.standalone.backends.aws_ec2.aws_ec2 import AWSEC2Backend
        backend = AWSEC2Backend.__new__(AWSEC2Backend)
        backend.vpc_name = 'lithops-vpc'
        backend.ec2_data = {
            'vpc_data_type': 'created', 'security_group_id': 'sg-1', 'public_subnet_id': 'subnet-1',
            'internet_gateway_id': 'igw-1', 'vpc_id': 'vpc-1',
        }
        backend.ec2_client = MagicMock()
        for method, error in errors.items():
            getattr(backend.ec2_client, method).side_effect = error
        return backend

    @staticmethod
    def _client_error(message, status=400):
        pytest.importorskip('botocore')
        from botocore.exceptions import ClientError
        return ClientError(
            {'Error': {'Code': 'Some.Code', 'Message': message}, 'ResponseMetadata': {'HTTPStatusCode': status}},
            'Operation'
        )

    def test_every_resource_is_deleted_in_order(self):
        backend = self._backend()
        with patch('lithops.standalone.backends.aws_ec2.aws_ec2.logger') as logger:
            assert backend._delete_vpc() is True
        assert [c.args[0] for c in logger.debug.call_args_list] == [
            'Deleting security group sg-1', 'Deleting public subnet-1', 'Detaching internet gateway igw-1',
            'Deleting internet gateway igw-1', 'Deleting VPC vpc-1',
        ]
        assert backend.ec2_client.method_calls == [
            ('delete_security_group', (), {'GroupId': 'sg-1'}),
            ('delete_subnet', (), {'SubnetId': 'subnet-1'}),
            ('detach_internet_gateway', (), {'InternetGatewayId': 'igw-1', 'VpcId': 'vpc-1'}),
            ('delete_internet_gateway', (), {'InternetGatewayId': 'igw-1'}),
            ('delete_vpc', (), {'VpcId': 'vpc-1'}),
        ]

    def test_a_resource_that_does_not_exist_counts_as_deleted(self):
        backend = self._backend(delete_subnet=self._client_error("The subnet ID 'subnet-1' does not exist"))
        assert backend._delete_vpc() is True
        assert len(backend.ec2_client.method_calls) == 5

    def test_any_other_error_is_reported_and_the_rest_still_deleted(self):
        backend = self._backend(
            detach_internet_gateway=self._client_error('Gateway does not exist', status=404),
            delete_vpc=self._client_error('The vpc has dependencies and cannot be deleted'),
        )
        with patch('lithops.standalone.backends.aws_ec2.aws_ec2.logger') as logger:
            assert backend._delete_vpc() is False
        assert len(backend.ec2_client.method_calls) == 5
        logger.error.assert_called_once()

    def test_an_error_that_is_not_a_client_error_is_raised(self):
        backend = self._backend(delete_subnet=ValueError('bad'))
        with pytest.raises(ValueError):
            backend._delete_vpc()
        assert [c[0] for c in backend.ec2_client.method_calls] == ['delete_security_group', 'delete_subnet']

    def test_a_missing_resource_id_stops_after_the_earlier_deletions(self):
        backend = self._backend()
        del backend.ec2_data['internet_gateway_id']
        with pytest.raises(KeyError):
            backend._delete_vpc()
        assert [c[0] for c in backend.ec2_client.method_calls] == ['delete_security_group', 'delete_subnet']

    def test_a_provided_vpc_is_left_alone(self):
        backend = self._backend()
        backend.ec2_data['vpc_data_type'] = 'provided'
        assert backend._delete_vpc() is None
        assert backend.ec2_client.method_calls == []


class TestBudgetKeeper:

    def test_running_attribute_and_job_tracking(self):
        keeper, _instance = _make_keeper()
        assert keeper.running is False
        assert not hasattr(keeper, 'runing')
        assert keeper._all_jobs_done() is False
        keeper.add_job('job-a')
        assert keeper.jobs['job-a'] == JobStatus.RUNNING.value
        assert keeper._all_jobs_done() is False
        keeper.jobs['job-a'] = JobStatus.DONE.value
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

    def test_request_from_worker_gives_the_master_time_to_answer(self):
        handler = _make_handler()
        handler.is_lithops_worker = True
        with patch('lithops.standalone.standalone.requests.get') as get:
            get.return_value.json.return_value = []
            handler._make_request('GET', 'worker/list')
            assert get.call_args.kwargs['timeout'] == (10, 60)
            get.return_value.json.return_value = {'preinstalls': []}
            handler._make_request('GET', 'metadata', {'runtime': 'img'})
            assert get.call_args.kwargs['timeout'] == (10, None)
        with patch('lithops.standalone.standalone.requests.post') as post:
            post.return_value.content = b''
            handler._make_request('POST', 'clean')
            assert post.call_args.kwargs['timeout'] == (10, 60)

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

    def test_clear_stops_only_the_given_jobs(self):
        # get_result(fs1) must not cancel the job of fs2, still running
        handler = _make_handler('create')
        handler.jobs = ['sess-0-M000', 'sess-0-M001']
        handler._make_request = MagicMock(return_value=None)
        handler.clear({'sess-0-M000'})
        handler._make_request.assert_called_once_with('POST', 'job/stop', ['sess-0-M000'])
        assert handler.jobs == ['sess-0-M001']
        # The workers are still running the other job
        handler.backend.clear.assert_not_called()

    def test_clear_stops_the_create_mode_workers_once_no_job_is_left(self):
        handler = _make_handler('create')
        handler.jobs = ['sess-0-M000', 'sess-0-M001']
        handler._make_request = MagicMock(return_value=None)
        handler.clear({'sess-0-M000'})
        handler.clear({'sess-0-M001'})
        assert handler._make_request.call_args_list[1][0][2] == ['sess-0-M001']
        assert handler.jobs == []
        handler.backend.clear.assert_called_once_with({'sess-0-M001'})

    def test_clear_without_job_keys_stops_every_job_and_the_workers(self):
        handler = _make_handler('create')
        handler.jobs = ['sess-0-M000', 'sess-0-M001']
        handler._make_request = MagicMock(return_value=None)
        handler.clear()
        handler._make_request.assert_called_once_with(
            'POST', 'job/stop', ['sess-0-M000', 'sess-0-M001']
        )
        assert handler.jobs == []
        handler.backend.clear.assert_called_once_with(None)

    def _master_setup_failure(self, **master_errors):
        handler = self._ready_handler('create')
        workers = [MagicMock(name='w0'), MagicMock(name='w1')]
        handler.backend.workers = list(workers)
        handler._create_workers = MagicMock(return_value=list(workers))
        handler._is_master_service_ready = MagicMock(return_value=False)
        for method, error in master_errors.items():
            getattr(handler.backend.master, method).side_effect = error
        return handler, workers

    @pytest.mark.parametrize('method', ['create', 'wait_ready'])
    def test_invoke_stops_its_workers_when_the_master_cannot_be_set_up(self, method):
        handler, workers = self._master_setup_failure(**{method: Exception('quota')})
        with pytest.raises(Exception, match='quota'):
            handler.invoke(self._create_payload())
        for worker in workers:
            worker.stop.assert_called_once()
        assert handler.backend.workers == []
        assert handler.jobs == []

    def test_invoke_keeps_the_master_error_when_a_worker_cannot_be_stopped(self):
        handler, workers = self._master_setup_failure(create=Exception('quota'))
        workers[0].stop.side_effect = Exception('stop failed')
        with patch('lithops.standalone.standalone.logger') as log:
            with pytest.raises(Exception, match='quota'):
                handler.invoke(self._create_payload())
        workers[1].stop.assert_called_once()
        assert 'stop failed' in log.error.call_args[0][0]

    def test_invoke_does_not_stop_workers_a_dismantle_already_stopped(self):
        handler, workers = self._master_setup_failure()
        handler._validate_master_service_setup = MagicMock()

        def dismantle_and_fail():
            handler.backend.workers = []
            raise Exception('readiness probe expired')

        handler._wait_master_service_ready = MagicMock(side_effect=dismantle_and_fail)
        with pytest.raises(Exception, match='readiness probe expired'):
            handler.invoke(self._create_payload())
        for worker in workers:
            worker.stop.assert_not_called()

    def test_request_from_worker_sends_the_body_of_a_get(self):
        handler = _make_handler()
        handler.is_lithops_worker = True
        payload = {'worker_instance_type': 'big', 'worker_processes': 2, 'runtime_name': 'python3'}
        with patch('lithops.standalone.standalone.requests.get') as get:
            get.return_value.json.return_value = []
            assert handler._make_request('GET', 'worker/get', payload) == []
        assert json.loads(get.call_args.kwargs['data']) == payload

    def test_request_from_worker_raises_on_an_error_payload(self):
        handler = _make_handler()
        handler.is_lithops_worker = True
        with patch('lithops.standalone.standalone.requests.get') as get:
            get.return_value.status_code = 404
            get.return_value.json.return_value = {'error': 'not a dictionary'}
            with pytest.raises(ValueError, match='not a dictionary'):
                handler._make_request('GET', 'metadata', {'runtime': 'python3'})

    def test_request_via_ssh_raises_on_an_error_payload(self):
        handler = _make_handler()
        ssh = handler.backend.master.get_ssh_client.return_value
        ssh.run_remote_command.return_value = ('{"error": "not a dictionary"}', '')
        with pytest.raises(ValueError, match='not a dictionary'):
            handler._make_request('GET', 'metadata', {'runtime': 'python3'})

    def test_an_error_from_the_master_is_no_free_worker(self):
        # The error dict used to be counted as one free worker
        handler = _make_handler('reuse')
        ssh = handler.backend.master.get_ssh_client.return_value
        ssh.run_remote_command.return_value = ('{"error": "bad request"}', '')
        assert handler._get_workers_on_master('big', 2, 'python3') == []


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


class TestAzureNetworkSerialization:
    """Check the actual SDK serialization, without contacting Azure."""

    @staticmethod
    def _wire(model):
        if hasattr(model, 'as_dict'):
            return model.as_dict()
        return model.serialize()

    def test_network_resources_use_arm_properties(self):
        backend, *_ = _azure_backend_for_init()
        from azure.core.exceptions import ResourceNotFoundError
        backend._init_created = set()
        client = backend.network_client
        client.subnets.list.return_value = []
        client.network_security_groups.get.side_effect = ResourceNotFoundError('missing')
        client.public_ip_addresses.get.side_effect = ResourceNotFoundError('missing')

        backend._create_vnet()
        body = self._wire(client.virtual_networks.begin_create_or_update.call_args.args[2])
        assert body['properties']['addressSpace']['addressPrefixes'] == ['10.0.0.0/16']
        assert 'address_space' not in body

        backend._create_subnet()
        body = self._wire(client.subnets.begin_create_or_update.call_args.args[3])
        assert body['properties']['addressPrefix'] == '10.0.0.0/24'
        assert body['properties']['defaultOutboundAccess'] is True

        backend._create_security_group()
        body = self._wire(client.network_security_groups.begin_create_or_update.call_args.args[2])
        rules = body['properties']['securityRules']
        assert len(rules) == 4
        assert rules[0]['properties']['destinationPortRange'] == '22'
        assert rules[1]['properties']['sourceAddressPrefix'] == '10.0.0.0/24'

        backend._create_master_floating_ip()
        body = self._wire(client.public_ip_addresses.begin_create_or_update.call_args.args[2])
        assert body['sku']['name'] == 'Standard'
        assert body['properties']['publicIPAllocationMethod'] == 'Static'
        assert body['properties']['publicIPAddressVersion'] == 'IPv4'

    @pytest.mark.parametrize('public', [False, True])
    def test_nic_references_are_serialized(self, tmp_path, monkeypatch, public):
        pytest.importorskip('azure.mgmt.network')
        from lithops.standalone.backends.azure_vms import azure_vms
        captured = []
        model = azure_vms.NetworkInterface

        def capture(**kwargs):
            nic = model(**kwargs)
            captured.append(nic)
            return nic

        monkeypatch.setattr(azure_vms, 'NetworkInterface', capture)
        TestAzureSpotWorkers._created_vm(tmp_path, public=public, spot=False)
        body = self._wire(captured[0])['properties']
        assert body['networkSecurityGroup']['id'] == 'sg'
        ip = body['ipConfigurations'][0]['properties']
        assert ip['subnet']['id'] == 's'
        if public:
            assert ip['publicIPAddress']['id'] == 'ip'
        else:
            assert 'publicIPAddress' not in ip


class TestGceCleanupMissingInstances:
    @staticmethod
    def _backend():
        pytest.importorskip('googleapiclient')
        from lithops.standalone.backends.gcp_compute_engine.gcp_compute_engine import GCPComputeEngineBackend
        backend = GCPComputeEngineBackend.__new__(GCPComputeEngineBackend)
        backend.compute_client = MagicMock()
        backend.project_name = 'project'
        backend.zone = 'us-east1-b'
        backend.network_name = 'network'
        return backend

    @pytest.mark.parametrize('async_error', [False, True])
    def test_missing_vm_does_not_stop_cleanup(self, async_error):
        backend = self._backend()
        from googleapiclient.errors import HttpError
        backend._iter_zone_instances = MagicMock(side_effect=[[
            {'name': 'lithops-worker-gone'}, {'name': 'lithops-worker-next'},
        ], []])
        delete = backend.compute_client.instances.return_value.delete.return_value.execute
        get_operation = backend.compute_client.zoneOperations.return_value.get.return_value.execute
        if async_error:
            delete.side_effect = [{'name': 'gone-op'}, {'name': 'next-op'}]
            get_operation.side_effect = [
                {'status': 'DONE', 'error': {'errors': [{'code': 'RESOURCE_NOT_FOUND'}]}},
                {'status': 'DONE'},
            ]
        else:
            delete.side_effect = [HttpError(SimpleNamespace(status=404, reason='gone'), b'{}'), {'name': 'next-op'}]
            get_operation.return_value = {'status': 'DONE'}
        backend._delete_vm_instances()
        calls = backend.compute_client.instances.return_value.delete.call_args_list
        assert [call.kwargs['instance'] for call in calls] == ['lithops-worker-gone', 'lithops-worker-next']

    @pytest.mark.parametrize('ignore_not_found,codes', [
        (False, ['RESOURCE_NOT_FOUND']),
        (True, ['PERMISSIONS_ERROR']),
        (True, ['RESOURCE_NOT_FOUND', 'PERMISSIONS_ERROR']),
        (True, []),
    ])
    def test_other_operation_errors_still_raise(self, ignore_not_found, codes):
        backend = self._backend()
        backend.compute_client.zoneOperations.return_value.get.return_value.execute.return_value = {
            'status': 'DONE', 'error': {'errors': [{'code': code} for code in codes]},
        }
        with pytest.raises(Exception):
            backend._wait_operation('op', ignore_not_found=ignore_not_found)

    def test_permission_failure_still_raises(self):
        backend = self._backend()
        from googleapiclient.errors import HttpError
        backend._iter_zone_instances = MagicMock(return_value=[{'name': 'lithops-worker-denied'}])
        backend.compute_client.instances.return_value.delete.return_value.execute.side_effect = HttpError(
            SimpleNamespace(status=403, reason='denied'), b'{}',
        )
        with pytest.raises(HttpError):
            backend._delete_vm_instances()
