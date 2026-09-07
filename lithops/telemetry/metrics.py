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
The metrics Lithops exports, declared once and materialised by whichever
telemetry backend is configured.

A metric is a :class:`MetricSpec`: a name, a kind, the labels it carries
and, for histograms, its bucket boundaries. Backends turn a spec into
their own instrument the first time they see it, so adding a metric is
adding a spec here and nothing else.

Cardinality is the reason this file exists. Every distinct combination of
label values is a separate time series, and Lithops runs jobs of tens of
thousands of calls: a ``call_id`` label would mean a series per call, for
ever. The label set of every metric is therefore bounded by properties of
the *job* -- never of the call -- and :data:`FORBIDDEN_LABELS` makes a
spec that breaks the rule fail at import rather than in production.

Per-call detail is not lost, it is simply not a metric: it lives in the
call status, which the client already keeps.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple

#: Kinds of instrument a backend has to support
COUNTER = 'counter'
HISTOGRAM = 'histogram'
UPDOWN = 'updown'
GAUGE = 'gauge'

_KINDS = (COUNTER, HISTOGRAM, UPDOWN, GAUGE)

#: Labels every metric carries. All of them are properties of the job, so
#: the number of series a backend holds is bounded by how many distinct
#: functions and runtimes are executed, not by how many calls are made
BASE_LABELS: Tuple[str, ...] = (
    'backend',
    'runtime_name',
    'runtime_memory',
    'function_name',
)

#: The labels an info metric carries. It says what a runtime *is*, so
#: the function that happened to run on it is not part of its identity,
#: and leaving it out keeps one series per runtime rather than one per
#: (runtime, function) pair
RUNTIME_LABELS: Tuple[str, ...] = (
    'backend',
    'runtime_name',
    'runtime_memory',
)

#: Labels that identify a single call or a single job. Attaching one of
#: these to a metric turns a bounded series into an unbounded one, which
#: is the failure mode this whole module is shaped to prevent
FORBIDDEN_LABELS = frozenset({
    'call_id',
    'job_id',
    'job_key',
    'executor_id',
    'activation_id',
    'worker_id',
    'instance_id',
})


@dataclass(frozen=True)
class MetricSpec:
    """
    One exported metric.

    ``name`` is used verbatim by every backend, so that a dashboard
    written against one keeps working against another. Counters are named
    without the ``_total`` suffix: both Prometheus and OpenTelemetry add
    it themselves when they render the metric.
    """

    name: str
    kind: str
    documentation: str
    unit: str = ''
    base_labels: Tuple[str, ...] = BASE_LABELS
    extra_labels: Tuple[str, ...] = ()
    buckets: Optional[Tuple[float, ...]] = None
    labelnames: Tuple[str, ...] = field(init=False)

    def __post_init__(self):
        if self.kind not in _KINDS:
            raise ValueError(
                f"{self.name}: unknown metric kind '{self.kind}'"
            )
        if self.kind == HISTOGRAM and not self.buckets:
            raise ValueError(f'{self.name}: a histogram needs buckets')
        if self.kind != HISTOGRAM and self.buckets:
            raise ValueError(f'{self.name}: only a histogram takes buckets')

        labelnames = tuple(self.base_labels) + tuple(self.extra_labels)
        forbidden = FORBIDDEN_LABELS.intersection(labelnames)
        if forbidden:
            raise ValueError(
                f"{self.name}: {', '.join(sorted(forbidden))} identifies a "
                f"single call or job. A label like that gives the metric one "
                f"time series per call, which no time series database "
                f"survives. Per-call detail belongs in the call status"
            )
        # frozen=True, so the derived field is set the long way round
        object.__setattr__(self, 'labelnames', labelnames)


# ---------------------------------------------------------------------------
# Bucket boundaries
#
# Chosen so that the interesting part of each distribution falls in the
# middle of the range: a serverless call is a few hundred milliseconds to a
# few minutes, a cold start a few seconds, a result a few kilobytes
# ---------------------------------------------------------------------------

