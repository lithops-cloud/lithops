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

REQUIRED_AZURE_STORAGE_PARAMS = ['storage_account_name', 'storage_account_key']


def load_config(config_data=None):
    if 'azure_storage' not in config_data:
        raise Exception("azure_storage section is mandatory in the configuration")

    for key in REQUIRED_AZURE_STORAGE_PARAMS:
        if key not in config_data['azure_storage']:
            raise Exception('{} key is mandatory in azure section of the configuration'.format(key))

    config_data['azure_blob'] = config_data['azure_storage']
