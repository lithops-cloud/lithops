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
Monitoring backends.

Each backend is a package named after the service (``storage``,
``rabbitmq``, ``redis``, ``aws_sqs``, ``gcp_pubsub``,
``azure_queue``, ...). It must export:

* ``MonitoringBackend`` — a :class:`~lithops.monitoring.monitor.Monitor`
  (or :class:`~lithops.monitoring.monitor.MessageMonitor`) subclass the
  client runs as a thread.
* ``CallStatus`` — a :class:`~lithops.monitoring.status.CallStatus`
  subclass workers use to report progress.

and carry a ``config.py`` with a ``load_config(config_data)`` function.

Adding a backend is adding a package. :class:`~lithops.monitoring.JobMonitor`
and :func:`~lithops.monitoring.create_call_status` load it with::

    lithops.monitoring.backends.<name>

The name of the package is also the name of the config section the backend
reads and the value ``monitoring:`` selects it by; ``Monitor`` takes its
``backend_name`` from the package it is defined in.
"""

from typing import Any, Dict, Optional

from lithops import utils

#: Backend used when the configuration does not name one. Every storage
#: backend can act as a monitoring channel, so this always works
DEFAULT_BACKEND = 'storage'


def resolve_backend(
        config: Optional[Dict[str, Any]] = None,
        backend: Optional[str] = None,
) -> str:
    """
    Name of the monitoring backend to use.

    ``backend`` wins over ``config['lithops']['monitoring']``, which in turn
    wins over :data:`DEFAULT_BACKEND`. Resolved the same way on the client
    and in the worker, so the two cannot pick different backends
    """
    if backend:
        return str(backend).lower()
    if config:
        monitoring = (config.get('lithops') or {}).get('monitoring')
        if monitoring:
            return str(monitoring).lower()
    return DEFAULT_BACKEND


def import_backend_module(backend: str, submodule: Optional[str] = None):
    """
    Imports ``lithops.monitoring.backends.<backend>`` or one of its
    submodules. An unknown backend raises ValueError; one whose SDK is
    missing keeps its own ImportError
    """
    return utils.import_backend_module(__name__, 'monitoring', backend, submodule)


def load_backend_attr(backend: str, attr: str):
    """
    Returns ``attr`` of ``lithops.monitoring.backends.<backend>``, naming
    the backend when the package does not export it
    """
    return utils.load_backend_attr(__name__, 'monitoring', backend, attr)
