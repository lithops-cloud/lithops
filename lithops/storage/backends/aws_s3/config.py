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

def load_config(config_data=None):
    if 'aws' not in config_data and 'aws_s3' not in config_data:
        raise Exception("'aws' and 'aws_s3' sections are mandatory in the configuration")

    required_parameters_0 = ('access_key_id', 'secret_access_key')
    if not set(required_parameters_0) <= set(config_data['aws']):
        raise Exception("'access_key_id' and 'secret_access_key' are mandatory under 'aws' section")
    
    # Put credential keys to 'aws_s3' dict entry
    config_data['aws_s3'] = {**config_data['aws_s3'], **config_data['aws']}
    
    if 'endpoint' not in config_data['aws_s3']:
        raise Exception("'endpoint' is mandatory under 's3' section")