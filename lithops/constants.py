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
LOGGER_STREAM = 'ext://sys.stderr'
LOGGER_FORMAT = "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)s -- %(message)s"
LOGGER_FORMAT_SHORT = "[%(levelname)s] %(filename)s:%(lineno)s -- %(message)s"
LOGGER_LEVEL_CHOICES = ["debug", "info", "warning", "error", "critical"]

CPU_COUNT = os.cpu_count()

STORAGE_CLI_MSG = '{} client created'
COMPUTE_CLI_MSG = '{} client created'

LOCALHOST = 'localhost'
SERVERLESS = 'serverless'
STANDALONE = 'standalone'

MODE_DEFAULT = SERVERLESS

SERVERLESS_BACKEND_DEFAULT = 'aws_lambda'
STANDALONE_BACKEND_DEFAULT = 'aws_ec2'
STORAGE_BACKEND_DEFAULT = 'aws_s3'

JOBS_PREFIX = "lithops.jobs"
TEMP_PREFIX = "lithops.jobs/tmp"
LOGS_PREFIX = "lithops.logs"
RUNTIMES_PREFIX = "lithops.runtimes"

MAX_AGG_DATA_SIZE = 4  # 4MiB

WORKER_PROCESSES_DEFAULT = 1

TEMP_DIR = os.path.realpath(tempfile.gettempdir())
USER_TEMP_DIR = 'lithops-' + os.getenv("USER", "root")
LITHOPS_TEMP_DIR = os.path.join(TEMP_DIR, USER_TEMP_DIR)
JOBS_DIR = os.path.join(LITHOPS_TEMP_DIR, 'jobs')
LOGS_DIR = os.path.join(LITHOPS_TEMP_DIR, 'logs')
MODULES_DIR = os.path.join(LITHOPS_TEMP_DIR, 'modules')
CUSTOM_RUNTIME_DIR = os.path.join(LITHOPS_TEMP_DIR, 'custom-runtime')

RN_LOG_FILE = os.path.join(LITHOPS_TEMP_DIR, 'localhost-runner.log')
SV_LOG_FILE = os.path.join(LITHOPS_TEMP_DIR, 'localhost-service.log')
FN_LOG_FILE = os.path.join(LITHOPS_TEMP_DIR, 'functions.log')

CLEANER_DIR = os.path.join(LITHOPS_TEMP_DIR, 'cleaner')
CLEANER_PID_FILE = os.path.join(CLEANER_DIR, 'cleaner.pid')
CLEANER_LOG_FILE = os.path.join(CLEANER_DIR, 'cleaner.log')

HOME_DIR = os.path.expanduser('~')
CONFIG_DIR = os.path.join(HOME_DIR, '.lithops')
CACHE_DIR = os.path.join(CONFIG_DIR, 'cache')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config')
CONFIG_FILE_GLOBAL = os.path.join("/etc", "lithops", "config")

LITHOPS_DEFAULT_CONFIG_KEYS = {
    'monitoring': 'storage',
    'monitoring_interval': 2,
    'execution_timeout': 1800
}

SA_INSTALL_DIR = '/opt/lithops'
SA_SETUP_LOG_FILE = f'{SA_INSTALL_DIR}/setup.log'
SA_SETUP_DONE_FILE = f'{SA_INSTALL_DIR}/setup-done.flag'
SA_MASTER_LOG_FILE = f'{LITHOPS_TEMP_DIR}/master-service.log'
SA_WORKER_LOG_FILE = f'{LITHOPS_TEMP_DIR}/worker-service.log'
SA_MASTER_SERVICE_PORT = 8080
SA_WORKER_SERVICE_PORT = 8081
SA_CONFIG_FILE = os.path.join(SA_INSTALL_DIR, 'config')
SA_MASTER_DATA_FILE = os.path.join(SA_INSTALL_DIR, 'master.data')
SA_WORKER_DATA_FILE = os.path.join(SA_INSTALL_DIR, 'worker.data')

SA_DEFAULT_CONFIG_KEYS = {
    'runtime': 'python3',
    'exec_mode': 'reuse',
    'use_gpu': False,
    'start_timeout': 300,
    'auto_dismantle': True,
    'soft_dismantle_timeout': 300,
    'hard_dismantle_timeout': 3600
}

SERVERLESS_BACKENDS = [
    'ibm_cf',
    'code_engine',
    'knative',
    'openwhisk',
    'aws_lambda',
    'aws_batch',
    'gcp_cloudrun',
    'gcp_functions',
    'cloudrun',
    'azure_functions',
    'azure_containers',
    'aliyun_fc',
    'oracle_f',
    'k8s',
    'singularity'
]

STANDALONE_BACKENDS = [
    'ibm_vpc',
    'aws_ec2',
    'azure_vms',
    'vm'
]
