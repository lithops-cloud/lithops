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

REQ_PARAMS = ('project_id',)


def load_config(config_data):
    if 'gcsfs' not in config_data:
        raise Exception("gcsfs section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['gcsfs']:
            msg = f"'{param}' is mandatory under 'gcsfs' section of the configuration"
            raise Exception(msg)

    if 'storage_bucket' in config_data['gcsfs']:
        config_data['lithops']['storage_bucket'] = config_data['gcsfs']['storage_bucket']
