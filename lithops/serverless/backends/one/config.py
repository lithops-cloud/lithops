#
# (C) Copyright Cloudlab URV 2024
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
import enum


@enum.unique
class ServiceState(enum.Enum):
    RUNNING = 2
    SCALING = 9
    COOLDOWN = 10


DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 10 minutes
    'runtime_memory': 512,  # Default memory: 512 MB
    'max_workers': 100,
    'worker_processes': 1,
}


def load_config(config_data):
    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['one']:
            config_data['one'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'rabbitmq' not in config_data:
        raise Exception('RabbitMQ configuration is needed in this backend')
    else:
        config_data['one']['amqp_url'] = config_data['rabbitmq'].get('amqp_url', False)
