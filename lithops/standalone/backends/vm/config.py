#
# Copyright Cloudlab URV 2021
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

from lithops.constants import SA_DEFAULT_CONFIG_KEYS

REQ_PARAMETERS = ('ip_address', 'ssh_username')


def load_config(config_data):

    for param in REQ_PARAMETERS:
        if param not in config_data['vm']:
            msg = f"'{param}' is mandatory in 'vm' section of the configuration"
            raise Exception(msg)

    config_data['vm']['max_workers'] = 1

    if "worker_processes" not in config_data['vm']:
        config_data['vm']['worker_processes'] = "AUTO"

    if 'standalone' not in config_data or config_data['standalone'] is None:
        config_data['standalone'] = {}

    for key in SA_DEFAULT_CONFIG_KEYS:
        if key in config_data['vm']:
            config_data['standalone'][key] = config_data['vm'].pop(key)
        elif key not in config_data['standalone']:
            config_data['standalone'][key] = SA_DEFAULT_CONFIG_KEYS[key]

    # A single existing machine is both master and worker
    config_data['standalone']['exec_mode'] = 'consume'
    config_data['standalone']['auto_dismantle'] = False
