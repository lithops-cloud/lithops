#
# Copyright Cloudlab URV 2020
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

import sys
import os
import shutil
from lithops.utils import version_str
from lithops import __version__
from lithops.constants import TEMP

BUILD_DIR = os.path.join(TEMP, 'AzureRuntimeBuild')
ACTION_DIR = 'lithops_handler'
ACTION_MODULES_DIR = os.path.join('.python_packages', 'lib', 'site-packages')

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_azure.zip')
DOCKER_PATH = shutil.which('docker')

RUNTIME_NAME = 'lithops-runtime'
FUNCTIONS_VERSION = 3
RUNTIME_TIMEOUT = 300000    # Default: 300000 ms => 10 minutes
RUNTIME_TIMEOUT_MAX = 600000        # Platform maximum
RUNTIME_MEMORY = 1500       # Default memory: 1.5 GB
MAX_CONCURRENT_WORKERS = 2000

IN_QUEUE = "in-trigger"
OUT_QUEUE = "out-result"

BINDINGS = {
    "scriptFile": "__init__.py",
    "bindings": [
        {
            "name": "msgIn",
            "type": "queueTrigger",
            "direction": "in",
            "queueName": "",
            "connection": "AzureWebJobsStorage"
        },
        {
            "name": "msgOut",
            "type": "queue",
            "direction": "out",
            "queueName": "",
            "connection": "AzureWebJobsStorage"
        }]}

HOST_FILE = """
{
  "version": "2.0",
  "logging": {
    "applicationInsights": {
      "samplingSettings": {
        "isEnabled": true,
        "excludedTypes": "Request"
      }
    }
  },
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[1.*, 2.0.0)"
  }
}
"""

REQUIREMENTS_FILE = """
azure-functions
azure-storage-blob
azure-storage-queue
pika==0.13.1
flask
gevent
glob2
redis
requests
PyYAML
kubernetes
numpy
cloudpickle
ps-mem
tblib
"""

DEFAULT_DOCKERFILE = """
ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true

RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        azure-functions \
        azure-storage-blob \
        azure-storage-queue \
        pika==0.13.1 \
        flask \
        gevent \
        glob2 \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy

COPY lithops_azure.zip .
RUN mkdir -p /home/site/wwwroo \
    && unzip lithops_azure.zip -d /home/site/wwwroo \
    && rm lithops_azure.zip
"""

SUPPORTED_PYTHON = ['3.6', '3.7', '3.8']


def load_config(config_data=None):

    python_version = version_str(sys.version_info)
    if python_version not in SUPPORTED_PYTHON:
        raise Exception('Python {} is not supported'.format(python_version))

    if 'runtime_memory' in config_data['serverless']:
        print("Ignoring user specified '{}'. The current Azure compute backend"
              " does not support custom runtimes.".format('runtime_memory'))
        print('Default runtime memory: {}MB'.format(RUNTIME_MEMORY))
    config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY

    if 'runtime_timeout' in config_data['serverless']:
        print("Ignoring user specified '{}'. The current Azure compute backend"
              " does not support custom runtimes.".format('runtime_timeout'))
        print('Default runtime timeout: {}ms'.format(RUNTIME_TIMEOUT))
    config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT

    if 'workers' not in config_data['lithops']:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS

    if 'azure_fa' not in config_data:
        raise Exception("azure_fa section is mandatory in the configuration")

    required_parameters = ('resource_group', 'location', 'storage_account', 'storage_account_key')

    if set(required_parameters) > set(config_data['azure_fa']):
        raise Exception('You must provide {} to access to Azure Function App'
                        .format(required_parameters))

    if 'runtime' not in config_data['serverless']:
        config_data['azure_fa']['functions_version'] = FUNCTIONS_VERSION
        storage_account = config_data['azure_fa']['storage_account']
        py_version = python_version.replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = '{}-{}-v{}-{}'.format(storage_account, RUNTIME_NAME, py_version, revision)
        config_data['serverless']['runtime'] = runtime_name
