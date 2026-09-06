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

"""
Client-side telemetry.

Lithops already measures a great deal about every call and reports it in
the call status. This package aggregates those numbers as they arrive and
ships them to a metrics system, so that a job can be watched and compared
over time instead of only summarised once it ends.

Backends live under :mod:`lithops.telemetry.backends` and are imported on
demand, so only the client library of the configured one is ever loaded.
"""

from lithops.telemetry.backend import MetricsBackend
from lithops.telemetry.backends import DEFAULT_BACKEND, resolve_backend
from lithops.telemetry.exporter import (
    NOOP,
    BoundTelemetry,
    TelemetryExporter,
    current_telemetry,
    default_instance_id,
    get_telemetry,
    load_backend_config,
    shutdown_telemetry,
)

__all__ = [
    'DEFAULT_BACKEND',
    'NOOP',
    'BoundTelemetry',
    'MetricsBackend',
    'TelemetryExporter',
    'current_telemetry',
    'default_instance_id',
    'get_telemetry',
    'load_backend_config',
    'resolve_backend',
    'shutdown_telemetry',
]
