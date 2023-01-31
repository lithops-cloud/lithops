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


REQ_PARAMS1 = ('secret_access_key', 'access_key_id')
REQ_PARAMS2 = ('region_name', )


def load_config(config_data):

    if 'aws' in config_data and 'aws_s3' in config_data:

        for param in REQ_PARAMS1:
            if param not in config_data['aws']:
                msg = f"'{param}' is mandatory under 'aws' section of the configuration"
                raise Exception(msg)

        for param in REQ_PARAMS2:
            if param not in config_data['aws_s3']:
                msg = f"'{param}' is mandatory under 'aws_s3' section of the configuration"
                raise Exception(msg)

        config_data['aws_s3'].update(config_data['aws'])
