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
OpenTelemetry telemetry backend.

Where the Prometheus backend talks to one specific system, this one talks
to an OpenTelemetry collector, which is then free to forward the same
metrics to Prometheus over remote write, to a hosted service, or to
several at once. It is the option to reach for when Lithops is one
workload among many rather than the thing being watched.

Metric names are the ones :mod:`lithops.telemetry.metrics` declares, so a
dashboard written against the Prometheus backend keeps working when the
metrics arrive through a collector instead.
"""

import logging
from typing import Any, Dict

from lithops.telemetry.backend import MetricsBackend as BaseMetricsBackend
from lithops.telemetry.metrics import (
    ALL_METRICS,
    COUNTER,
    GAUGE,
    HISTOGRAM,
    UPDOWN,
    MetricSpec,
)
from lithops.version import __version__

logger = logging.getLogger(__name__)

_METRICS_PATH = '/v1/metrics'


def _metrics_endpoint(endpoint: str) -> str:
    """
    The OTLP/HTTP metrics endpoint. Both the collector root and the full
    signal URL are accepted, because both are what people have written
    down
    """
    endpoint = endpoint.rstrip('/')
    if endpoint.endswith(_METRICS_PATH):
        return endpoint
    return endpoint + _METRICS_PATH


class MetricsBackend(BaseMetricsBackend):
    """
    Aggregates through an OpenTelemetry meter and exports over OTLP
    """

    backend_name = 'otlp'

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        try:
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.resources import Resource
        except ImportError as exc:
            raise ImportError(
                'The OTLP telemetry backend needs the opentelemetry-sdk '
                'package. Install it with '
                '"pip install lithops[telemetry]"'
            ) from exc

        resource = Resource.create({
            'service.name': config['service_name'],
            'service.version': __version__,
            'host.name': config['instance'],
        })
        self._provider = MeterProvider(
            resource=resource,
            metric_readers=[self._create_reader(config)],
            views=self._create_views(),
        )
        self._meter = self._provider.get_meter('lithops', __version__)

        logger.debug(
            f"OTLP telemetry: exporting to {config['endpoint']} over "
            f"{config['protocol']} as {config['service_name']}"
        )

    @staticmethod
    def _cumulative_temporality():
        """
        Every instrument exported as a cumulative total rather than as a
        delta since the last export.

        Pinned rather than left to the SDK. Cumulative is what Prometheus
        accepts, whether the metrics reach it through its own OTLP
        receiver or through a collector, and the SDK default is
        overridden by an OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE
        that may well be in the environment for something else
        """
        from opentelemetry.sdk.metrics import (
            Counter,
            Histogram,
            ObservableCounter,
            ObservableGauge,
            ObservableUpDownCounter,
            UpDownCounter,
        )
        from opentelemetry.sdk.metrics.export import AggregationTemporality

        return {
            instrument: AggregationTemporality.CUMULATIVE
            for instrument in (
                Counter,
                UpDownCounter,
                Histogram,
                ObservableCounter,
                ObservableUpDownCounter,
                ObservableGauge,
            )
        }

    @classmethod
    def _create_reader(cls, config: Dict[str, Any]):
        """
        The periodic reader and the OTLP exporter behind it.

        Split out so that a test, or a backend that wants a different
        transport, can put its own reader in without reimplementing the
        instrument and view handling
        """
        from opentelemetry.sdk.metrics.export import (
            PeriodicExportingMetricReader,
        )

        temporality = cls._cumulative_temporality()
        protocol = str(config['protocol']).lower()
        if protocol in ('grpc', 'grpc/protobuf'):
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            exporter = OTLPMetricExporter(
                endpoint=config['endpoint'],
                headers=config['headers'] or None,
                timeout=config['timeout'],
                preferred_temporality=temporality,
            )
        elif protocol in ('http', 'http/protobuf'):
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )
            exporter = OTLPMetricExporter(
                endpoint=_metrics_endpoint(config['endpoint']),
                headers=config['headers'] or None,
                timeout=config['timeout'],
                preferred_temporality=temporality,
            )
        else:
            raise ValueError(
                f"Unknown OTLP protocol '{config['protocol']}'. Use "
                f"'http/protobuf' or 'grpc'"
            )

        return PeriodicExportingMetricReader(
            exporter,
            export_interval_millis=float(config['export_interval']) * 1000,
        )

    @staticmethod
    def _create_views():
        """
        Pins the bucket boundaries of every histogram.

        Views have to exist before the meter provider does, which is why
        this walks the whole inventory rather than being done lazily with
        the instruments
        """
        from opentelemetry.sdk.metrics.view import (
            ExplicitBucketHistogramAggregation,
            View,
        )

        return [
            View(
                instrument_name=spec.name,
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=spec.buckets
                ),
            )
            for spec in ALL_METRICS
            if spec.kind == HISTOGRAM
        ]

    def _create_instrument(self, spec: MetricSpec):
        # The unit is deliberately not declared: it is already part of
        # every metric name, and a collector translating to Prometheus
        # appends the unit to the name it is given
        if spec.kind == COUNTER:
            return self._meter.create_counter(
                spec.name, description=spec.documentation
            )
        if spec.kind == HISTOGRAM:
            return self._meter.create_histogram(
                spec.name, description=spec.documentation
            )
        if spec.kind == UPDOWN:
            return self._meter.create_up_down_counter(
                spec.name, description=spec.documentation
            )
        if spec.kind == GAUGE:
            return self._meter.create_gauge(
                spec.name, description=spec.documentation
            )
        raise ValueError(f'{spec.name}: unsupported kind {spec.kind}')

    def observe(
        self, spec: MetricSpec, value: float, labels: Dict[str, str]
    ) -> None:
        instrument = self._instrument(spec)
        if spec.kind == HISTOGRAM:
            instrument.record(value, attributes=labels)
        elif spec.kind == GAUGE:
            instrument.set(value, attributes=labels)
        else:
            instrument.add(value, attributes=labels)

    def flush(self) -> None:
        self._provider.force_flush()

    def shutdown(self) -> None:
        self._provider.shutdown()
