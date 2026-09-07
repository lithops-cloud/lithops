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

from lithops.telemetry.exporter import default_instance_id

DEFAULT_CONFIG_KEYS = {
    'gateway': 'http://localhost:9091',
    'job': 'lithops',
    'timeout': 10,
}


def load_config(config_data):
    """
    Fills in the defaults of the ``prometheus`` section.

    ``instance`` defaults to the hostname rather than to anything derived
    from the execution: it is part of the Pushgateway grouping key, and a
    key that changed on every run would leave a group behind on every run.
    The Pushgateway has no expiry, so those groups would be served to
    Prometheus for ever
    """
    section = config_data.get('prometheus') or {}
    config_data['prometheus'] = section

    for key, value in DEFAULT_CONFIG_KEYS.items():
        section.setdefault(key, value)
    section.setdefault('instance', default_instance_id())
