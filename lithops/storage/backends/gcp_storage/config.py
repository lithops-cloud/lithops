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

import copy
import hashlib
import os


def load_config(config_data=None):
    if 'gcp' not in config_data:
        raise Exception("gcp section is mandatory in the configuration")

    if 'credentials_path' not in config_data['gcp']:
        if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
            config_data['gcp']['credentials_path'] = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

    if 'credentials_path' in config_data['gcp']:
        config_data['gcp']['credentials_path'] = os.path.expanduser(config_data['gcp']['credentials_path'])

    if 'gcp_storage' not in config_data:
        config_data['gcp_storage'] = {}

    temp = copy.deepcopy(config_data['gcp_storage'])
    config_data['gcp_storage'].update(config_data['gcp'])
    config_data['gcp_storage'].update(temp)

    if 'region' not in config_data['gcp_storage']:
        raise Exception("'region' parameter is mandatory under 'gcp_storage' or 'gcp' section of the configuration")

    if 'storage_bucket' not in config_data['gcp_storage']:
        gcps = config_data['gcp_storage']
        region = gcps['region']
        key = hashlib.sha1(gcps['credentials_path'].encode()).hexdigest()[:6]
        config_data['gcp_storage']['storage_bucket'] = f'lithops-{region}-{key[:6].lower()}'
