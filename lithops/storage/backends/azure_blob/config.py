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

def load_config(config_data=None):
    if 'azure_blob' not in config_data:
        raise Exception("azure_blob section is mandatory in the configuration")

    required_parameters = ('account_name', 'account_key')

    if set(required_parameters) > set(config_data['azure_blob']):
        raise Exception('You must provide {} to access to Azure Blob Storage'.format(required_parameters))

