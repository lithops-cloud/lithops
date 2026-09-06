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
Prometheus Pushgateway telemetry backend.

Prometheus scrapes, and a Lithops client is not there to be scraped: it
is a script that runs for as long as the job does. The Pushgateway exists
for exactly that, and this backend keeps a registry of cumulative metrics
and replaces the gateway group with it on every flush.

Because the group is replaced rather than added to, and because the
grouping key is fixed for the lifetime of the machine, the gateway holds
one group per host no matter how many jobs are run through it.
"""

import logging
from typing import Any, Dict

from lithops.telemetry.backend import MetricsBackend as BaseMetricsBackend
from lithops.telemetry.metrics import (
    COUNTER,
    GAUGE,
    HISTOGRAM,
    UPDOWN,
    MetricSpec,
)

logger = logging.getLogger(__name__)


class MetricsBackend(BaseMetricsBackend):
    """
    Aggregates into a ``prometheus_client`` registry and pushes it to a
    Pushgateway
    """

    backend_name = 'prometheus'

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        try:
            from prometheus_client import CollectorRegistry
        except ImportError as exc:
            raise ImportError(
                'The Prometheus telemetry backend needs the '
                'prometheus-client package. Install it with '
                '"pip install lithops[telemetry]"'
            ) from exc

        self.gateway = config['gateway']
        self.job = config['job']
        self.timeout = config['timeout']
        self.grouping_key = {'instance': config['instance']}
        self.registry = CollectorRegistry()
        self._handler = self._build_handler(config)

        logger.debug(
            f'Prometheus telemetry: pushing to {self.gateway} as '
            f'job={self.job} instance={self.grouping_key["instance"]}'
        )

    @staticmethod
    def _build_handler(config: Dict[str, Any]):
        """
        The push handler, which is where authentication goes when the
        gateway is behind one
        """
        username = config.get('username')
        password = config.get('password')
        if not (username and password):
            return None

        from prometheus_client.exposition import basic_auth_handler

        def handler(url, method, timeout, headers, data):
            return basic_auth_handler(
                url, method, timeout, headers, data, username, password
            )

        return handler

    def _create_instrument(self, spec: MetricSpec):
        from prometheus_client import Counter, Gauge, Histogram

        kwargs = {
            'name': spec.name,
            'documentation': spec.documentation,
            'labelnames': spec.labelnames,
            'registry': self.registry,
        }
        if spec.kind == COUNTER:
            # The _total suffix is the client's to add, and the unit is
            # already part of the name, so neither is passed here
            return Counter(**kwargs)
        if spec.kind == HISTOGRAM:
            return Histogram(buckets=spec.buckets, **kwargs)
        if spec.kind in (UPDOWN, GAUGE):
            return Gauge(**kwargs)
        raise ValueError(f'{spec.name}: unsupported kind {spec.kind}')

    def observe(
        self, spec: MetricSpec, value: float, labels: Dict[str, str]
    ) -> None:
        instrument = self._instrument(spec).labels(**labels)
        if spec.kind == HISTOGRAM:
            instrument.observe(value)
        elif spec.kind == GAUGE:
            instrument.set(value)
        else:
            instrument.inc(value)

    def flush(self) -> None:
        """
        Replaces the gateway group with the current state of the registry.

        A PUT rather than a POST: the registry holds every metric this
        process has recorded since it started, so replacing the group is
        both correct and self healing after a push that did not land
        """
        from prometheus_client import push_to_gateway

        push_to_gateway(
            self.gateway,
            job=self.job,
            registry=_WithoutCreatedSeries(self.registry),
            grouping_key=self.grouping_key,
            timeout=self.timeout,
            handler=self._handler or _default_handler,
        )


class _WithoutCreatedSeries:
    """
    A registry with the ``_created`` series left out.

    ``prometheus_client`` exposes a ``<name>_created`` gauge next to every
    counter, holding the time the counter was first observed. It is of no
    use here and it doubles the number of series a counter costs, which
    is the one thing the metric inventory is shaped to keep down. There is
    no per instrument switch for it, only a process wide one, so it is
    filtered on the way out instead.

    Duck typed rather than a real registry: an object with ``collect()``
    is all the exposition format needs
    """

    __slots__ = ('_registry',)

    def __init__(self, registry):
        self._registry = registry

    def collect(self):
        from prometheus_client.metrics_core import Metric

        for family in self._registry.collect():
            kept = [
                sample for sample in family.samples
                if not sample.name.endswith('_created')
            ]
            if not kept:
                continue
            # A copy, so that filtering the push never touches what the
            # registry itself holds
            filtered = Metric(
                family.name, family.documentation, family.type, family.unit
            )
            filtered.samples = kept
            yield filtered


def _default_handler(url, method, timeout, headers, data):
    from prometheus_client.exposition import default_handler

    return default_handler(url, method, timeout, headers, data)
