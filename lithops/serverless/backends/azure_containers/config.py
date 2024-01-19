#
# (C) Copyright IBM Corp. 2022
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

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_azure_ca.zip')
CA_JSON_LOCATION = os.path.join(TEMP_DIR, 'lithops_containerapp.yaml')

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 600 seconds => 10 minutes
    'runtime_memory': 512,  # Default memory: 512 MB
    'max_workers': 1000,
    'worker_processes': 1,
    'invoke_pool_threads': 32,
    'trigger': 'pub/sub',
    'environment': 'lithops',
    'docker_server': 'index.docker.io'
}

ALLOWED_MEM = {
    512: ('0.5Gi', 0.25),
    1024: ('1Gi', 0.5),
    1536: ('1.5Gi', 0.75),
    2048: ('2Gi', 1),
    2560: ('2.5Gi', 1.25),
    3072: ('3Gi', 1.5),
    3584: ('3.5Gi', 1.75),
    4096: ('4Gi', 2),
}

REQUIRED_AZURE_STORAGE_PARAMS = ('storage_account_name', 'storage_account_key')
REQUIRED_AZURE_CONTAINERS_PARAMS = ('resource_group', 'region')

CONTAINERAPP_JSON = {
    "type": "Microsoft.App/containerApps",
    "name": "",
    "apiVersion": "2022-03-01",
    "kind": "containerapp",
    "location": "",
    "tags": {
        "type": "",
        "lithops_version": "",
        "runtime_name": "",
        "runtime_memory": "",
    },
    "properties": {
        "managedEnvironmentId": "",
        "configuration": {
            "activeRevisionsMode": "single",
            "secrets": [{
                "name": "queueconnection",
                "value": ""
            }, {
                "name": "dockerhubtoken",
                "value": ""
            }],
            "registries": [{
                "server": "",
                "username": "",
                "passwordSecretRef": "dockerhubtoken"
            }]
        },
        "template": {
            "containers": [
                {
                    "image": "",
                    "name": "lithops-runtime",
                    "env": [
                        {
                            "name": "QueueName",
                            "value": "",
                        },
                        {
                            "name": "QueueConnectionString",
                            "secretRef": "queueconnection"
                        }
                    ],
                    "resources": {
                        "cpu": 0.25,
                        "memory": "0.5Gi"
                    },
                }
            ],
            "scale": {
                "minReplicas": 0,
                "maxReplicas": 30,
                "rules": [
                    {
                        "name": "queue-based-autoscaling",
                        "azureQueue": {
                            "queueName": "",
                            "queueLength": 1,
                            "auth": [
                                {
                                    "secretRef": "queueconnection",
                                    "triggerParameter": "connection"
                                }
                            ]
                        }
                    }
                ]
            }
        }
    }
}


DEFAULT_DOCKERFILE = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
        azure-storage-blob \
        azure-storage-queue \
        pika \
        flask \
        gevent \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib

WORKDIR /app
COPY lithops_azure_ca.zip .
RUN unzip lithops_azure_ca.zip && rm lithops_azure_ca.zip

CMD ["python", "lithopsentry.py"]
"""


def load_config(config_data):
    if 'azure_storage' not in config_data or not config_data['azure_storage']:
        raise Exception("'azure_storage' section is mandatory in the configuration")

    if 'azure' in config_data and config_data['azure'] is not None:
        temp = copy.deepcopy(config_data['azure_containers'])
        config_data['azure_containers'].update(config_data['azure'])
        config_data['azure_containers'].update(temp)

    if not config_data['azure_containers']:
        raise Exception("'azure_containers' section is mandatory in the configuration")

    if 'location' in config_data['azure_containers']:
        config_data['azure_containers']['region'] = config_data['azure_containers'].pop('location')

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['azure_containers']:
            config_data['azure_containers'][key] = DEFAULT_CONFIG_KEYS[key]

    for key in REQUIRED_AZURE_STORAGE_PARAMS:
        if key not in config_data['azure_storage']:
            raise Exception(f'{key} key is mandatory in azure section of the configuration')

    for key in REQUIRED_AZURE_CONTAINERS_PARAMS:
        if key not in config_data['azure_containers']:
            raise Exception(f'{key} key is mandatory in azure section of the configuration')

    config_data['azure_containers'].update(config_data['azure_storage'])