DURATION_BUCKETS = (
    0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800
)

DELAY_BUCKETS = (
    0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300
)

SIZE_BUCKETS = (
    1024, 8192, 65536, 524288, 1048576, 8388608, 67108864, 536870912
)

MEMORY_BUCKETS = (
    16777216, 67108864, 134217728, 268435456, 536870912,
    1073741824, 2147483648, 4294967296, 8589934592
)

#: A ratio over 1 means the function used more than the memory the runtime
#: was configured with, which is worth seeing rather than clamping away
RATIO_BUCKETS = (0.1, 0.25, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0, 1.25)

PERCENT_BUCKETS = (1, 5, 10, 25, 50, 75, 90, 95, 99, 100)

#: For the client side of a job: serialising, uploading, and the storage
#: round trips the monitor makes. All of it is fractions of a second to a
#: few seconds when it is healthy
OVERHEAD_BUCKETS = (
    0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60
)

#: Counts of storage requests per call. A well behaved monitoring channel
#: needs one or two; the long tail is what a rate limited poll looks like
COUNT_BUCKETS = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)

#: Sizes of a job rather than of a result: the serialised function is
#: kilobytes, the data can be anything
JOB_SIZE_BUCKETS = (
    1024, 16384, 131072, 1048576, 8388608, 67108864, 536870912, 4294967296
)

#: How many calls a job is made of
JOB_CALLS_BUCKETS = (1, 5, 10, 50, 100, 500, 1000, 5000, 10000, 50000)


# ---------------------------------------------------------------------------
# The inventory
# ---------------------------------------------------------------------------

JOBS_SUBMITTED = MetricSpec(
    name='lithops_jobs_submitted',
    kind=COUNTER,
    documentation='Jobs submitted for execution',
)

CALLS_INVOKED = MetricSpec(
    name='lithops_calls_invoked',
    kind=COUNTER,
    documentation='Function calls handed to the compute backend',
)

CALLS_STARTED = MetricSpec(
    name='lithops_calls_started',
    kind=COUNTER,
    documentation='Function calls the client has seen start running',
)

CALLS_COMPLETED = MetricSpec(
    name='lithops_calls_completed',
    kind=COUNTER,
    documentation=(
        'Function calls that reached a final state. The outcome label is '
        'one of success, failure, timeout or chained'
    ),
    extra_labels=('outcome',),
)

COLD_STARTS = MetricSpec(
    name='lithops_cold_starts',
    kind=COUNTER,
    documentation='Function calls that ran in a cold worker',
)

WORKER_CPU_SECONDS = MetricSpec(
    name='lithops_worker_cpu_seconds',
    kind=COUNTER,
    documentation='CPU time consumed by the function, by mode (user, system)',
    unit='seconds',
    extra_labels=('mode',),
)

WORKER_NETWORK_BYTES = MetricSpec(
    name='lithops_worker_network_bytes',
    kind=COUNTER,
    documentation='Network traffic of the function, by direction (sent, recv)',
    unit='bytes',
    extra_labels=('direction',),
)

CALL_DURATION = MetricSpec(
    name='lithops_call_duration_seconds',
    kind=HISTOGRAM,
    documentation='Wall clock time spent inside the user function',
    unit='seconds',
    buckets=DURATION_BUCKETS,
)

CALL_TOTAL_DURATION = MetricSpec(
    name='lithops_call_total_duration_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Wall clock time the worker spent on the call, including the '
        'Lithops overhead around the user function'
    ),
    unit='seconds',
    buckets=DURATION_BUCKETS,
)

CALL_QUEUE_DELAY = MetricSpec(
    name='lithops_call_queue_delay_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time between the client submitting the call and the worker '
        'starting it. This is the scheduling latency of the backend'
    ),
    unit='seconds',
    buckets=DELAY_BUCKETS,
)

