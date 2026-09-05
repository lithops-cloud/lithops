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
reads and the value ``monitoring:`` selects it by; ``Monitor`` checks that
its ``backend_name`` agrees with the package it is defined in.
"""

import importlib
from typing import Any, Dict, Optional

#: Backend used when the configuration does not name one. Every storage
#: backend can act as a monitoring channel, so this always works
DEFAULT_BACKEND = 'storage'

#: Attribute name each backend package exports, and the base class it has
#: to be a subclass of. Loaded lazily so that importing this module does
#: not pull the whole monitoring package in
_CONTRACT = {
    'MonitoringBackend': ('lithops.monitoring.monitor', 'Monitor'),
    'CallStatus': ('lithops.monitoring.status', 'CallStatus'),
}


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
    submodules.

    Raises ValueError only when the backend itself is not there. A
    backend whose SDK is missing keeps its own ImportError, which names
    the package to install instead of claiming the backend is unknown.
    """
    module_name = f'lithops.monitoring.backends.{backend}'
    if submodule:
        module_name = f'{module_name}.{submodule}'
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and not module_name.startswith(exc.name):
            raise
        raise ValueError(f'Unknown monitoring backend: {backend}') from exc


def load_backend_attr(backend: str, attr: str):
    """
    Returns ``attr`` of ``lithops.monitoring.backends.<backend>``, checked
    against the backend contract so that a package that exports the wrong
    thing fails here rather than halfway through a job
    """
    module = import_backend_module(backend)

    try:
        value = getattr(module, attr)
    except AttributeError as exc:
        raise ValueError(
            f"Monitoring backend '{backend}' exports no {attr}"
        ) from exc

    expected = _CONTRACT.get(attr)
    if expected is None:
        return value

    base_module, base_name = expected
    base = getattr(importlib.import_module(base_module), base_name)
    if not (isinstance(value, type) and issubclass(value, base)):
        raise ValueError(
            f"Monitoring backend '{backend}' exports {attr}="
            f"{value!r}, which is not a {base_name} subclass"
        )
    return value
