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
Client-side job monitoring and worker-side status reporting.

Backends live under :mod:`lithops.monitoring.backends` and are imported
on demand, so that only the SDK of the configured one is ever loaded.
"""

from lithops.monitoring.backends import DEFAULT_BACKEND, resolve_backend
from lithops.monitoring.monitor import (
    LOG_INTERVAL,
    MessageMonitor,
    Monitor,
    PollingMessageMonitor,
)
from lithops.monitoring.job_monitor import JobMonitor
from lithops.monitoring.status import (
    CallStatus,
    MessageCallStatus,
    StorageCallStatus,
    create_call_status,
)

__all__ = [
    'DEFAULT_BACKEND',
    'LOG_INTERVAL',
    'CallStatus',
    'JobMonitor',
    'MessageCallStatus',
    'MessageMonitor',
    'Monitor',
    'PollingMessageMonitor',
    'StorageCallStatus',
    'create_call_status',
    'resolve_backend',
]