CALL_STATUS_LATENCY = MetricSpec(
    name='lithops_call_status_latency_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time between the worker finishing the call and the client '
        'learning about it. This is the latency of the monitoring channel'
    ),
    unit='seconds',
    buckets=DELAY_BUCKETS,
)

CALL_RESULT_SIZE = MetricSpec(
    name='lithops_call_result_size_bytes',
    kind=HISTOGRAM,
    documentation='Size of the value the function returned',
    unit='bytes',
    buckets=SIZE_BUCKETS,
)

WORKER_MEMORY = MetricSpec(
    name='lithops_worker_memory_bytes',
    kind=HISTOGRAM,
    documentation=(
        'Memory of the worker, by kind. "peak" is the high water mark of '
        'the whole task and is what an out-of-memory kill is measured '
        'against; "baseline" is the same reading taken before the function '
        'started, which is what the runtime itself costs. "rss", "vms" and '
        '"uss" are sampled once, as the function returns'
    ),
    unit='bytes',
    extra_labels=('kind',),
    buckets=MEMORY_BUCKETS,
)

WORKER_MEMORY_RATIO = MetricSpec(
    name='lithops_worker_memory_utilization_ratio',
    kind=HISTOGRAM,
    documentation=(
        'Memory of the worker over the memory the runtime was configured '
        'with, by kind. Values close to 1 are calls about to be killed; '
        'values close to 0 are memory paid for and not used. The "peak" '
        'kind is the one to size a runtime by'
    ),
    extra_labels=('kind',),
    buckets=RATIO_BUCKETS,
)

CALL_RESULT_UPLOAD = MetricSpec(
    name='lithops_call_result_upload_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time the worker spent writing the result to the storage backend. '
        'Zero for a result small enough to travel in the call status'
    ),
    unit='seconds',
    buckets=OVERHEAD_BUCKETS,
)

CALL_WORKER_SETUP = MetricSpec(
    name='lithops_call_worker_setup_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time the worker spent between starting and entering the user '
        'function: unpacking the job, importing the modules and fetching '
        'the data'
    ),
    unit='seconds',
    buckets=OVERHEAD_BUCKETS,
)

CALL_WORKER_TEARDOWN = MetricSpec(
    name='lithops_call_worker_teardown_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time the worker spent after the user function returned: writing '
        'the result and reporting the status'
    ),
    unit='seconds',
    buckets=OVERHEAD_BUCKETS,
)

CALL_RESULT_DOWNLOAD = MetricSpec(
    name='lithops_call_result_download_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time the client spent getting the result of a call once it knew '
        'the call was done, by source. "inline" is a result small enough to '
        'have travelled in the call status, so it costs no request at all; '
        '"storage" is one that had to be fetched'
    ),
    unit='seconds',
    extra_labels=('source',),
    buckets=OVERHEAD_BUCKETS,
)

CALL_RESULT_QUERIES = MetricSpec(
    name='lithops_call_result_queries',
    kind=HISTOGRAM,
    documentation=(
        'Storage requests the client made to get the result of one call. '
        'Zero for a result that travelled in the call status'
    ),
    buckets=COUNT_BUCKETS,
)

CALL_END_TO_END = MetricSpec(
    name='lithops_call_end_to_end_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time from the client submitting a call to the client holding its '
        'result. Everything else is a part of this one'
    ),
    unit='seconds',
    buckets=DURATION_BUCKETS,
)

CALL_STATUS_QUERIES = MetricSpec(
    name='lithops_call_status_queries',
    kind=HISTOGRAM,
    documentation=(
        'Storage requests the client made to learn the status of one call. '
        'This is what the monitoring channel costs against the storage '
        'backend, and it is zero for the channels that push'
    ),
    buckets=COUNT_BUCKETS,
)

WORKER_CPU_UTILIZATION = MetricSpec(
    name='lithops_worker_cpu_utilization_percent',
    kind=HISTOGRAM,
    documentation='CPU utilisation of the worker while the function ran',
    unit='percent',
    buckets=PERCENT_BUCKETS,
)

