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
    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    required_parameters_0 = ('project_name', 'service_account', 'credentials_path')
    if not set(required_parameters_0) <= set(config_data['gcp']):
        raise Exception("'project_name', 'service_account' and 'credentials_path' "
        "are mandatory under 'gcp' section")

    if 'region' not in config_data['gcp']:
        config_data['gcp']['region'] = config_data['lithops']['compute_backend_region']

    config_data['gcp_storage'] = config_data['gcp'].copy()
