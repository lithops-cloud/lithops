#
# (C) Copyright Cloudlab URV 2020
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
import tempfile

LOGGER_LEVEL = 'info'
LOGGER_FORMAT = ("%(asctime)s [%(levelname)s] %(name)s -- %(message)s")
LOGGER_FORMAT_SHORT = ("[%(levelname)s] %(filename)s -- %(message)s")
LOGGER_LEVEL_CHOICES = ["debug", "info", "warning", "error", "critical"]

LOCALHOST = 'localhost'
SERVERLESS = 'serverless'
STANDALONE = 'standalone'

MODE_DEFAULT = SERVERLESS
SERVERLESS_BACKEND_DEFAULT = 'ibm_cf'
STANDALONE_BACKEND_DEFAULT = 'ibm_vpc'
STORAGE_BACKEND_DEFAULT = 'ibm_cos'

JOBS_PREFIX = "lithops.jobs"
TEMP_PREFIX = "lithops.jobs/tmp"
LOGS_PREFIX = "lithops.logs"
RUNTIMES_PREFIX = "lithops.runtimes"

EXECUTION_TIMEOUT_DEFAULT = 1800

STANDALONE_RUNTIME_DEFAULT = 'python3'
STANDALONE_AUTO_DISMANTLE_DEFAULT = True
STANDALONE_SOFT_DISMANTLE_TIMEOUT_DEFAULT = 300
STANDALONE_HARD_DISMANTLE_TIMEOUT_DEFAULT = 3600

MAX_AGG_DATA_SIZE = 4  # 4MiB

TEMP = os.path.realpath(tempfile.gettempdir())
LITHOPS_TEMP_DIR = os.path.join(TEMP, 'lithops')
JOBS_DONE_DIR = os.path.join(LITHOPS_TEMP_DIR, 'jobs')
LOGS_DIR = os.path.join(LITHOPS_TEMP_DIR, 'logs')

RN_LOG_FILE = os.path.join(LITHOPS_TEMP_DIR, 'runner.log')
PX_LOG_FILE = os.path.join(LITHOPS_TEMP_DIR, 'proxy.log')
FN_LOG_FILE = os.path.join(LITHOPS_TEMP_DIR, 'functions.log')

CLEANER_DIR = os.path.join(LITHOPS_TEMP_DIR, 'cleaner')
CLEANER_PID_FILE = os.path.join(CLEANER_DIR, 'cleaner.pid')
CLEANER_LOG_FILE = os.path.join(CLEANER_DIR, 'cleaner.log')

REMOTE_INSTALL_DIR = '/opt/lithops'

HOME_DIR = os.path.expanduser('~')
CONFIG_DIR = os.path.join(HOME_DIR, '.lithops')
CACHE_DIR = os.path.join(CONFIG_DIR, 'cache')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config')
