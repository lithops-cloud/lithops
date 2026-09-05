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

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest
import yaml

from lithops import constants as c
from lithops.config import (
    _ensure_lithops_section,
    _resolve_mode_and_backend,
    _section_with_user_agent,
    default_config,
    default_storage_config,
    dump_yaml_config,
    extract_localhost_config,
    extract_serverless_config,
    extract_standalone_config,
    extract_storage_config,
    get_default_config_filename,
    get_log_info,
    load_config,
    load_yaml_config,
)
from lithops.version import __version__

_real_import_module = importlib.import_module


def _isolate_config_files(monkeypatch, tmp_path):
    monkeypatch.delenv('LITHOPS_CONFIG', raising=False)
    monkeypatch.delenv('LITHOPS_CONFIG_FILE', raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(c, 'CONFIG_FILE', str(tmp_path / 'missing-user-config'))
    monkeypatch.setattr(c, 'CONFIG_FILE_GLOBAL', str(tmp_path / 'missing-global-config'))


def _localhost_input(**lithops_extra):
    lithops_cfg = {'mode': c.LOCALHOST, 'backend': c.LOCALHOST, 'storage': c.LOCALHOST}
    lithops_cfg.update(lithops_extra)
    return {'lithops': lithops_cfg}


class TestYamlConfig:

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_yaml_config(str(tmp_path / 'does-not-exist.yml')) == {}

    def test_dump_and_load_roundtrip(self, tmp_path):
        path = tmp_path / 'nested' / 'cfg.yml'
        payload = {'lithops': {'mode': 'localhost'}, 'flag': True}
        dump_yaml_config(str(path), payload)
        loaded = load_yaml_config(str(path))
        assert loaded == payload

    def test_load_empty_file_returns_none(self, tmp_path):
        path = tmp_path / 'empty.yml'
        path.write_text('')
        assert load_yaml_config(str(path)) is None

    def test_dump_filename_without_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        dump_yaml_config('plain.yml', {'a': 1})
        assert load_yaml_config('plain.yml') == {'a': 1}


class TestConfigFileDiscovery:

    def test_env_lithops_config_file_wins(self, monkeypatch, tmp_path):
        cfg = tmp_path / 'from-env.yml'
        cfg.write_text('lithops: {}\n')
        monkeypatch.setenv('LITHOPS_CONFIG_FILE', str(cfg))
        assert get_default_config_filename() == str(cfg)

    def test_env_lithops_config_file_returned_even_if_missing(self, monkeypatch, tmp_path):
        missing = str(tmp_path / 'does-not-exist.yml')
        monkeypatch.setenv('LITHOPS_CONFIG_FILE', missing)
        assert get_default_config_filename() == missing

    def test_dotfile_in_cwd(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        (tmp_path / '.lithops_config').write_text('lithops: {}\n')
        assert get_default_config_filename() == str((tmp_path / '.lithops_config').resolve())

    def test_user_config_file(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        user_cfg = tmp_path / 'user-config'
        user_cfg.write_text('lithops: {}\n')
        monkeypatch.setattr(c, 'CONFIG_FILE', str(user_cfg))
        assert get_default_config_filename() == str(user_cfg)

    def test_global_config_file(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        global_cfg = tmp_path / 'global-config'
        global_cfg.write_text('lithops: {}\n')
        monkeypatch.setattr(c, 'CONFIG_FILE_GLOBAL', str(global_cfg))
        assert get_default_config_filename() == str(global_cfg)

    def test_none_when_no_file_exists(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        assert get_default_config_filename() is None


class TestLoadConfig:

    def test_explicit_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="doesn't exist"):
            load_config(str(tmp_path / 'missing.yml'))

    def test_explicit_file(self, tmp_path):
        cfg = tmp_path / 'cfg.yml'
        cfg.write_text(yaml.dump({'lithops': {'mode': 'localhost'}}))
        loaded = load_config(str(cfg), log=False)
        assert loaded['lithops']['mode'] == 'localhost'

    def test_json_from_env(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        monkeypatch.setenv('LITHOPS_CONFIG', json.dumps({'lithops': {'backend': 'localhost'}}))
        loaded = load_config(log=False)
        assert loaded['lithops']['backend'] == 'localhost'

    def test_fallback_to_localhost(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        loaded = load_config(log=False)
        assert loaded == {
            'lithops': {
                'mode': c.LOCALHOST,
                'backend': c.LOCALHOST,
                'storage': c.LOCALHOST,
            }
        }

    def test_fallback_does_not_share_mutable_state(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        first = load_config(log=False)
        first['lithops']['mode'] = 'serverless'
        second = load_config(log=False)
        assert second['lithops']['mode'] == c.LOCALHOST

    def test_json_env_wins_over_config_file(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        (tmp_path / '.lithops_config').write_text(yaml.dump({'lithops': {'backend': 'fromfile'}}))
        monkeypatch.setenv('LITHOPS_CONFIG', json.dumps({'lithops': {'backend': 'fromenv'}}))
        loaded = load_config(log=False)
        assert loaded['lithops']['backend'] == 'fromenv'

    def test_missing_env_config_file_falls_back_to_localhost(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        monkeypatch.setenv('LITHOPS_CONFIG_FILE', str(tmp_path / 'nope.yml'))
        loaded = load_config(log=False)
        assert loaded['lithops'] == {
            'mode': c.LOCALHOST, 'backend': c.LOCALHOST, 'storage': c.LOCALHOST
        }

    def test_explicit_empty_yaml_falls_back_to_localhost(self, tmp_path):
        path = tmp_path / 'empty.yml'
        path.write_text('')
        loaded = load_config(str(path), log=False)
        assert loaded['lithops']['backend'] == c.LOCALHOST

    def test_yaml_empty_mapping_falls_back_to_localhost(self, tmp_path):
        path = tmp_path / 'empty-map.yml'
        path.write_text('{}\n')
        loaded = load_config(str(path), log=False)
        assert loaded['lithops']['mode'] == c.LOCALHOST

    def test_file_with_empty_lithops_section_is_kept(self, tmp_path):
        path = tmp_path / 'cfg.yml'
        path.write_text('lithops: {}\n')
        loaded = load_config(str(path), log=False)
        assert loaded == {'lithops': {}}

    def test_json_env_empty_object_falls_back_to_localhost(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        monkeypatch.setenv('LITHOPS_CONFIG', '{}')
        loaded = load_config(log=False)
        assert loaded['lithops']['mode'] == c.LOCALHOST

    def test_explicit_file_expands_user_home(self, monkeypatch, tmp_path):
        cfg = tmp_path / 'home.yml'
        cfg.write_text(yaml.dump({'lithops': {'mode': 'localhost'}}))
        monkeypatch.setenv('HOME', str(tmp_path))
        loaded = load_config('~/home.yml', log=False)
        assert loaded['lithops']['mode'] == 'localhost'


class TestGetLogInfo:

    def test_defaults(self):
        level, fmt, stream, filename = get_log_info(config_data={'lithops': {}})
        assert level == c.LOGGER_LEVEL
        assert fmt == c.LOGGER_FORMAT
        assert stream == c.LOGGER_STREAM
        assert filename is None

    def test_values_from_config(self):
        level, fmt, stream, filename = get_log_info(config_data={
            'lithops': {
                'log_level': 'DEBUG',
                'log_format': '%(message)s',
                'log_stream': 'ext://sys.stdout',
                'log_filename': '/tmp/lithops.log',
            }
        })
        assert level == 'DEBUG'
        assert fmt == '%(message)s'
        assert stream == 'ext://sys.stdout'
        assert filename == '/tmp/lithops.log'

    def test_does_not_mutate_input(self):
        src = {'lithops': {}}
        get_log_info(config_data=src)
        assert 'log_level' not in src['lithops']

    def test_explicit_none_log_level_is_preserved(self):
        level, *_ = get_log_info(config_data={'lithops': {'log_level': None}})
        assert level is None

    def test_missing_lithops_section_gets_defaults(self):
        level, fmt, stream, filename = get_log_info(config_data={'other': 1})
        assert level == c.LOGGER_LEVEL
        assert fmt == c.LOGGER_FORMAT
        assert stream == c.LOGGER_STREAM
        assert filename is None


class TestResolveModeAndBackend:

    def test_mode_without_backend_uses_mode_section(self):
        cfg = {
            'lithops': {'mode': c.SERVERLESS},
            c.SERVERLESS: {'backend': 'code_engine'},
        }
        backend, mode = _resolve_mode_and_backend(cfg)
        assert mode == c.SERVERLESS
        assert backend == 'code_engine'

    def test_mode_without_backend_uses_default_backend(self):
        cfg = {'lithops': {'mode': c.LOCALHOST}}
        backend, mode = _resolve_mode_and_backend(cfg)
        assert backend == c.LOCALHOST
        assert mode == c.LOCALHOST

    def test_backend_sets_mode(self):
        cfg = {'lithops': {'backend': 'aws_lambda'}}
        backend, mode = _resolve_mode_and_backend(cfg)
        assert backend == 'aws_lambda'
        assert mode == c.SERVERLESS

    def test_neither_uses_mode_default(self):
        cfg = {'lithops': {}}
        backend, mode = _resolve_mode_and_backend(cfg)
        assert mode == c.MODE_DEFAULT
        assert backend == c.SERVERLESS_BACKEND_DEFAULT

    def test_backend_wins_when_both_are_set(self):
        cfg = {'lithops': {'mode': c.SERVERLESS, 'backend': c.LOCALHOST}}
        backend, mode = _resolve_mode_and_backend(cfg)
        assert backend == c.LOCALHOST
        assert mode == c.LOCALHOST

    def test_standalone_backend_sets_standalone_mode(self):
        cfg = {'lithops': {'backend': 'aws_ec2'}}
        backend, mode = _resolve_mode_and_backend(cfg)
        assert backend == 'aws_ec2'
        assert mode == c.STANDALONE

    def test_mode_section_backend_none_is_still_applied(self):
        cfg = {
            'lithops': {'mode': c.SERVERLESS},
            c.SERVERLESS: {'backend': None},
        }
        backend, mode = _resolve_mode_and_backend(cfg)
        assert backend is None
        assert mode == c.SERVERLESS

    def test_empty_string_backend_is_treated_as_missing(self):
        cfg = {'lithops': {'mode': c.LOCALHOST, 'backend': ''}}
        backend, mode = _resolve_mode_and_backend(cfg)
        assert backend == c.LOCALHOST
        assert mode == c.LOCALHOST


class TestDefaultConfig:

    def test_localhost_completes_defaults(self):
        cfg = default_config(config_data=_localhost_input())
        assert cfg['lithops']['mode'] == c.LOCALHOST
        assert cfg['lithops']['backend'] == c.LOCALHOST
        assert cfg['lithops']['storage'] == c.LOCALHOST
        assert cfg['lithops']['chunksize'] == cfg['localhost']['worker_processes']
        assert cfg['lithops']['monitoring'] == 'storage'
        assert cfg['lithops']['monitoring_interval'] == 0.1
        assert cfg['lithops']['execution_timeout'] == 3600
        assert 'localhost' in cfg

    def test_overwrite_lithops_and_backend_keys(self):
        cfg = default_config(
            config_data=_localhost_input(),
            config_overwrite={
                'lithops': {'monitoring_interval': 9},
                'backend': {'runtime': 'python3'},
            },
        )
        assert cfg['lithops']['monitoring_interval'] == 9
        assert cfg['localhost']['runtime'] == 'python3'

    def test_does_not_mutate_input(self):
        src = _localhost_input()
        default_config(config_data=src)
        assert 'chunksize' not in src['lithops']
        assert 'localhost' not in src

    def test_empty_lithops_section_is_replaced(self):
        cfg = {'lithops': None}
        _ensure_lithops_section(cfg)
        assert cfg['lithops'] == {}

    def test_localhost_storage_rejected_for_other_backends(self):
        fake_module = MagicMock()
        fake_module.load_config.side_effect = lambda cfg: cfg.setdefault(
            'aws_lambda', {'worker_processes': 1}
        )

        def importer(name):
            if name.endswith('aws_lambda.config'):
                return fake_module
            return _real_import_module(name)

        with patch('lithops.config.importlib.import_module', side_effect=importer):
            with pytest.raises(Exception, match='Localhost storage backend cannot be used'):
                default_config(config_data={
                    'lithops': {'backend': 'aws_lambda', 'storage': c.LOCALHOST},
                    'aws_lambda': {'worker_processes': 1},
                })

    def test_standalone_sets_chunksize_zero(self):
        fake_module = MagicMock()

        def load_config(cfg):
            cfg.setdefault('standalone', {})
            cfg.setdefault('aws_ec2', {'worker_processes': 4})

        fake_module.load_config.side_effect = load_config

        def importer(name):
            if 'standalone.backends' in name:
                return fake_module
            return _real_import_module(name)

        with patch('lithops.config.importlib.import_module', side_effect=importer):
            cfg = default_config(
                config_data={
                    'lithops': {'backend': 'aws_ec2', 'storage': c.LOCALHOST},
                    'aws_ec2': {},
                },
                load_storage_config=False,
            )

        assert cfg['lithops']['mode'] == c.STANDALONE
        assert cfg['lithops']['chunksize'] == 0
        fake_module.load_config.assert_called_once()

    def test_standalone_overwrites_user_chunksize(self):
        fake_module = MagicMock()
        fake_module.load_config.side_effect = lambda cfg: cfg.setdefault('standalone', {})

        def importer(name):
            if 'standalone.backends' in name:
                return fake_module
            return _real_import_module(name)

        with patch('lithops.config.importlib.import_module', side_effect=importer):
            cfg = default_config(
                config_data={
                    'lithops': {'backend': 'aws_ec2', 'chunksize': 8},
                    'aws_ec2': {'worker_processes': 4},
                },
                load_storage_config=False,
            )
        assert cfg['lithops']['chunksize'] == 0

    def test_user_chunksize_preserved_on_localhost(self):
        cfg = default_config(config_data=_localhost_input(chunksize=8))
        assert cfg['lithops']['chunksize'] == 8

    def test_backend_overwrite_worker_processes_sets_chunksize(self):
        cfg = default_config(
            config_data=_localhost_input(),
            config_overwrite={'backend': {'worker_processes': 3}},
        )
        assert cfg['localhost']['worker_processes'] == 3
        assert cfg['lithops']['chunksize'] == 3

    def test_empty_dict_config_data_loads_from_discovery(self, monkeypatch, tmp_path):
        _isolate_config_files(monkeypatch, tmp_path)
        cfg = default_config(config_data={})
        assert cfg['lithops']['mode'] == c.LOCALHOST
        assert cfg['lithops']['backend'] == c.LOCALHOST

    def test_backend_overrides_conflicting_mode(self):
        cfg = default_config(config_data={
            'lithops': {
                'mode': c.SERVERLESS,
                'backend': c.LOCALHOST,
                'storage': c.LOCALHOST,
            }
        })
        assert cfg['lithops']['mode'] == c.LOCALHOST
        assert cfg['lithops']['backend'] == c.LOCALHOST

    def test_overwrite_backend_rewrites_mode(self):
        cfg = default_config(
            config_data={'lithops': {'mode': c.SERVERLESS, 'storage': c.LOCALHOST}},
            config_overwrite={'lithops': {'backend': c.LOCALHOST}},
        )
        assert cfg['lithops']['mode'] == c.LOCALHOST
        assert cfg['lithops']['backend'] == c.LOCALHOST

    def test_none_backend_section_is_replaced(self):
        src = _localhost_input()
        src['localhost'] = None
        cfg = default_config(config_data=src)
        assert isinstance(cfg['localhost'], dict)
        assert cfg['localhost']['max_workers'] == 1

    def test_empty_backend_overwrite_is_ignored(self):
        cfg = default_config(
            config_data=_localhost_input(),
            config_overwrite={'backend': {}},
        )
        assert cfg['lithops']['backend'] == c.LOCALHOST

    def test_skip_storage_config_skips_localhost_storage_defaults(self):
        cfg = default_config(
            config_data=_localhost_input(),
            load_storage_config=False,
        )
        assert cfg['lithops']['monitoring_interval'] == 2
        assert 'storage_bucket' not in cfg.get('localhost', {})

    def test_unknown_backend_raises(self):
        with pytest.raises(Exception, match='Unknown compute backend'):
            default_config(config_data={
                'lithops': {'backend': 'not_a_backend', 'storage': c.LOCALHOST}
            })

    def test_unknown_mode_raises(self):
        with pytest.raises(Exception, match='Unknown execution mode'):
            default_config(config_data={
                'lithops': {'mode': 'spaceship', 'storage': c.LOCALHOST}
            })

    def test_unknown_monitoring_backend_raises(self):
        with pytest.raises(Exception, match='Unknown monitoring backend'):
            default_config(config_data=_localhost_input(monitoring='nope'))

    def test_a_null_monitoring_key_falls_back_to_storage(self):
        """
        An explicit null used to reach .lower() and raise AttributeError
        rather than falling back the way a missing key does
        """
        config_data = _localhost_input()
        config_data['lithops']['monitoring'] = None
        cfg = default_config(config_data=config_data)
        assert cfg['lithops']['monitoring'] == 'storage'

    def test_the_monitoring_backend_name_is_normalised(self):
        config_data = _localhost_input(monitoring='RabbitMQ')
        config_data['rabbitmq'] = {'amqp_url': 'amqp://guest@localhost'}
        cfg = default_config(config_data=config_data)
        assert cfg['lithops']['monitoring'] == 'rabbitmq'

    def test_rabbitmq_monitoring_requires_amqp_url(self):
        with pytest.raises(Exception, match='rabbitmq'):
            default_config(config_data=_localhost_input(monitoring='rabbitmq'))

    def test_rabbitmq_monitoring_loads_with_amqp_url(self):
        config_data = _localhost_input(monitoring='rabbitmq')
        config_data['rabbitmq'] = {'amqp_url': 'amqp://guest@localhost'}
        cfg = default_config(config_data=config_data)
        assert cfg['lithops']['monitoring'] == 'rabbitmq'
        assert cfg['rabbitmq']['amqp_url'] == 'amqp://guest@localhost'

    def test_redis_monitoring_requires_host(self):
        with pytest.raises(Exception, match='redis'):
            default_config(config_data=_localhost_input(monitoring='redis'))

    def test_redis_monitoring_loads_with_host(self):
        config_data = _localhost_input(monitoring='redis')
        config_data['redis'] = {'host': 'localhost'}
        cfg = default_config(config_data=config_data)
        assert cfg['lithops']['monitoring'] == 'redis'
        assert cfg['redis']['host'] == 'localhost'

    def test_aws_sqs_monitoring_merges_aws_section(self):
        config_data = _localhost_input(monitoring='aws_sqs')
        config_data['aws'] = {'region': 'eu-west-1', 'access_key_id': 'AK'}
        cfg = default_config(config_data=config_data)
        assert cfg['lithops']['monitoring'] == 'aws_sqs'
        assert cfg['aws_sqs']['region'] == 'eu-west-1'
        assert cfg['aws_sqs']['access_key_id'] == 'AK'

    def test_aws_sqs_monitoring_requires_region(self):
        with pytest.raises(Exception, match='region'):
            default_config(config_data=_localhost_input(monitoring='aws_sqs'))

    def test_gcp_pubsub_monitoring_merges_gcp_section(self, monkeypatch):
        monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)
        config_data = _localhost_input(monitoring='gcp_pubsub')
        config_data['gcp'] = {
            'project_name': 'my-proj',
            'credentials_path': '/tmp/creds.json',
        }
        cfg = default_config(config_data=config_data)
        assert cfg['lithops']['monitoring'] == 'gcp_pubsub'
        assert cfg['gcp_pubsub']['project_name'] == 'my-proj'
        assert cfg['gcp_pubsub']['credentials_path'] == '/tmp/creds.json'

    def test_gcp_pubsub_monitoring_requires_project_name(self, monkeypatch):
        monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)
        with pytest.raises(Exception, match='project_name'):
            default_config(config_data=_localhost_input(monitoring='gcp_pubsub'))

    def test_azure_queue_monitoring_merges_azure_storage(self):
        config_data = _localhost_input(monitoring='azure_queue')
        config_data['azure_storage'] = {
            'storage_account_name': 'acct',
            'storage_account_key': 'key',
        }
        cfg = default_config(config_data=config_data)
        assert cfg['lithops']['monitoring'] == 'azure_queue'
        assert cfg['azure_queue']['storage_account_name'] == 'acct'
        assert cfg['azure_queue']['storage_account_key'] == 'key'

    def test_azure_queue_monitoring_requires_account(self):
        with pytest.raises(Exception, match='storage_account_name'):
            default_config(config_data=_localhost_input(monitoring='azure_queue'))


class TestStorageAndExtract:

    def test_default_storage_config_localhost(self):
        cfg = default_storage_config(config_data=_localhost_input())
        assert cfg['lithops']['storage'] == c.LOCALHOST
        assert cfg['localhost']['storage_bucket'] == 'storage'

    def test_default_storage_config_backend_override(self):
        cfg = default_storage_config(
            config_data={'lithops': {'storage': 'aws_s3'}},
            backend=c.LOCALHOST,
        )
        assert cfg['lithops']['storage'] == c.LOCALHOST

    def test_extract_storage_config_sets_user_agent(self):
        cfg = {
            'lithops': {'storage': c.LOCALHOST, 'monitoring_interval': 0.5},
            c.LOCALHOST: {'storage_bucket': 'storage'},
        }
        extracted = extract_storage_config(cfg)
        assert extracted['backend'] == c.LOCALHOST
        assert extracted['monitoring_interval'] == 0.5
        assert extracted[c.LOCALHOST]['user_agent'] == f'lithops/{__version__}'
        assert cfg[c.LOCALHOST]['user_agent'] == extracted[c.LOCALHOST]['user_agent']

    def test_extract_storage_config_missing_backend_section(self):
        cfg = {'lithops': {'storage': c.LOCALHOST}}
        extracted = extract_storage_config(cfg)
        assert extracted[c.LOCALHOST]['user_agent'] == f'lithops/{__version__}'
        assert c.LOCALHOST not in cfg

    def test_extract_localhost_config_is_a_copy(self):
        cfg = {c.LOCALHOST: {'runtime': 'python3', 'version': 2}}
        extracted = extract_localhost_config(cfg)
        extracted['runtime'] = 'other'
        assert cfg[c.LOCALHOST]['runtime'] == 'python3'

    def test_extract_serverless_config(self):
        cfg = {
            'lithops': {'backend': 'aws_lambda'},
            'aws_lambda': {'region': 'us-east-1'},
        }
        extracted = extract_serverless_config(cfg)
        assert extracted['backend'] == 'aws_lambda'
        assert extracted['aws_lambda']['region'] == 'us-east-1'
        assert extracted['aws_lambda']['user_agent'] == f'lithops/{__version__}'

    def test_extract_standalone_config(self):
        cfg = {
            'lithops': {'backend': 'aws_ec2', 'storage': c.LOCALHOST},
            c.STANDALONE: {'exec_mode': 'reuse'},
            'aws_ec2': {'region': 'us-east-1'},
        }
        extracted = extract_standalone_config(cfg)
        assert extracted['backend'] == 'aws_ec2'
        assert extracted['storage'] == c.LOCALHOST
        assert extracted['exec_mode'] == 'reuse'
        assert extracted['aws_ec2']['user_agent'] == f'lithops/{__version__}'

    def test_section_with_user_agent_uses_empty_dict_when_missing(self):
        section = _section_with_user_agent({'lithops': {}}, 'aws_lambda')
        assert section == {'user_agent': f'lithops/{__version__}'}

    def test_extract_does_not_mutate_empty_backend_section(self):
        cfg = {'lithops': {'storage': c.LOCALHOST}, c.LOCALHOST: {}}
        extract_storage_config(cfg)
        assert 'user_agent' not in cfg[c.LOCALHOST]

    def test_extract_storage_config_default_monitoring_interval(self):
        cfg = {
            'lithops': {'storage': c.LOCALHOST},
            c.LOCALHOST: {'storage_bucket': 'storage'},
        }
        extracted = extract_storage_config(cfg)
        assert extracted['monitoring_interval'] == c.LITHOPS_DEFAULT_CONFIG_KEYS['monitoring_interval']

    def test_extract_standalone_does_not_share_standalone_section(self):
        cfg = {
            'lithops': {'backend': 'aws_ec2', 'storage': c.LOCALHOST},
            c.STANDALONE: {'exec_mode': 'reuse'},
            'aws_ec2': {'region': 'us-east-1'},
        }
        extracted = extract_standalone_config(cfg)
        extracted['exec_mode'] = 'consume'
        assert cfg[c.STANDALONE]['exec_mode'] == 'reuse'
