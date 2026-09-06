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
Turns the call statuses Lithops already collects into metrics.

Everything is measured on the client. The worker writes its status once,
as it always did, and the monitor thread that reads it feeds the numbers
in here on its way past. Nothing is added to the critical path of a
function, no worker needs a route to the metrics system, and every
monitoring backend is instrumented by the same code.

The exporter is a process-wide singleton. Counters are cumulative for the
lifetime of the process, which is what a time series database expects,
and one process pushes under one identity however many executors it
creates.
"""

import atexit
import logging
import os
import socket
import threading
from typing import Any, Dict, Optional

from lithops.telemetry import metrics as M
from lithops.version import __version__
from lithops.telemetry.backends import (
    import_backend_module,
    load_backend_class,
    resolve_backend,
)

logger = logging.getLogger(__name__)

#: How often the aggregated metrics leave the process, in seconds
DEFAULT_FLUSH_INTERVAL = 10

_UNKNOWN = 'unknown'


def _number(status: Dict[str, Any], key: str) -> Optional[float]:
    """
    A numeric field of a call status, or None when it is absent or not a
    number.

    Not every status carries every field: a call that timed out never
    reported resource usage, and one whose worker was killed reported
    nothing at all. A missing measurement is skipped, never recorded as a
    zero, because a zero is a real value that drags a histogram quantile
    down with it
    """
    value = status.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(
    status: Dict[str, Any], end_key: str, start_key: str
) -> Optional[float]:
    """
    The time between two timestamps of a call status, when both are there
    and the result makes sense. Clocks of a client and a worker are not
    the same clock, so a small negative delta is not an error, it is skew
    """
    end = _number(status, end_key)
    start = _number(status, start_key)
    if end is None or start is None:
        return None
    delta = end - start
    return delta if delta >= 0 else 0.0


class BoundTelemetry:
    """
    The exporter as one compute backend sees it.

    A :class:`TelemetryExporter` is process-wide, but ``backend`` is a
    label of every metric and belongs to the executor. Binding pins it
    once instead of threading it through every call site.
    """

    __slots__ = ('_exporter', '_backend')

    def __init__(self, exporter: 'TelemetryExporter', backend: str):
        self._exporter = exporter
        self._backend = backend or _UNKNOWN

    @property
    def enabled(self) -> bool:
        return True

    def _labels(self, source: Any, **extra: str) -> Dict[str, str]:
        """
        The label set of a job or a future. Both carry the same four
        attributes, which is why one function covers them
        """
        labels = {
            'backend': self._backend,
            'runtime_name': getattr(source, 'runtime_name', None) or _UNKNOWN,
            'runtime_memory': str(getattr(source, 'runtime_memory', None) or 0),
            'function_name': (
                getattr(source, 'function_name', None) or _UNKNOWN
            ),
        }
        labels.update(extra)
        return labels

    def on_job_submitted(self, job: Any) -> None:
        """
        Records a job on its way to the compute backend, and what the
        client spent getting it there.

        This is the only thing measured before a worker has run;
        everything else comes back with a call status
        """
        try:
            self._record_submitted(job)
        except Exception as exc:
            logger.debug(f'Telemetry: could not record the job: {exc}')

    def _record_submitted(self, job: Any) -> None:
        labels = self._labels(job)
        observe = self._exporter.observe

        observe(M.JOBS_SUBMITTED, 1, labels)
        observe(M.CALLS_INVOKED, job.total_calls, labels)
        observe(M.JOB_CALLS, job.total_calls, labels)

        # What the client spent partitioning, serialising and uploading.
        # Invisible until now: it happens before the first worker exists,
        # so no call status has ever carried it
        metadata = getattr(job, 'metadata', None) or {}
        for spec, key in (
            (M.JOB_CREATE_DURATION, 'host_job_created_time'),
            (M.JOB_SERIALIZE_DURATION, 'host_job_serialize_time'),
            (M.JOB_PARTITION_DURATION, 'host_job_create_partitions_time'),
        ):
            value = _number(metadata, key)
            if value is not None:
                observe(spec, value, labels)

        for part, duration_key, size_key in (
            ('function', 'host_func_upload_time', 'func_module_size_bytes'),
            ('data', 'host_data_upload_time', 'func_data_size_bytes'),
        ):
            duration = _number(metadata, duration_key)
            if duration is not None:
                observe(
                    M.JOB_UPLOAD_DURATION, duration, dict(labels, part=part)
                )
            size = _number(metadata, size_key)
            if size is not None:
                observe(
                    M.JOB_PAYLOAD_SIZE, size, dict(labels, part=part)
                )

    def on_call_started(self, future: Any, call_status: Dict[str, Any]) -> None:
        """
        Records a call the client has seen start.

        Not every call is seen starting: the storage sweep that recovers a
        lost status jumps straight to finished. Started and completed are
        therefore counted separately and never assumed to match
        """
        try:
            self._exporter.observe(M.CALLS_STARTED, 1, self._labels(future))
            if call_status.get('worker_cold_start'):
                self._exporter.observe(M.COLD_STARTS, 1, self._labels(future))
        except Exception as exc:
            logger.debug(f'Telemetry: could not record the call start: {exc}')

    def on_call_finished(
        self,
        future: Any,
        call_status: Dict[str, Any],
        outcome: Optional[str] = None,
    ) -> None:
        """
        Records a call that reached a final state, and everything the
        worker measured while it ran
        """
        try:
            self._record_finished(future, call_status or {}, outcome)
        except Exception as exc:
            # The caller is the monitor thread. Letting anything out of
            # here would take the thread down and hang every wait() of
            # the executor, so a metric that cannot be recorded is a
            # metric that is not recorded
            logger.debug(f'Telemetry: could not record the call: {exc}')

    def _record_finished(
        self,
        future: Any,
        status: Dict[str, Any],
        outcome: Optional[str],
    ) -> None:
        if outcome is None:
            outcome = (
                M.OUTCOME_FAILURE if status.get('exception')
                else M.OUTCOME_SUCCESS
            )

        labels = self._labels(future)
        observe = self._exporter.observe
        observe(M.CALLS_COMPLETED, 1, dict(labels, outcome=outcome))

        observations = (
            (M.CALL_DURATION, _delta(
                status, 'worker_func_end_tstamp', 'worker_func_start_tstamp'
            )),
            (M.CALL_TOTAL_DURATION, _delta(
                status, 'worker_end_tstamp', 'worker_start_tstamp'
            )),
            (M.CALL_QUEUE_DELAY, _delta(
                status, 'worker_start_tstamp', 'host_submit_tstamp'
            )),
            (M.CALL_WORKER_SETUP, _delta(
                status, 'worker_func_start_tstamp', 'worker_start_tstamp'
            )),
            (M.CALL_WORKER_TEARDOWN, _delta(
                status, 'worker_end_tstamp', 'worker_func_end_tstamp'
            )),
            (M.CALL_RESULT_SIZE, _number(status, 'func_result_size')),
            (M.CALL_RESULT_UPLOAD, _number(status, 'worker_result_upload_time')),
            (M.WORKER_CPU_UTILIZATION, _number(status, 'worker_func_cpu_usage')),
            # Kept by the client, not by the worker: how many times it had
            # to ask the storage backend before this call reported in
            (M.CALL_STATUS_QUERIES, getattr(future, '_status_query_count', None)),
        )
        for spec, value in observations:
            if value is not None:
                observe(spec, value, labels)

        # The monitoring channel is measured against the client clock, so
        # only the part of it the client timed is used
        status_done = getattr(future, '_host_status_done_tstamp', None)
        worker_end = _number(status, 'worker_end_tstamp')
        if status_done and worker_end:
            observe(
                M.CALL_STATUS_LATENCY, max(0.0, status_done - worker_end),
                labels
            )

        # Five readings of the same thing, and they answer different
        # questions. "peak" is the high water mark of the whole task, which
        # is what an out-of-memory kill is measured against; "baseline" is
        # that same mark before the function started, so the difference is
        # what the function itself cost on top of the runtime
        runtime_bytes = (
            float(getattr(future, 'runtime_memory', None) or 0) * 1024 * 1024
        )
        for kind, key in (
            ('rss', 'worker_func_rss'),
            ('vms', 'worker_func_vms'),
            ('uss', 'worker_func_uss'),
            ('peak', 'worker_peak_memory_end'),
            ('baseline', 'worker_peak_memory_start'),
        ):
            value = _number(status, key)
            if value is None:
                continue
            observe(M.WORKER_MEMORY, value, dict(labels, kind=kind))
            # Only the two that mean "how close was this to the limit"
            if runtime_bytes and kind in ('rss', 'peak'):
                observe(
                    M.WORKER_MEMORY_RATIO, value / runtime_bytes,
                    dict(labels, kind=kind),
                )

        for mode, key in (
            ('user', 'worker_func_cpu_user_time'),
            ('system', 'worker_func_cpu_system_time'),
        ):
            value = _number(status, key)
            if value is not None:
                observe(
                    M.WORKER_CPU_SECONDS, value, dict(labels, mode=mode)
                )

        for direction, key in (
            ('sent', 'worker_func_sent_net_io'),
            ('recv', 'worker_func_recv_net_io'),
        ):
            value = _number(status, key)
            if value is not None:
                observe(
                    M.WORKER_NETWORK_BYTES, value,
                    dict(labels, direction=direction),
                )

        # What the runtime is, rather than what it did. Carried by its own
        # metric so that none of the above has to grow a label for it
        observe(M.WORKER_INFO, 1, {
            'backend': self._backend,
            'runtime_name': getattr(future, 'runtime_name', None) or _UNKNOWN,
            'runtime_memory': str(
                getattr(future, 'runtime_memory', None) or 0
            ),
            'python_version': status.get('python_version') or _UNKNOWN,
            'lithops_version': __version__,
        })

    def on_result_read(self, future: Any, source: str) -> None:
        """
        Records the client getting hold of the result of a call.

        This is the one part of a call the monitor never sees: it happens
        in ``get_result()``, on whichever thread the user is on, long
        after the future went ready
        """
        try:
            self._record_result_read(future, source)
        except Exception as exc:
            logger.debug(f'Telemetry: could not record the result: {exc}')

    def _record_result_read(self, future: Any, source: str) -> None:
        stats = getattr(future, 'stats', None) or {}
        labels = self._labels(future)
        observe = self._exporter.observe

        done = _number(stats, 'host_result_done_tstamp')

        # From knowing the call was done to holding what it returned
        download = _delta(
            stats, 'host_result_done_tstamp', 'host_status_done_tstamp'
        )
        if download is not None:
            observe(
                M.CALL_RESULT_DOWNLOAD, download, dict(labels, source=source)
            )

        queries = _number(stats, 'host_result_query_count')
        if queries is not None:
            observe(M.CALL_RESULT_QUERIES, queries, labels)

        # The number the user actually feels: submit to result in hand
        submitted = _number(stats, 'host_submit_tstamp')
        if done is not None and submitted is not None:
            observe(M.CALL_END_TO_END, max(0.0, done - submitted), labels)

    def flush(self) -> None:
        """Pushes what has been recorded so far, out of band of the timer"""
        self._exporter.flush()


class NoopTelemetry(BoundTelemetry):
    """
    What every call site holds when telemetry is off: the same shape, and
    nothing behind it. Instrumenting a code path therefore costs an
    attribute lookup and a call that returns, with no ``if enabled``
    scattered around the monitor
    """

    __slots__ = ()

    def __init__(self):  # noqa: D107 - deliberately takes no exporter
        pass

    @property
    def enabled(self) -> bool:
        return False

    def on_job_submitted(self, job):
        pass

    def on_call_started(self, future, call_status):
        pass

    def on_call_finished(self, future, call_status, outcome=None):
        pass

    def on_result_read(self, future, source):
        pass

    def flush(self):
        pass


#: Shared instance. Immutable and stateless, so one is enough
NOOP = NoopTelemetry()


class TelemetryExporter:
    """
    Owns the metrics backend and the thread that flushes it.

    Built through :func:`get_exporter`, which keeps one per process.
    """

    def __init__(self, backend, flush_interval: float):
        self.backend = backend
        self.flush_interval = flush_interval
        self._stopped = threading.Event()
        self._shutdown_done = False
        self._shutdown_lock = threading.Lock()
        self._flusher = threading.Thread(
            target=self._flush_loop,
            name='lithops-telemetry-flush',
            daemon=True,
        )
        self._flusher.start()
        # A script that never closes its executor is the common case, and
        # the metrics of its last seconds are the ones worth having
        atexit.register(self.shutdown)

    def observe(
        self, spec: M.MetricSpec, value: float, labels: Dict[str, str]
    ) -> None:
        """
        Records one observation, after checking that the labels are the
        ones the spec declares.

        The check is what keeps the cardinality rules of
        :mod:`lithops.telemetry.metrics` true at runtime rather than only
        at import: a call site that invents a label is dropped and logged,
        not written to the backend
        """
        if set(labels) != set(spec.labelnames):
            logger.error(
                f'Telemetry: {spec.name} takes labels '
                f'{sorted(spec.labelnames)}, got {sorted(labels)}. '
                f'The observation was dropped'
            )
            return
        try:
            self.backend.observe(spec, value, labels)
        except Exception as exc:
            logger.debug(f'Telemetry: {spec.name} was not recorded: {exc}')

    def bind(self, compute_backend: str) -> BoundTelemetry:
        """The exporter as an executor on ``compute_backend`` sees it"""
        return BoundTelemetry(self, compute_backend)

    def flush(self) -> None:
        try:
            self.backend.flush()
        except Exception as exc:
            logger.warning(f'Telemetry: could not flush the metrics: {exc}')

    def _flush_loop(self) -> None:
        while not self._stopped.wait(self.flush_interval):
            self.flush()

    def shutdown(self) -> None:
        """
        Flushes one last time and releases the backend. Idempotent, and
        best effort: it runs from atexit, where the interpreter may
        already be tearing the modules the HTTP client needs down
        """
        with self._shutdown_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True

        self._stopped.set()
        try:
            self.backend.flush()
            self.backend.shutdown()
        except Exception as exc:
            logger.debug(f'Telemetry: shutdown was incomplete: {exc}')


# ---------------------------------------------------------------------------
# The process-wide instance
# ---------------------------------------------------------------------------

_exporter: Optional[TelemetryExporter] = None
_exporter_backend: Optional[str] = None
_exporter_lock = threading.Lock()


def default_instance_id() -> str:
    """
    Identity a backend labels this process with when the configuration
    does not name one.

    The hostname, deliberately: it is stable across runs, which keeps the
    number of series a backend holds bounded by the number of machines
    running Lithops rather than growing with every execution
    """
    return os.environ.get('LITHOPS_TELEMETRY_INSTANCE') or socket.gethostname()


def get_telemetry(
    config: Optional[Dict[str, Any]],
    compute_backend: Optional[str] = None,
) -> BoundTelemetry:
    """
    The telemetry handle for an executor, or :data:`NOOP` when telemetry
    is off or its backend cannot be loaded.

    Never raises. A metrics system that is misconfigured or unreachable
    is a metrics system that is not used, not a job that does not run.
    """
    backend_name = resolve_backend(config)
    if backend_name is None:
        return NOOP

    if 'LITHOPS_WORKER' in os.environ:
        # Metrics are a client concern, and a worker gets the client's
        # whole config. Without this, every worker would try to reach a
        # metrics system it most likely has no route to. The remote
        # invoker sets the same variable before it builds its JobMonitor,
        # so it is covered too
        return NOOP

    try:
        exporter = _get_exporter(config, backend_name)
    except Exception as exc:
        logger.error(
            f"Telemetry is disabled: the '{backend_name}' backend could "
            f"not be initialised: {exc}"
        )
        return NOOP

    return exporter.bind(
        compute_backend or (config.get('lithops') or {}).get('backend')
    )


def _get_exporter(
    config: Dict[str, Any], backend_name: str
) -> TelemetryExporter:
    global _exporter, _exporter_backend

    with _exporter_lock:
        if _exporter is not None:
            if _exporter_backend != backend_name:
                logger.warning(
                    f"Telemetry was already started with the "
                    f"'{_exporter_backend}' backend; '{backend_name}' is "
                    f"ignored. One process exports through one backend"
                )
            return _exporter

        backend_cls = load_backend_class(backend_name)
        section = config.get(backend_name) or {}
        interval = float(
            (config.get('lithops') or {}).get(
                'telemetry_interval', DEFAULT_FLUSH_INTERVAL
            )
        )
        _exporter = TelemetryExporter(backend_cls(section), interval)
        _exporter_backend = backend_name
        logger.debug(
            f'Telemetry enabled: {backend_name} backend, flushing every '
            f'{interval}s'
        )
        return _exporter


def current_telemetry(compute_backend: Optional[str] = None) -> BoundTelemetry:
    """
    The telemetry of this process, for a caller that has no configuration
    to hand -- a :class:`~lithops.future.ResponseFuture` reading its
    result, which knows which backend it ran on and nothing else.

    Returns :data:`NOOP` unless :func:`get_telemetry` has already started
    an exporter, so this never switches telemetry on by itself and never
    reads the configuration a second time.
    """
    exporter = _exporter
    if exporter is None:
        return NOOP
    return exporter.bind(compute_backend)


def shutdown_telemetry() -> None:
    """
    Stops the exporter of this process, if there is one. Only the tests
    and a process that wants a deterministic final push need this;
    everything else is covered by the atexit hook
    """
    global _exporter, _exporter_backend

    with _exporter_lock:
        exporter, _exporter, _exporter_backend = _exporter, None, None

    if exporter is not None:
        exporter.shutdown()


def load_backend_config(config_data: Dict[str, Any]) -> None:
    """
    Lets the configured telemetry backend fill in its own defaults, the
    way the monitoring backends do. A no-op when telemetry is off
    """
    backend_name = resolve_backend(config_data)
    if backend_name is None:
        return
    logger.debug(f'Loading Telemetry backend module: {backend_name}')
    module = import_backend_module(backend_name, 'config')
    module.load_config(config_data)
