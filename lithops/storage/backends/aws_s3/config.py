#
# (C) Copyright Cloudlab URV 2020
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


REQ_PARAMS = ['secret_access_key', 'access_key_id']


def load_config(config_data):
    if 'aws' not in config_data or 'aws_s3' not in config_data:
        raise Exception("'aws' and 'aws_s3' sections are mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['aws']:
            msg = f"'{param}' is mandatory under 'aws' section of the configuration"
            raise Exception(msg)

    # Put credential keys to 'aws_s3' dict entry
    config_data['aws_s3'].update(config_data['aws'])

    if 'endpoint' not in config_data['aws_s3']:
        raise Exception("'endpoint' is mandatory under 'aws_s3' section of the configuration")

    if not config_data['aws_s3']['endpoint'].startswith('http'):
        raise Exception('S3 endpoint must start with http:// or https://')
