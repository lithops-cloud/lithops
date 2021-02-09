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

# General lithops.multiprocessing parameters
LITHOPS_CONFIG = 'LITHOPS_CONFIG'  # Override lithops configuration
STREAM_STDOUT = 'STREAM_STDOUT'  # Enable remote logging
ENV_VARS = 'ENV_VARS'  # Processes environment variables

# Redis specific parameters
REDIS_EXPIRY_TIME = 'REDIS_EXPIRY_TIME'  # Redis key expiry time in seconds
REDIS_CONNECTION_TYPE = 'REDIS_CONNECTION_TYPE'  # Pipe/Queue connection type

_DEFAULT_CONFIG = {
    LITHOPS_CONFIG: {},
    STREAM_STDOUT: False,
    REDIS_EXPIRY_TIME: 900,
    REDIS_CONNECTION_TYPE: 'listconn',
    ENV_VARS: {}
}

_config = _DEFAULT_CONFIG


def update(config_dic=None, **configurations):
    if config_dic is None:
        config_dic = {}
    _config.update(config_dic)
    _config.update(configurations)


def set_parameter(key, value):
    if key in _config:
        _config[key] = value
    else:
        raise KeyError(key)


def get_parameter(parameter):
    return _config[parameter]
