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

from lithops import constants
from lithops.utils import get_default_backend, get_mode


class TestConstants:

    def test_execution_modes(self):
        assert constants.LOCALHOST == 'localhost'
        assert constants.SERVERLESS == 'serverless'
        assert constants.STANDALONE == 'standalone'
        assert constants.MODE_DEFAULT == constants.SERVERLESS

    def test_default_backends_are_known(self):
        assert constants.SERVERLESS_BACKEND_DEFAULT in constants.SERVERLESS_BACKENDS
        assert constants.STANDALONE_BACKEND_DEFAULT in constants.STANDALONE_BACKENDS
        assert constants.LOCALHOST not in constants.SERVERLESS_BACKENDS
        assert constants.LOCALHOST not in constants.STANDALONE_BACKENDS

    def test_backend_collections_are_immutable(self):
        assert isinstance(constants.SERVERLESS_BACKENDS, tuple)
        assert isinstance(constants.STANDALONE_BACKENDS, tuple)
        assert isinstance(constants.LOGGER_LEVEL_CHOICES, tuple)

    def test_temp_paths_are_under_lithops_temp_dir(self):
        for path in (
            constants.JOBS_DIR,
            constants.LOGS_DIR,
            constants.MODULES_DIR,
            constants.CUSTOM_RUNTIME_DIR,
            constants.CLEANER_DIR,
            constants.RN_LOG_FILE,
            constants.SV_LOG_FILE,
            constants.FN_LOG_FILE,
            constants.SA_MASTER_LOG_FILE,
            constants.SA_WORKER_LOG_FILE,
        ):
            assert path.startswith(constants.LITHOPS_TEMP_DIR)
            assert os.path.isabs(path)

    def test_cleaner_files_are_under_cleaner_dir(self):
        assert constants.CLEANER_PID_FILE.startswith(constants.CLEANER_DIR)
        assert constants.CLEANER_LOG_FILE.startswith(constants.CLEANER_DIR)

    def test_config_paths(self):
        assert constants.CONFIG_FILE.endswith(os.path.join('.lithops', 'config'))
        assert constants.CACHE_DIR.endswith(os.path.join('.lithops', 'cache'))
        assert constants.CONFIG_FILE_GLOBAL == '/etc/lithops/config'

    def test_local_temp_paths_use_native_separators(self):
        assert constants.LITHOPS_TEMP_DIR == os.path.join(
            constants.TEMP_DIR, constants.USER_TEMP_DIR
        )
        assert constants.JOBS_DIR == os.path.join(constants.LITHOPS_TEMP_DIR, 'jobs')
        assert constants.LOGS_DIR == os.path.join(constants.LITHOPS_TEMP_DIR, 'logs')

    def test_standalone_remote_paths_are_posix(self):
        remote = (
            constants.SA_INSTALL_DIR,
            constants.SA_SETUP_LOG_FILE,
            constants.SA_SETUP_DONE_FILE,
            constants.SA_CONFIG_FILE,
            constants.SA_MASTER_DATA_FILE,
            constants.SA_WORKER_DATA_FILE,
            constants.CONFIG_FILE_GLOBAL,
        )
        for path in remote:
            assert path.startswith('/')
            assert '\\' not in path
        assert constants.SA_INSTALL_DIR == '/opt/lithops'
        assert constants.SA_SETUP_LOG_FILE == '/opt/lithops/setup.log'
        assert constants.SA_SETUP_DONE_FILE == '/opt/lithops/setup-done.flag'
        assert constants.SA_CONFIG_FILE == '/opt/lithops/config'
        assert constants.SA_MASTER_DATA_FILE == '/opt/lithops/master.data'
        assert constants.SA_WORKER_DATA_FILE == '/opt/lithops/worker.data'

    def test_storage_prefixes_are_posix(self):
        assert constants.JOBS_PREFIX == 'lithops.jobs'
        assert constants.TEMP_PREFIX == 'lithops.jobs/tmp'
        assert constants.LOGS_PREFIX == 'lithops.logs'
        assert constants.RUNTIMES_PREFIX == 'lithops.runtimes'
        assert '\\' not in constants.TEMP_PREFIX

    def test_default_config_keys(self):
        assert set(constants.LITHOPS_DEFAULT_CONFIG_KEYS) == {
            'monitoring', 'monitoring_interval', 'execution_timeout'
        }
        assert constants.LITHOPS_DEFAULT_CONFIG_KEYS['monitoring_interval'] == 2

    def test_get_mode_and_default_backend_round_trip(self):
        assert get_mode(constants.LOCALHOST) == constants.LOCALHOST
        assert get_mode(constants.SERVERLESS_BACKEND_DEFAULT) == constants.SERVERLESS
        assert get_mode(constants.STANDALONE_BACKEND_DEFAULT) == constants.STANDALONE
        assert get_default_backend(constants.LOCALHOST) == constants.LOCALHOST
        assert get_default_backend(constants.SERVERLESS) == constants.SERVERLESS_BACKEND_DEFAULT
        assert get_default_backend(constants.STANDALONE) == constants.STANDALONE_BACKEND_DEFAULT

    def test_every_known_backend_has_a_mode(self):
        for backend in constants.SERVERLESS_BACKENDS:
            assert get_mode(backend) == constants.SERVERLESS
        for backend in constants.STANDALONE_BACKENDS:
            assert get_mode(backend) == constants.STANDALONE
