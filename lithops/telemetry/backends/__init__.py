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
Telemetry backends.

Each backend is a package named after the system it ships metrics to
(``prometheus``, ``otlp``). It must export ``MetricsBackend`` -- a
:class:`~lithops.telemetry.backend.MetricsBackend` subclass -- and carry
a ``config.py`` with a ``load_config(config_data)`` function that fills
in the defaults of its own configuration section.

The name of the package is the name of that section and the value
``lithops.telemetry`` selects it by.
"""

from typing import Any, Dict, Optional

from lithops import utils

#: Backend used when telemetry is switched on without naming one
DEFAULT_BACKEND = 'prometheus'

#: Values of ``lithops.telemetry`` that mean "off". Written out because a
#: config file that says ``telemetry: false`` parses to the bool, one that
#: says ``telemetry: "false"`` to the string, and both mean the same thing
_DISABLED = frozenset({'', 'false', 'no', 'none', 'off', '0'})

#: Values that mean "on, backend unspecified"
_ENABLED = frozenset({'true', 'yes', 'on', '1'})


def resolve_backend(
        config: Optional[Dict[str, Any]] = None,
        backend: Optional[str] = None,
) -> Optional[str]:
    """
    Name of the telemetry backend to use, or None when telemetry is off.

    ``backend`` wins over ``config['lithops']['telemetry']``. A truthy
    value that does not name a backend selects :data:`DEFAULT_BACKEND`,
    so that ``telemetry: true`` keeps working as the switch it reads like
    """
    value = backend
    if value is None and config:
        value = (config.get('lithops') or {}).get('telemetry')

    if value is None or value is False:
        return None
    if value is True:
        return DEFAULT_BACKEND

    value = str(value).strip().lower()
    if value in _DISABLED:
        return None
    if value in _ENABLED:
        return DEFAULT_BACKEND
    return value


def import_backend_module(backend: str, submodule: Optional[str] = None):
    """
    Imports ``lithops.telemetry.backends.<backend>`` or one of its
    submodules. An unknown backend raises ValueError; one whose client
    library is missing keeps its own ImportError
    """
    return utils.import_backend_module(__name__, 'telemetry', backend, submodule)


def load_backend_class(backend: str):
    """
    Returns the ``MetricsBackend`` class of ``backend``
    """
    return utils.load_backend_attr(__name__, 'telemetry', backend, 'MetricsBackend')
