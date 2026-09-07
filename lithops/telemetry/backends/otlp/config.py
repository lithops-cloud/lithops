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
    'endpoint': 'http://localhost:4318',
    'protocol': 'http/protobuf',
    'service_name': 'lithops',
    'timeout': 10,
    # The exporter drives the export itself, on lithops.telemetry_interval.
    # This is only the backstop of the OpenTelemetry SDK, in seconds
    'export_interval': 3600,
}


def load_config(config_data):
    """
    Fills in the defaults of the ``otlp`` section
    """
    section = config_data.get('otlp') or {}
    config_data['otlp'] = section

    for key, value in DEFAULT_CONFIG_KEYS.items():
        section.setdefault(key, value)
    section.setdefault('instance', default_instance_id())
    section.setdefault('headers', {})