JOB_CALLS = MetricSpec(
    name='lithops_job_calls',
    kind=HISTOGRAM,
    documentation='How many calls a job is made of',
    buckets=JOB_CALLS_BUCKETS,
)

JOB_CREATE_DURATION = MetricSpec(
    name='lithops_job_create_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time the client spent preparing the job before the first worker '
        'was invoked: partitioning, serialising and uploading'
    ),
    unit='seconds',
    buckets=OVERHEAD_BUCKETS,
)

JOB_SERIALIZE_DURATION = MetricSpec(
    name='lithops_job_serialize_seconds',
    kind=HISTOGRAM,
    documentation='Time the client spent serialising the function and its data',
    unit='seconds',
    buckets=OVERHEAD_BUCKETS,
)

JOB_PARTITION_DURATION = MetricSpec(
    name='lithops_job_partition_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time the client spent partitioning the input data, for a job that '
        'processes objects'
    ),
    unit='seconds',
    buckets=OVERHEAD_BUCKETS,
)

JOB_UPLOAD_DURATION = MetricSpec(
    name='lithops_job_upload_seconds',
    kind=HISTOGRAM,
    documentation=(
        'Time the client spent uploading the job to the storage backend, by '
        'part (function, data). Zero for a function already in the cache'
    ),
    unit='seconds',
    extra_labels=('part',),
    buckets=OVERHEAD_BUCKETS,
)

JOB_PAYLOAD_SIZE = MetricSpec(
    name='lithops_job_payload_bytes',
    kind=HISTOGRAM,
    documentation=(
        'Size of what the client uploaded for the job, by part (function, '
        'data)'
    ),
    unit='bytes',
    extra_labels=('part',),
    buckets=JOB_SIZE_BUCKETS,
)

WORKER_INFO = MetricSpec(
    name='lithops_worker_info',
    kind=GAUGE,
    documentation=(
        'Always 1. Carries the properties of the execution environment as '
        'labels, so that a dashboard can show what a runtime actually is '
        'without any of them having to be a label of every other metric'
    ),
    base_labels=RUNTIME_LABELS,
    extra_labels=('python_version', 'lithops_version'),
)

#: Every spec, which is what a backend needs in order to declare its
#: instruments (OpenTelemetry views, for one, have to be registered before
#: the meter is built)
ALL_METRICS: Tuple[MetricSpec, ...] = (
    JOBS_SUBMITTED,
    CALLS_INVOKED,
    CALLS_STARTED,
    CALLS_COMPLETED,
    COLD_STARTS,
    WORKER_CPU_SECONDS,
    WORKER_NETWORK_BYTES,
    CALL_DURATION,
    CALL_TOTAL_DURATION,
    CALL_QUEUE_DELAY,
    CALL_STATUS_LATENCY,
    CALL_WORKER_SETUP,
    CALL_WORKER_TEARDOWN,
    CALL_RESULT_SIZE,
    CALL_RESULT_UPLOAD,
    CALL_RESULT_DOWNLOAD,
    CALL_RESULT_QUERIES,
    CALL_END_TO_END,
    CALL_STATUS_QUERIES,
    WORKER_MEMORY,
    WORKER_MEMORY_RATIO,
    WORKER_CPU_UTILIZATION,
    WORKER_INFO,
    JOB_CALLS,
    JOB_CREATE_DURATION,
    JOB_SERIALIZE_DURATION,
    JOB_PARTITION_DURATION,
    JOB_UPLOAD_DURATION,
    JOB_PAYLOAD_SIZE,
)


# ---------------------------------------------------------------------------
# Outcomes of a call, the only per-call dimension that is safe to label
# ---------------------------------------------------------------------------

#: Where the client read the result of a call from
SOURCE_INLINE = 'inline'
SOURCE_STORAGE = 'storage'

OUTCOME_SUCCESS = 'success'
OUTCOME_FAILURE = 'failure'
OUTCOME_TIMEOUT = 'timeout'
OUTCOME_CHAINED = 'chained'
