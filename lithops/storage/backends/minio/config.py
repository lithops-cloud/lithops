#
# (C) Copyright Cloudlab URV 2021
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

REQ_PARAMS = ('endpoint', 'secret_access_key', 'access_key_id')


def load_config(config_data):
    if 'minio' not in config_data:
        raise Exception("minio section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['minio']:
            msg = f"'{param}' is mandatory under 'minio' section of the configuration"
            raise Exception(msg)

    if not config_data['minio']['endpoint'].startswith('http'):
        raise Exception('MinIO endpoint must start with http:// or https://')

    if 'storage_bucket' in config_data['minio']:
        config_data['lithops']['storage_bucket'] = config_data['minio']['storage_bucket']
