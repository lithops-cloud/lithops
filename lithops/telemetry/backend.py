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
The contract a telemetry backend implements.

A backend owns an aggregator (a Prometheus registry, an OpenTelemetry
meter provider) and knows how to get what it has aggregated out of the
process. It never decides *what* is measured: that is
:mod:`lithops.telemetry.metrics`.
"""

import logging
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from lithops.telemetry.metrics import MetricSpec

logger = logging.getLogger(__name__)


class MetricsBackend(ABC):
    """
    Aggregates observations and ships them somewhere.

    Backends are instantiated with the section of the Lithops
    configuration named after them, already filled in with the defaults
    their ``config.py`` declares.

    Implementations only have to build their instruments and push. The
    exporter above them takes care of never calling into a backend with
    labels the spec does not declare, and of swallowing whatever a
    backend raises: telemetry never breaks a job.
    """

    #: Config section this backend reads, and the value ``telemetry:``
    #: selects it by. Derived from the package name in
    #: :mod:`lithops.telemetry.backends`
    backend_name: Optional[str] = None

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Instruments are built on first use from the monitor thread and
        # from the threads that submit jobs, so the cache is locked. The
        # underlying client libraries are themselves thread safe once the
        # instrument exists; this only guards the creation
        self._instruments: Dict[str, Any] = {}
        self._instruments_lock = threading.Lock()

    def _instrument(self, spec: MetricSpec) -> Any:
        """
        The instrument of ``spec``, built once and cached
        """
        instrument = self._instruments.get(spec.name)
        if instrument is not None:
            return instrument
        with self._instruments_lock:
            # Checked again: two threads can get past the fast path
            if spec.name not in self._instruments:
                self._instruments[spec.name] = self._create_instrument(spec)
            return self._instruments[spec.name]

    @abstractmethod
    def _create_instrument(self, spec: MetricSpec) -> Any:
        """
        Builds the backend instrument that records ``spec``
        """

    @abstractmethod
    def observe(
        self,
        spec: MetricSpec,
        value: float,
        labels: Dict[str, str],
    ) -> None:
        """
        Records one observation. ``labels`` holds exactly the keys of
        ``spec.labelnames``
        """

    def flush(self) -> None:
        """
        Gets what has been aggregated so far out of the process. Called on
        a timer by the exporter, and once more on shutdown
        """

    def shutdown(self) -> None:
        """
        Releases whatever the backend holds. Called once, after the last
        flush
        """
