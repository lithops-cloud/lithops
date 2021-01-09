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

_set = set

DEFAULT_CONFIG = {
    'lithops': {},
    'redis_expiry_time': 3600,
    'stream_stdout': False
}

_config = DEFAULT_CONFIG


def set(config_dic=None, **configurations):
    if config_dic is None:
        config_dic = {}
    _config.update(config_dic)
    _config.update(configurations)


def get_config():
    return _config
