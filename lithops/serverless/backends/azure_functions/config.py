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

import os
import copy

from lithops.constants import TEMP_DIR

BUILD_DIR = os.path.join(TEMP_DIR, 'AzureRuntimeBuild')
ACTION_DIR = 'lithops_handler'
ACTION_MODULES_DIR = os.path.join('.python_packages', 'lib', 'site-packages')

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_azure_fa.zip')

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 300 seconds => 5 minutes
    'runtime_memory': 1536,  # Default memory: 1536 MB
    'max_workers': 1000,
    'worker_processes': 1,
    'invoke_pool_threads': 10,
    'functions_version': 4,
    'trigger': 'pub/sub'
}

AVAILABLE_PY_RUNTIMES = ['3.7', '3.8', '3.9', '3.10', '3.11']

REQUIRED_AZURE_STORAGE_PARAMS = ('storage_account_name', 'storage_account_key')
REQUIRED_AZURE_FUNCTIONS_PARAMS = ('resource_group', 'region')

IN_QUEUE = "in-trigger"
OUT_QUEUE = "out-result"

BINDINGS_QUEUE = {
    "scriptFile": "__init__.py",
    "entryPoint": "main_queue",
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

BINDINGS_HTTP = {
    "scriptFile": "__init__.py",
    "entryPoint": "main_http",
    "bindings": [
        {
            "authLevel": "anonymous",
            "type": "httpTrigger",
            "direction": "in",
            "name": "req",
            "methods": [
                "get",
                "post"
            ]
        },
        {
            "type": "http",
            "direction": "out",
            "name": "$return"
        }]}

# https://docs.microsoft.com/en-us/azure/azure-functions/functions-host-json
HOST_FILE = """
{
    "version": "2.0",
    "logging": {
        "fileLoggingMode": "always",
        "logLevel": {
            "default": "Debug",
            "Function.lithops_handler": "Debug",
            "EventForwarder": "Debug"
        },
        "console": {
            "isEnabled": "true"
        },
        "applicationInsights": {
            "samplingSettings": {
                "excludedTypes": "Request;Trace"
            }
        }
    },
    "extensions": {
        "http": {
            "maxOutstandingRequests": 1,
            "maxConcurrentRequests": 1,
            "dynamicThrottlesEnabled": true
        },
        "queues": {
            "maxPollingInterval": 2000,
            "visibilityTimeout" : "00:00:05",
            "batchSize": 1,
            "maxDequeueCount": 5,
            "newBatchThreshold": 1
        },
    },
    "extensionBundle": {
        "id": "Microsoft.Azure.Functions.ExtensionBundle",
        "version": "[2.*, 3.0.0)"
    }
}
"""

REQUIREMENTS_FILE = """
azure-functions
azure-storage-blob
azure-storage-queue
pika
flask
gevent
numpy
redis
requests
PyYAML
kubernetes
cloudpickle
ps-mem
tblib
"""


def load_config(config_data):
    if 'azure_storage' not in config_data or not config_data['azure_storage']:
        raise Exception("'azure_storage' section is mandatory in the configuration")

    if 'azure' in config_data and config_data['azure'] is not None:
        temp = copy.deepcopy(config_data['azure_functions'])
        config_data['azure_functions'].update(config_data['azure'])
        config_data['azure_functions'].update(temp)

    if not config_data['azure_functions']:
        raise Exception("'azure_functions' section is mandatory in the configuration")

    if 'location' in config_data['azure_functions']:
        config_data['azure_functions']['region'] = config_data['azure_functions'].pop('location')

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['azure_functions']:
            config_data['azure_functions'][key] = DEFAULT_CONFIG_KEYS[key]

    for key in REQUIRED_AZURE_STORAGE_PARAMS:
        if key not in config_data['azure_storage']:
            raise Exception(f'{key} key is mandatory in azure section of the configuration')

    for key in REQUIRED_AZURE_FUNCTIONS_PARAMS:
        if key not in config_data['azure_functions']:
            raise Exception(f'{key} key is mandatory in azure section of the configuration')

    config_data['azure_functions'].update(config_data['azure_storage'])
