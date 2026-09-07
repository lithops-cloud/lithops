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

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lithops.telemetry import metrics as M
from lithops.telemetry.backend import MetricsBackend
from lithops.telemetry.backends import DEFAULT_BACKEND, resolve_backend
from lithops.telemetry.exporter import (
    NOOP,
    BoundTelemetry,
    TelemetryExporter,
    get_telemetry,
    shutdown_telemetry,
)
from lithops.monitoring.monitor import Monitor


class RecordingBackend(MetricsBackend):
    """A backend that keeps every observation instead of shipping it"""

    backend_name = 'recording'

    def __init__(self, config=None):
        super().__init__(config or {})
        self.observations = []
        self.flushes = 0
        self.shutdowns = 0

    def _create_instrument(self, spec):
        return spec.name

    def observe(self, spec, value, labels):
        self.observations.append((spec.name, value, dict(labels)))

    def flush(self):
        self.flushes += 1

    def shutdown(self):
        self.shutdowns += 1

    def values(self, spec):
        return [v for name, v, _ in self.observations if name == spec.name]

    def names(self):
        return [name for name, _, _ in self.observations]


@pytest.fixture
def recorder():
    """
    A bound telemetry writing into a RecordingBackend, with the flush
    thread wound all the way down before the test ends
    """
    backend = RecordingBackend()
    exporter = TelemetryExporter(backend, flush_interval=3600)
    try:
        yield exporter.bind('aws_lambda'), backend
    finally:
        exporter.shutdown()


@pytest.fixture(autouse=True)
def no_process_exporter():
    """
    The exporter is a process-wide singleton, so a test that builds one
    would otherwise hand it to every test that runs afterwards
    """
    shutdown_telemetry()
    yield
    shutdown_telemetry()


def _future(**attrs):
    defaults = dict(
        function_name='my_func',
        runtime_name='python:3.11',
        runtime_memory=512,
        _host_status_done_tstamp=None,
        _status_query_count=3,
    )
    defaults.update(attrs)
    return SimpleNamespace(**defaults)


def _call_status(**attrs):
    """A call status with everything a healthy worker reports"""
    status = {
        'exception': False,
        'worker_cold_start': True,
        'host_submit_tstamp': 1000.0,
        'worker_start_tstamp': 1002.0,
        'worker_func_start_tstamp': 1002.5,
        'worker_func_end_tstamp': 1007.5,
        'worker_end_tstamp': 1008.0,
        'func_result_size': 4096,
        'worker_result_upload_time': 0.12,
        'python_version': '3.11',
        'worker_func_rss': 268435456,
        'worker_func_vms': 900000000,
        'worker_func_uss': 200000000,
        'worker_peak_memory_start': 90000000,
        'worker_peak_memory_end': 402653184,
        'worker_func_cpu_usage': 42.5,
        'worker_func_cpu_user_time': 4.0,
        'worker_func_cpu_system_time': 0.5,
        'worker_func_sent_net_io': 1024,
        'worker_func_recv_net_io': 2048,
    }
    status.update(attrs)
    return status


def _job(**attrs):
    defaults = dict(
        total_calls=120,
        function_name='my_func',
        runtime_name='python:3.11',
        runtime_memory=512,
        metadata={
            'host_job_created_time': 1.8,
            'host_job_serialize_time': 0.4,
            'host_job_create_partitions_time': 0.05,
            'host_func_upload_time': 0.3,
            'func_module_size_bytes': 82000,
            'host_data_upload_time': 0.9,
            'func_data_size_bytes': 5500000,
        },
    )
    defaults.update(attrs)
    return SimpleNamespace(**defaults)


class TestMetricSpecs:

    def test_a_per_call_label_is_refused(self):
        with pytest.raises(ValueError, match='call_id'):
            M.MetricSpec(
                name='lithops_bad', kind=M.COUNTER,
                documentation='', extra_labels=('call_id',),
            )

    def test_a_histogram_needs_buckets(self):
        with pytest.raises(ValueError, match='buckets'):
            M.MetricSpec(
                name='lithops_bad', kind=M.HISTOGRAM, documentation=''
            )

    def test_only_a_histogram_takes_buckets(self):
        with pytest.raises(ValueError, match='histogram'):
            M.MetricSpec(
                name='lithops_bad', kind=M.COUNTER,
                documentation='', buckets=(1, 2),
            )

    def test_no_exported_metric_is_identified_by_a_call(self):
        for spec in M.ALL_METRICS:
            assert not M.FORBIDDEN_LABELS.intersection(spec.labelnames)

    def test_metric_names_are_unique(self):
        names = [spec.name for spec in M.ALL_METRICS]
        assert len(names) == len(set(names))


