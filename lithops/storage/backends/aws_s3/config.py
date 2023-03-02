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


import copy


def load_config(config_data):

    if 'aws' in config_data:

        if not {'access_key_id', 'secret_access_key'}.issubset(set(config_data['aws'])):
            raise Exception("'access_key_id' and 'secret_access_key' are mandatory under the 'aws' section of the configuration")

        if 'aws_s3' not in config_data:
            config_data['aws_s3'] = {}

        temp = copy.deepcopy(config_data['aws_s3'])
        config_data['aws_s3'].update(config_data['aws'])
        config_data['aws_s3'].update(temp)

        if 'region_name' in config_data['aws_s3']:
            config_data['aws_s3']['region'] = config_data['aws_s3'].pop('region_name')

        if 'region' not in config_data['aws_s3']:
            raise Exception("'region' is mandatory under 'aws_s3' or 'aws' section of the configuration")

        if 'storage_bucket' not in config_data['aws_s3']:
            key = config_data['aws_s3']['access_key_id']
            region = config_data['aws_s3']['region']
            config_data['aws_s3']['storage_bucket'] = f'lithops-{region}-{key[:6].lower()}'
