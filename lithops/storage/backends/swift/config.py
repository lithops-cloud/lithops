#
# (C) Copyright IBM Corp. 2018
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

REQ_PARAMS = ('auth_url', 'user_id', 'project_id', 'password', 'region')


def load_config(config_data):
    if 'swift' not in config_data:
        raise Exception("swift section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['swift']:
            msg = f"'{param}' is mandatory under 'swift' section of the configuration"
            raise Exception(msg)

    if 'storage_bucket' in config_data['swift']:
        config_data['lithops']['storage_bucket'] = config_data['swift']['storage_bucket']