class TestResolveBackend:

    @pytest.mark.parametrize('value', [None, False, '', 'false', 'no', 'off'])
    def test_disabled_values(self, value):
        assert resolve_backend({'lithops': {'telemetry': value}}) is None

    @pytest.mark.parametrize('value', [True, 'true', 'YES', '1'])
    def test_enabled_without_a_backend_picks_the_default(self, value):
        config = {'lithops': {'telemetry': value}}
        assert resolve_backend(config) == DEFAULT_BACKEND

    def test_a_named_backend_wins(self):
        assert resolve_backend({'lithops': {'telemetry': 'OTLP'}}) == 'otlp'

    def test_the_argument_wins_over_the_config(self):
        config = {'lithops': {'telemetry': 'prometheus'}}
        assert resolve_backend(config, 'otlp') == 'otlp'

    def test_missing_section(self):
        assert resolve_backend({}) is None
        assert resolve_backend(None) is None


class TestRecordingACall:

    def test_a_finished_call_records_every_measurement(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(_future(), _call_status())

        assert backend.values(M.CALL_DURATION) == [5.0]
        assert backend.values(M.CALL_TOTAL_DURATION) == [6.0]
        assert backend.values(M.CALL_QUEUE_DELAY) == [2.0]
        assert backend.values(M.CALL_WORKER_SETUP) == [0.5]
        assert backend.values(M.CALL_WORKER_TEARDOWN) == [0.5]
        assert backend.values(M.CALL_RESULT_SIZE) == [4096]
        assert backend.values(M.WORKER_CPU_UTILIZATION) == [42.5]
        assert backend.values(M.CALL_RESULT_UPLOAD) == [0.12]
        assert backend.values(M.CALL_STATUS_QUERIES) == [3]
        assert sorted(backend.values(M.WORKER_CPU_SECONDS)) == [0.5, 4.0]
        assert sorted(backend.values(M.WORKER_NETWORK_BYTES)) == [1024, 2048]

    def test_the_labels_are_the_job_not_the_call(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(_future(), _call_status())

        for name, _, labels in backend.observations:
            assert labels['backend'] == 'aws_lambda'
            assert labels['runtime_name'] == 'python:3.11'
            assert labels['runtime_memory'] == '512'
            assert not M.FORBIDDEN_LABELS.intersection(labels)
            if name == M.WORKER_INFO.name:
                # Says what a runtime is, not what ran on it
                assert 'function_name' not in labels
            else:
                assert labels['function_name'] == 'my_func'

    def test_cpu_and_network_carry_their_own_dimension(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(_future(), _call_status())

        modes = {
            labels['mode']
            for name, _, labels in backend.observations
            if name == M.WORKER_CPU_SECONDS.name
        }
        directions = {
            labels['direction']
            for name, _, labels in backend.observations
            if name == M.WORKER_NETWORK_BYTES.name
        }
        assert modes == {'user', 'system'}
        assert directions == {'sent', 'recv'}

    def test_a_successful_call_is_counted_as_such(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(_future(), _call_status())

        outcomes = [
            labels['outcome'] for name, _, labels in backend.observations
            if name == M.CALLS_COMPLETED.name
        ]
        assert outcomes == [M.OUTCOME_SUCCESS]

    def test_a_failed_call_is_counted_as_such(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(_future(), _call_status(exception=True))

        outcomes = [
            labels['outcome'] for name, _, labels in backend.observations
            if name == M.CALLS_COMPLETED.name
        ]
        assert outcomes == [M.OUTCOME_FAILURE]

    def test_an_explicit_outcome_wins(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(
            _future(), _call_status(exception=True), M.OUTCOME_TIMEOUT
        )

        outcomes = [
            labels['outcome'] for name, _, labels in backend.observations
            if name == M.CALLS_COMPLETED.name
        ]
        assert outcomes == [M.OUTCOME_TIMEOUT]

    def test_the_monitoring_latency_is_measured_against_the_client_clock(
        self, recorder
    ):
        telemetry, backend = recorder
        future = _future(_host_status_done_tstamp=1008.75)
        telemetry.on_call_finished(future, _call_status())

        assert backend.values(M.CALL_STATUS_LATENCY) == [0.75]

    def test_a_started_call_is_counted_once(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_started(_future(), _call_status())

        assert backend.values(M.CALLS_STARTED) == [1]

    def test_a_cold_start_is_counted_when_the_call_finishes(self, recorder):
        # Not when it starts: the status that says a call is running is
        # synthesised by the storage backend from a listing, and carries
        # nothing the worker measured
        telemetry, backend = recorder
        telemetry.on_call_started(_future(), _call_status())

        assert backend.values(M.COLD_STARTS) == []

        telemetry.on_call_finished(_future(), _call_status())

        assert backend.values(M.COLD_STARTS) == [1]

    def test_a_warm_call_is_not_a_cold_start(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(
            _future(), _call_status(worker_cold_start=False)
        )

        assert backend.values(M.CALLS_COMPLETED) == [1]
        assert backend.values(M.COLD_STARTS) == []

    def test_the_cpu_usage_of_every_core_is_averaged(self, recorder):
        # psutil reports one figure per core, and the metric holds one
        telemetry, backend = recorder
        telemetry.on_call_finished(
            _future(), _call_status(
                worker_func_cpu_usage=[10.0, 30.0, 50.0, 10.0]
            )
        )

        assert backend.values(M.WORKER_CPU_UTILIZATION) == [25.0]

    def test_a_worker_that_reports_no_cpu_usage_is_skipped(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(
            _future(), _call_status(worker_func_cpu_usage=[])
        )

        assert backend.values(M.WORKER_CPU_UTILIZATION) == []

    def test_a_job_records_its_size(self, recorder):
        telemetry, backend = recorder
        telemetry.on_job_submitted(_job())

        assert backend.values(M.JOBS_SUBMITTED) == [1]
        assert backend.values(M.CALLS_INVOKED) == [120]
        assert backend.values(M.JOB_CALLS) == [120]

    def test_a_job_records_what_the_client_spent_preparing_it(self, recorder):
        telemetry, backend = recorder
        telemetry.on_job_submitted(_job())

        assert backend.values(M.JOB_CREATE_DURATION) == [1.8]
        assert backend.values(M.JOB_SERIALIZE_DURATION) == [0.4]
        assert backend.values(M.JOB_PARTITION_DURATION) == [0.05]

        uploads = {
            labels['part']: value
            for name, value, labels in backend.observations
            if name == M.JOB_UPLOAD_DURATION.name
        }
        payloads = {
            labels['part']: value
            for name, value, labels in backend.observations
            if name == M.JOB_PAYLOAD_SIZE.name
        }
        assert uploads == {'function': 0.3, 'data': 0.9}
        assert payloads == {'function': 82000, 'data': 5500000}

    def test_a_job_without_metadata_still_records_its_size(self, recorder):
        telemetry, backend = recorder
        job = SimpleNamespace(
            total_calls=7, function_name='my_func',
            runtime_name='python:3.11', runtime_memory=512,
        )
        telemetry.on_job_submitted(job)

        assert backend.values(M.CALLS_INVOKED) == [7]
        assert backend.values(M.JOB_CREATE_DURATION) == []


class TestMemoryAndEnvironment:

    def _by_kind(self, backend, spec):
        return {
            labels['kind']: value
            for name, value, labels in backend.observations
            if name == spec.name
        }

    def test_every_reading_of_the_memory_is_recorded(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(_future(), _call_status())

        assert self._by_kind(backend, M.WORKER_MEMORY) == {
            'rss': 268435456,
            'vms': 900000000,
            'uss': 200000000,
            'peak': 402653184,
            'baseline': 90000000,
        }

    def test_only_the_readings_that_mean_a_limit_get_a_ratio(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(_future(), _call_status())

        # 512MB runtime: 256MB resident, 384MB peak
        assert self._by_kind(backend, M.WORKER_MEMORY_RATIO) == {
            'rss': 0.5, 'peak': 0.75
        }

    def test_a_worker_that_reports_no_peak_still_reports_the_rest(
        self, recorder
    ):
        # peak_memory() returns None on a worker that is not Unix
        telemetry, backend = recorder
        status = _call_status()
        del status['worker_peak_memory_start']
        del status['worker_peak_memory_end']
        telemetry.on_call_finished(_future(), status)

        kinds = self._by_kind(backend, M.WORKER_MEMORY)
        assert set(kinds) == {'rss', 'vms', 'uss'}
        assert set(self._by_kind(backend, M.WORKER_MEMORY_RATIO)) == {'rss'}

    def test_the_environment_is_reported_once_per_call(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(_future(), _call_status())

        info = [
            labels for name, _, labels in backend.observations
            if name == M.WORKER_INFO.name
        ]
        assert len(info) == 1
        assert info[0]['python_version'] == '3.11'
        assert info[0]['lithops_version']
        assert 'function_name' not in info[0]

    def test_an_unknown_python_version_is_still_reported(self, recorder):
        telemetry, backend = recorder
        status = _call_status()
        del status['python_version']
        telemetry.on_call_finished(_future(), status)

        info = [
            labels for name, _, labels in backend.observations
            if name == M.WORKER_INFO.name
        ]
        assert info[0]['python_version'] == 'unknown'


class TestIncompleteStatuses:

    def test_a_timed_out_call_records_what_little_it_has(self, recorder):
        telemetry, backend = recorder
        # What the timeout checker of the monitor synthesises: no resource
        # usage, and no timestamps from inside the function
        status = {
            'type': '__end__', 'exception': True,
            'worker_start_tstamp': 1002.0, 'worker_end_tstamp': 1032.0,
        }
        telemetry.on_call_finished(_future(), status, M.OUTCOME_TIMEOUT)

        assert backend.values(M.CALL_TOTAL_DURATION) == [30.0]
        assert backend.values(M.CALLS_COMPLETED) == [1]

    def test_a_missing_measurement_is_skipped_not_zeroed(self, recorder):
        telemetry, backend = recorder
        status = _call_status()
        for key in ('worker_func_rss', 'worker_func_vms', 'worker_func_uss',
                    'worker_peak_memory_start', 'worker_peak_memory_end',
                    'worker_func_end_tstamp'):
            del status[key]
        telemetry.on_call_finished(_future(), status)

        assert backend.values(M.WORKER_MEMORY) == []
        assert backend.values(M.WORKER_MEMORY_RATIO) == []
        assert backend.values(M.CALL_DURATION) == []
        # The measurements that are there are still recorded
        assert backend.values(M.CALL_QUEUE_DELAY) == [2.0]

    def test_an_empty_status_records_the_outcome_and_the_environment(
        self, recorder
    ):
        telemetry, backend = recorder
        telemetry.on_call_finished(
            _future(_status_query_count=None), {}
        )

        assert backend.names() == [
            M.CALLS_COMPLETED.name, M.WORKER_INFO.name
        ]

    def test_a_runtime_without_a_memory_size_has_no_ratio(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(_future(runtime_memory=None), _call_status())

        assert backend.values(M.WORKER_MEMORY)
        assert backend.values(M.WORKER_MEMORY_RATIO) == []

    def test_clock_skew_does_not_produce_a_negative_duration(self, recorder):
        telemetry, backend = recorder
        # The worker clock is a fraction ahead of the client clock
        telemetry.on_call_finished(
            _future(), _call_status(worker_start_tstamp=999.9)
        )

        assert backend.values(M.CALL_QUEUE_DELAY) == [0.0]

    def test_a_non_numeric_measurement_is_ignored(self, recorder):
        telemetry, backend = recorder
        telemetry.on_call_finished(
            _future(), _call_status(func_result_size='big')
        )

        assert backend.values(M.CALL_RESULT_SIZE) == []


class TestReadingTheResult:
    """
    The one part of a call the monitor never sees: it happens in
    get_result(), long after the future went ready
    """

    # The timestamps are halves so that every delta below is exact in
    # binary and can be compared with ==, as the rest of the file does
    def _read(self, telemetry, *, submitted=1000.0, status_done=1008.0,
              done=1008.5, queries=2, source=M.SOURCE_STORAGE):
        future = _future()
        future.stats = {
            'host_submit_tstamp': submitted,
            'host_status_done_tstamp': status_done,
            'host_result_done_tstamp': done,
            'host_result_query_count': queries,
        }
        telemetry.on_result_read(future, source)
        return future

    def test_the_download_and_the_end_to_end_are_recorded(self, recorder):
        telemetry, backend = recorder
        self._read(telemetry)

        assert backend.values(M.CALL_RESULT_DOWNLOAD) == [0.5]
        assert backend.values(M.CALL_RESULT_QUERIES) == [2]
        assert backend.values(M.CALL_END_TO_END) == [8.5]

    def test_the_source_tells_a_fetch_from_an_inline_result(self, recorder):
        telemetry, backend = recorder
        self._read(telemetry, source=M.SOURCE_INLINE, queries=0)
        self._read(telemetry, source=M.SOURCE_STORAGE)

        sources = {
            labels['source']
            for name, _, labels in backend.observations
            if name == M.CALL_RESULT_DOWNLOAD.name
        }
        assert sources == {M.SOURCE_INLINE, M.SOURCE_STORAGE}

    def test_a_result_never_read_records_nothing(self, recorder):
        telemetry, backend = recorder
        telemetry.on_result_read(_future(), M.SOURCE_STORAGE)

        assert backend.values(M.CALL_RESULT_DOWNLOAD) == []
        assert backend.values(M.CALL_END_TO_END) == []

    def test_clock_skew_does_not_produce_a_negative_latency(self, recorder):
        telemetry, backend = recorder
        self._read(telemetry, status_done=1008.75, done=1008.25)

        assert backend.values(M.CALL_RESULT_DOWNLOAD) == [0.0]

    def test_a_broken_future_is_swallowed(self, recorder):
        telemetry, _ = recorder
        telemetry.on_result_read(object(), M.SOURCE_STORAGE)


class TestFutureRecordsItsResult:
    """
    The future reaches the exporter through a module level lookup rather
    than by holding it, so that it stays picklable: a worker pickles a
    future whenever a function returns futures
    """

    def _future_for(self, backend='aws_lambda'):
        from lithops.future import ResponseFuture

        job = SimpleNamespace(
            job_id='M000', job_key='sess-M000', executor_id='sess',
            function_name='my_func', execution_timeout=60,
            runtime_name='python:3.11', runtime_memory=512, backend=backend,
        )
        storage_config = {
            'backend': 'localhost',
            'localhost': {'storage_bucket': 'bucket'},
        }
        return ResponseFuture(
            '00000', job, {'host_submit_tstamp': 1000.0}, storage_config
        )

    def test_the_future_knows_which_backend_it_ran_on(self):
        assert self._future_for().backend == 'aws_lambda'

    def test_a_future_stays_picklable(self):
        import pickle

        future = self._future_for()
        assert pickle.loads(pickle.dumps(future)).backend == 'aws_lambda'

    def test_recording_the_result_reaches_the_exporter(self):
        backend = RecordingBackend()
        exporter = TelemetryExporter(backend, flush_interval=3600)
        future = self._future_for()
        future.stats['host_status_done_tstamp'] = 1008.0

        with patch(
            'lithops.telemetry.exporter._exporter', exporter
        ):
            future._record_result_stats(M.SOURCE_STORAGE, 2)
        exporter.shutdown()

        assert backend.values(M.CALL_RESULT_QUERIES) == [2]
        assert future.stats['host_result_query_count'] == 2
        assert future.stats['host_result_done_tstamp']

    def test_recording_the_result_without_telemetry_is_a_no_op(self):
        future = self._future_for()

        future._record_result_stats(M.SOURCE_INLINE, 0)

        assert future.stats['host_result_query_count'] == 0
        assert future.stats['host_result_done_tstamp']


class TestTelemetryNeverBreaksAJob:

    def test_a_backend_that_raises_is_swallowed(self, recorder):
        telemetry, backend = recorder
        backend.observe = MagicMock(side_effect=RuntimeError('gateway down'))

        telemetry.on_call_finished(_future(), _call_status())
        telemetry.on_call_started(_future(), _call_status())
        telemetry.on_job_submitted(
            SimpleNamespace(total_calls=1, function_name='f',
                            runtime_name='r', runtime_memory=1)
        )

    def test_a_future_missing_its_attributes_is_swallowed(self, recorder):
        telemetry, _ = recorder
        telemetry.on_call_finished(object(), _call_status())

    def test_a_flush_that_raises_is_swallowed(self, recorder):
        telemetry, backend = recorder
        backend.flush = MagicMock(side_effect=OSError('unreachable'))
        telemetry.flush()

    def test_an_invented_label_is_dropped_rather_than_written(self):
        backend = RecordingBackend()
        exporter = TelemetryExporter(backend, flush_interval=3600)
        try:
            exporter.observe(M.CALLS_INVOKED, 1, {'backend': 'aws_lambda'})
        finally:
            exporter.shutdown()

        assert backend.observations == []


class TestExporterLifecycle:

    def test_shutdown_flushes_once_and_is_idempotent(self):
        backend = RecordingBackend()
        exporter = TelemetryExporter(backend, flush_interval=3600)
        exporter.shutdown()
        exporter.shutdown()

        assert backend.flushes == 1
        assert backend.shutdowns == 1

    def test_the_flush_thread_pushes_on_its_own(self):
        backend = RecordingBackend()
        exporter = TelemetryExporter(backend, flush_interval=0.01)
        try:
            deadline = time.time() + 2
            while backend.flushes < 2 and time.time() < deadline:
                time.sleep(0.01)
            assert backend.flushes >= 2
        finally:
            exporter.shutdown()

    def test_telemetry_is_off_by_default(self):
        assert get_telemetry({'lithops': {}}) is NOOP
        assert get_telemetry(None) is NOOP

    def test_one_process_exports_through_one_exporter(self):
        config = {'lithops': {'telemetry': 'recording', 'backend': 'aws_lambda'}}
        with patch(
            'lithops.telemetry.exporter.load_backend_class',
            return_value=RecordingBackend,
        ):
            first = get_telemetry(config)
            second = get_telemetry(config)

        assert isinstance(first, BoundTelemetry)
        assert first._exporter is second._exporter

    def test_a_worker_exports_nothing(self, monkeypatch):
        # Workers get the client's whole config, and the remote invoker
        # builds a JobMonitor of its own
        monkeypatch.setenv('LITHOPS_WORKER', 'True')
        config = {'lithops': {'telemetry': 'prometheus'}}

        assert get_telemetry(config) is NOOP

    def test_a_backend_that_cannot_be_built_disables_telemetry(self):
        config = {'lithops': {'telemetry': 'nonexistent-backend'}}
        assert get_telemetry(config) is NOOP

    def test_current_telemetry_never_starts_an_exporter(self):
        from lithops.telemetry import current_telemetry

        assert current_telemetry('aws_lambda') is NOOP

    def test_current_telemetry_binds_the_running_exporter(self):
        from lithops.telemetry import current_telemetry

        config = {'lithops': {'telemetry': 'recording'}}
        with patch(
            'lithops.telemetry.exporter.load_backend_class',
            return_value=RecordingBackend,
        ):
            bound = get_telemetry(config)
        later = current_telemetry('aws_lambda')

        assert later._exporter is bound._exporter
        assert later._backend == 'aws_lambda'

    def test_the_noop_records_nothing_and_raises_nothing(self):
        assert NOOP.enabled is False
        NOOP.on_job_submitted(None)
        NOOP.on_call_started(None, None)
        NOOP.on_call_finished(None, None)
        NOOP.on_result_read(None, 'storage')
        NOOP.flush()


class TestMonitorFunnel:
    """
    Every state change of a future has to go past the telemetry, whatever
    monitoring backend produced it
    """

    def _monitor(self, telemetry):
        monitor = Monitor(
            executor_id='sess-0', internal_storage=None,
            token_bucket_q=None, job_chunksize={},
            generate_tokens=False, config={},
        )
        monitor.attach_telemetry(telemetry)
        return monitor

    def test_an_unattached_monitor_is_safe(self):
        monitor = Monitor(
            executor_id='sess-0', internal_storage=None,
            token_bucket_q=None, job_chunksize={},
            generate_tokens=False, config={},
        )
        assert monitor.telemetry is NOOP

        future = MagicMock()
        monitor._mark_ready(future, {})
        future._set_ready.assert_called_once()

    def test_marking_a_future_running_records_it(self, recorder):
        telemetry, backend = recorder
        monitor = self._monitor(telemetry)
        future = _future()
        future._set_running = MagicMock()

        monitor._mark_running(future, _call_status())

        future._set_running.assert_called_once()
        assert backend.values(M.CALLS_STARTED) == [1]

    def test_marking_a_future_ready_records_it(self, recorder):
        telemetry, backend = recorder
        monitor = self._monitor(telemetry)
        future = _future()
        future._set_ready = MagicMock()

        monitor._mark_ready(future, _call_status())

        future._set_ready.assert_called_once()
        assert backend.values(M.CALLS_COMPLETED) == [1]

    def test_the_status_is_measured_after_the_future_records_it(self, recorder):
        telemetry, backend = recorder
        monitor = self._monitor(telemetry)
        future = _future()

        def _set_ready(call_status):
            future._host_status_done_tstamp = 1009.0

        future._set_ready = _set_ready
        monitor._mark_ready(future, _call_status())

        assert backend.values(M.CALL_STATUS_LATENCY) == [1.0]

    def test_a_chained_call_is_counted_once_under_its_own_outcome(
        self, recorder
    ):
        telemetry, backend = recorder
        monitor = self._monitor(telemetry)
        future = MagicMock()
        future._new_futures = []
        monitor.add_futures = MagicMock()

        assert monitor._check_new_futures({'new_futures': 'x'}, future) is True

        outcomes = [
            labels['outcome'] for name, _, labels in backend.observations
            if name == M.CALLS_COMPLETED.name
        ]
        assert outcomes == [M.OUTCOME_CHAINED]

    def test_a_call_that_returned_no_futures_records_nothing_here(
        self, recorder
    ):
        telemetry, backend = recorder
        monitor = self._monitor(telemetry)

        assert monitor._check_new_futures({}, MagicMock()) is False
        assert backend.observations == []


class TestPrometheusBackend:

    @pytest.fixture
    def backend(self):
        prometheus_client = pytest.importorskip('prometheus_client')
        assert prometheus_client
        from lithops.telemetry.backends.prometheus import MetricsBackend
        from lithops.telemetry.backends.prometheus.config import load_config

        config = {'lithops': {'telemetry': 'prometheus'}}
        load_config(config)
        return MetricsBackend(config['prometheus'])

    def test_defaults_do_not_move_with_the_execution(self):
        from lithops.telemetry.backends.prometheus.config import load_config

        first = {'lithops': {}}
        second = {'lithops': {}}
        load_config(first)
        load_config(second)

        assert first['prometheus'] == second['prometheus']

    def test_a_histogram_gets_the_buckets_of_its_spec(self, backend):
        from prometheus_client import generate_latest

        labels = {
            'backend': 'aws_lambda', 'runtime_name': 'python:3.11',
            'runtime_memory': '512', 'function_name': 'my_func',
        }
        backend.observe(M.CALL_DURATION, 1.5, labels)
        exposed = generate_latest(backend.registry).decode()

        assert 'lithops_call_duration_seconds_bucket' in exposed
        for bound in M.CALL_DURATION.buckets:
            assert f'le="{float(bound)}"' in exposed

    def test_a_counter_accumulates(self, backend):
        from prometheus_client import generate_latest

        labels = {
            'backend': 'aws_lambda', 'runtime_name': 'python:3.11',
            'runtime_memory': '512', 'function_name': 'my_func',
            'outcome': 'success',
        }
        backend.observe(M.CALLS_COMPLETED, 1, labels)
        backend.observe(M.CALLS_COMPLETED, 2, labels)
        exposed = generate_latest(backend.registry).decode()

        assert 'lithops_calls_completed_total{' in exposed
        assert '} 3.0' in exposed

    def test_the_instrument_is_built_once(self, backend):
        labels = {
            'backend': 'aws_lambda', 'runtime_name': 'python:3.11',
            'runtime_memory': '512', 'function_name': 'my_func',
        }
        backend.observe(M.CALLS_STARTED, 1, labels)
        backend.observe(M.CALLS_STARTED, 1, labels)

        assert list(backend._instruments) == [M.CALLS_STARTED.name]

    def test_a_flush_replaces_the_group_of_this_host(self, backend):
        with patch(
            'prometheus_client.push_to_gateway'
        ) as push:
            backend.flush()

        push.assert_called_once()
        assert push.call_args.kwargs['job'] == 'lithops'
        assert set(push.call_args.kwargs['grouping_key']) == {'instance'}

    def test_the_created_series_are_not_pushed(self, backend):
        from prometheus_client import generate_latest
        from lithops.telemetry.backends.prometheus.prometheus import (
            _WithoutCreatedSeries,
        )

        labels = {
            'backend': 'aws_lambda', 'runtime_name': 'python:3.11',
            'runtime_memory': '512', 'function_name': 'my_func',
        }
        backend.observe(M.CALLS_STARTED, 1, labels)

        pushed = generate_latest(
            _WithoutCreatedSeries(backend.registry)
        ).decode()
        assert 'lithops_calls_started_total{' in pushed
        assert '_created' not in pushed
        # and the registry itself is left as it was
        assert '_created' in generate_latest(backend.registry).decode()

    def test_basic_auth_is_used_when_configured(self):
        pytest.importorskip('prometheus_client')
        from lithops.telemetry.backends.prometheus import MetricsBackend
        from lithops.telemetry.backends.prometheus.config import load_config

        config = {
            'lithops': {},
            'prometheus': {'username': 'u', 'password': 'p'},
        }
        load_config(config)
        backend = MetricsBackend(config['prometheus'])

        assert backend._handler is not None


class TestOtlpBackend:

    @pytest.fixture
    def backend_and_reader(self):
        pytest.importorskip('opentelemetry.sdk')
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from lithops.telemetry.backends.otlp import MetricsBackend
        from lithops.telemetry.backends.otlp.config import load_config

        config = {'lithops': {'telemetry': 'otlp'}}
        load_config(config)
        reader = InMemoryMetricReader()
        with patch.object(
            MetricsBackend, '_create_reader', staticmethod(lambda cfg: reader)
        ):
            yield MetricsBackend(config['otlp']), reader

    @staticmethod
    def _exported(reader):
        exported = {}
        data = reader.get_metrics_data()
        for resource_metrics in data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    exported[metric.name] = metric
        return exported

    def test_the_metric_names_match_the_prometheus_ones(
        self, backend_and_reader
    ):
        backend, reader = backend_and_reader
        labels = {
            'backend': 'aws_lambda', 'runtime_name': 'python:3.11',
            'runtime_memory': '512', 'function_name': 'my_func',
        }
        backend.observe(M.CALL_DURATION, 1.5, labels)
        backend.observe(M.CALLS_STARTED, 1, labels)

        exported = self._exported(reader)
        assert M.CALL_DURATION.name in exported
        assert M.CALLS_STARTED.name in exported

    def test_a_histogram_gets_the_buckets_of_its_spec(
        self, backend_and_reader
    ):
        backend, reader = backend_and_reader
        labels = {
            'backend': 'aws_lambda', 'runtime_name': 'python:3.11',
            'runtime_memory': '512', 'function_name': 'my_func',
        }
        backend.observe(M.CALL_DURATION, 1.5, labels)

        metric = self._exported(reader)[M.CALL_DURATION.name]
        point = list(metric.data.data_points)[0]
        assert tuple(point.explicit_bounds) == tuple(M.CALL_DURATION.buckets)

    def test_the_labels_travel_as_attributes(self, backend_and_reader):
        backend, reader = backend_and_reader
        labels = {
            'backend': 'aws_lambda', 'runtime_name': 'python:3.11',
            'runtime_memory': '512', 'function_name': 'my_func',
            'outcome': 'success',
        }
        backend.observe(M.CALLS_COMPLETED, 1, labels)

        metric = self._exported(reader)[M.CALLS_COMPLETED.name]
        point = list(metric.data.data_points)[0]
        assert dict(point.attributes) == labels

    def test_the_temporality_is_pinned_to_cumulative(self):
        pytest.importorskip('opentelemetry.sdk')
        from opentelemetry.sdk.metrics.export import AggregationTemporality
        from lithops.telemetry.backends.otlp import MetricsBackend

        temporality = MetricsBackend._cumulative_temporality()

        assert temporality
        assert set(temporality.values()) == {AggregationTemporality.CUMULATIVE}

    def test_an_unknown_protocol_is_refused(self):
        pytest.importorskip('opentelemetry.sdk')
        from lithops.telemetry.backends.otlp import MetricsBackend
        from lithops.telemetry.backends.otlp.config import load_config

        config = {'lithops': {}, 'otlp': {'protocol': 'carrier-pigeon'}}
        load_config(config)
        with pytest.raises(ValueError, match='carrier-pigeon'):
            MetricsBackend(config['otlp'])

    @pytest.mark.parametrize('endpoint, expected', [
        ('http://collector:4318', 'http://collector:4318/v1/metrics'),
        ('http://collector:4318/', 'http://collector:4318/v1/metrics'),
        ('http://collector:4318/v1/metrics', 'http://collector:4318/v1/metrics'),
    ])
    def test_the_signal_path_is_added_once(self, endpoint, expected):
        pytest.importorskip('opentelemetry.sdk')
        from lithops.telemetry.backends.otlp.otlp import _metrics_endpoint

        assert _metrics_endpoint(endpoint) == expected


class TestConfigIntegration:

    def test_the_telemetry_section_is_filled_in(self):
        from lithops.config import _load_telemetry_backend_config

        config = {'lithops': {'telemetry': True}}
        _load_telemetry_backend_config(config)

        assert config['lithops']['telemetry'] == DEFAULT_BACKEND
        assert config['prometheus']['gateway']
        assert config['prometheus']['instance']

    def test_a_disabled_telemetry_loads_no_backend(self):
        from lithops.config import _load_telemetry_backend_config

        config = {'lithops': {}}
        _load_telemetry_backend_config(config)

        assert config['lithops']['telemetry'] is False
        assert 'prometheus' not in config

    def test_an_unknown_backend_is_reported(self):
        from lithops.config import _load_telemetry_backend_config

        config = {'lithops': {'telemetry': 'graphite'}}
        with pytest.raises(Exception, match='graphite'):
            _load_telemetry_backend_config(config)

    def test_user_values_are_not_overwritten(self):
        from lithops.config import _load_telemetry_backend_config

        config = {
            'lithops': {'telemetry': 'prometheus'},
            'prometheus': {'gateway': 'http://gw:9091', 'instance': 'ci'},
        }
        _load_telemetry_backend_config(config)

        assert config['prometheus']['gateway'] == 'http://gw:9091'
        assert config['prometheus']['instance'] == 'ci'
