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

import copy


REQ_PARAMS = ('storage_account_name', 'storage_account_key')


def load_config(config_data):
    overrides = copy.deepcopy(config_data.get('azure_queue') or {})
    merged = {}
    if config_data.get('azure'):
        merged.update(config_data['azure'])
    if config_data.get('azure_storage'):
        merged.update(config_data['azure_storage'])
    merged.update(overrides)
    config_data['azure_queue'] = merged

    for param in REQ_PARAMS:
        if param not in config_data['azure_queue']:
            raise Exception(
                f"'{param}' is mandatory under 'azure_queue' or "
                "'azure_storage' section of the configuration"
            )
