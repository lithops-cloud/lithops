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

import os
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lithops.constants import LOCALHOST, SERVERLESS
from lithops.future import ResponseFuture
from lithops.invokers import (
    BatchInvoker,
    FaaSInvoker,
    Invoker,
    _format_call_id,
    _timed_invoke,
    _verify_runtime_meta,
    create_invoker,
    extend_runtime,
)
from lithops.utils import BackendType, version_str
from lithops.version import __version__


class TestInvokerHelpers:

    def test_format_call_id_zero_fills(self):
        assert _format_call_id(0) == '00000'
        assert _format_call_id(12) == '00012'
        assert _format_call_id(99999) == '99999'

    def test_verify_runtime_meta_accepts_matching_versions(self):
        _verify_runtime_meta(
            {
                'lithops_version': __version__,
                'python_version': version_str(sys.version_info),
            },
            'python:3',
        )

    def test_verify_runtime_meta_lithops_mismatch(self):
        with pytest.raises(Exception, match='Lithops version mismatch'):
            _verify_runtime_meta(
                {
                    'lithops_version': '0.0.0',
                    'python_version': version_str(sys.version_info),
                },
                'python:3',
            )

    def test_verify_runtime_meta_python_mismatch_includes_runtime_name(self):
        with pytest.raises(Exception, match="indicated runtime 'my-runtime'"):
            _verify_runtime_meta(
                {
                    'lithops_version': __version__,
                    'python_version': '2.7',
                },
                'my-runtime',
            )


class TestCreateInvoker:

    @patch('lithops.invokers.BatchInvoker')
    def test_creates_batch_invoker(self, batch_cls):
        handler = MagicMock()
        handler.get_backend_type.return_value = BackendType.BATCH.value
        result = create_invoker('cfg', 'ex', 'store', handler, 'monitor')
        batch_cls.assert_called_once_with('cfg', 'ex', 'store', handler, 'monitor')
        assert result is batch_cls.return_value

    @patch('lithops.invokers.FaaSInvoker')
    def test_creates_faas_invoker(self, faas_cls):
        handler = MagicMock()
        handler.get_backend_type.return_value = BackendType.FAAS.value
        result = create_invoker('cfg', 'ex', 'store', handler, 'monitor')
        faas_cls.assert_called_once_with('cfg', 'ex', 'store', handler, 'monitor')
        assert result is faas_cls.return_value

    def test_unknown_backend_type_returns_none(self):
        handler = MagicMock()
        handler.get_backend_type.return_value = 'mystery'
        assert create_invoker('cfg', 'ex', 'store', handler, 'monitor') is None


def _matching_runtime_meta():
    return {
        'lithops_version': __version__,
        'python_version': version_str(sys.version_info),
        'runtime_timeout': 300,
    }


def _job(**overrides):
    values = dict(
        executor_id='sess-0',
        job_id='M000',
        job_key='sess-0/M000',
        function_name='fn',
        func_key='fk',
        data_key='dk',
        extra_env=None,
        total_calls=2,
        execution_timeout=60,
        data_byte_ranges=[(0, 1), (2, 3)],
        chunksize=1,
        worker_processes=1,
        runtime_name='python:3',
        runtime_memory=256,
        metadata={'func_name': 'fn'},
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _bare_invoker(**attrs):
    inv = Invoker.__new__(Invoker)
    defaults = dict(
        executor_id='sess-0',
        mode=SERVERLESS,
        runtime_name='python:3',
        runtime_info={
            'runtime_name': 'python:3',
            'runtime_memory': 256,
            'runtime_timeout': 300,
            'max_workers': 8,
        },
        compute_handler=MagicMock(),
        internal_storage=MagicMock(),
        config={'lithops': {'mode': SERVERLESS, 'backend': 'ibm_cf'}, 'ibm_cf': {}},
        backend='ibm_cf',
        include_function=False,
        prometheus=MagicMock(),
        job_monitor=MagicMock(),
        storage_config={'backend': 'localhost', 'localhost': {'storage_bucket': 'test-bucket'}},
        max_workers=8,
        log_level='INFO',
    )
    defaults.update(attrs)
    for key, value in defaults.items():
        setattr(inv, key, value)
    return inv


class TestTimedInvoke:

    def test_timed_invoke_returns_activation_and_duration(self):
        handler = MagicMock()
        handler.invoke.return_value = 'act-9'
        activation_id, resp_time = _timed_invoke(handler, {'x': 1})
        assert activation_id == 'act-9'
        assert isinstance(resp_time, str)
        handler.invoke.assert_called_once_with({'x': 1})


class TestSelectRuntime:

    def test_serverless_uses_override_memory_and_skips_deploy_when_meta_exists(self):
        inv = _bare_invoker()
        inv.internal_storage.get_runtime_meta.return_value = _matching_runtime_meta()
        inv.compute_handler.get_runtime_key.return_value = 'rk'
        meta = inv.select_runtime('M000', 512)
        assert meta['lithops_version'] == __version__
        inv.compute_handler.get_runtime_key.assert_called_once()
        inv.compute_handler.deploy_runtime.assert_not_called()
        # memory override is passed to get_runtime_key
        assert inv.compute_handler.get_runtime_key.call_args[0][1] == 512

    def test_non_serverless_ignores_memory_override(self):
        inv = _bare_invoker(mode=LOCALHOST)
        inv.internal_storage.get_runtime_meta.return_value = _matching_runtime_meta()
        inv.compute_handler.get_runtime_key.return_value = 'rk'
        inv.select_runtime('M000', 512)
        assert inv.compute_handler.get_runtime_key.call_args[0][1] == 256

    def test_deploys_runtime_when_meta_missing(self):
        inv = _bare_invoker()
        inv.internal_storage.get_runtime_meta.return_value = None
        inv.compute_handler.get_runtime_key.return_value = 'rk'
        inv.compute_handler.deploy_runtime.return_value = _matching_runtime_meta()
        meta = inv.select_runtime('M000', None)
        inv.compute_handler.deploy_runtime.assert_called_once()
        inv.internal_storage.put_runtime_meta.assert_called_once()
        assert meta['runtime_timeout'] == 300


class TestPayloadAndFutures:

    def test_create_payload_copies_job_fields(self):
        inv = _bare_invoker()
        job = _job(chunksize=4, worker_processes=3, extra_env={'K': '1'})
        payload = inv._create_payload(job)
        assert payload['func_name'] == 'fn'
        assert payload['total_calls'] == 2
        assert payload['call_ids'] is None
        assert payload['lithops_version'] == __version__
        assert payload['chunksize'] == 4
        assert payload['worker_processes'] == 3
        assert payload['extra_env'] == {'K': '1'}
        assert payload['max_workers'] == 8
        assert payload['data_key'] == 'dk'

    def test_build_futures_marks_invoked_and_copies_metadata(self):
        inv = _bare_invoker()
        job = _job(total_calls=3, metadata={'func_name': 'fn', 'host_submit_tstamp': 1})
        futures = inv._build_futures(job)
        assert len(futures) == 3
        assert job.futures is futures
        assert all(isinstance(f, ResponseFuture) for f in futures)
        assert all(f.invoked for f in futures)
        assert futures[0].call_id == '00000'
        assert futures[2].call_id == '00002'
        assert futures[0].stats['func_name'] == 'fn'

    def test_run_job_sends_metrics_and_invokes(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.invokers.LOGS_DIR', str(tmp_path))
        inv = _bare_invoker()
        inv._invoke_job = MagicMock()
        job = _job()
        futures = inv._run_job(job)
        inv._invoke_job.assert_called_once_with(job)
        inv.prometheus.send_metric.assert_called()
        assert len(futures) == 2

    def test_run_job_include_function_extends_runtime(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.invokers.LOGS_DIR', str(tmp_path))
        inv = _bare_invoker(include_function=True, runtime_name='base:tag')
        inv._invoke_job = MagicMock()
        with patch('lithops.invokers.extend_runtime') as ext:
            job = _job(runtime_name='base:tag')
            inv._run_job(job)
            ext.assert_called_once()
            assert job.runtime_name == 'base:tag'

    def test_run_job_stops_invoker_on_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.invokers.LOGS_DIR', str(tmp_path))
        inv = _bare_invoker()
        inv._invoke_job = MagicMock(side_effect=RuntimeError('nope'))
        inv.stop = MagicMock()
        with pytest.raises(RuntimeError, match='nope'):
            inv._run_job(_job())
        inv.stop.assert_called_once()


class TestBatchInvoker:

    def test_invoke_job_sets_call_ids(self):
        inv = BatchInvoker.__new__(BatchInvoker)
        for key, value in _bare_invoker().__dict__.items():
            setattr(inv, key, value)
        inv.compute_handler.invoke.return_value = 'act-1'
        job = _job(total_calls=2)
        inv._invoke_job(job)
        payload = inv.compute_handler.invoke.call_args[0][0]
        assert payload['call_ids'] == ['00000', '00001']

    def test_run_job_starts_monitor(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.invokers.LOGS_DIR', str(tmp_path))
        inv = BatchInvoker.__new__(BatchInvoker)
        for key, value in _bare_invoker().__dict__.items():
            setattr(inv, key, value)
        inv._invoke_job = MagicMock()
        job = _job()
        futures = inv.run_job(job)
        inv.job_monitor.start.assert_called_once_with(futures)


class TestFaaSInvokerHelpers:

    def _faas(self, **attrs):
        inv = FaaSInvoker.__new__(FaaSInvoker)
        for key, value in _bare_invoker(**attrs).__dict__.items():
            setattr(inv, key, value)
        inv.pending_calls_q = queue.Queue()
        inv.job_monitor = MagicMock()
        inv.job_monitor.token_bucket_q = queue.Queue()
        inv.running_workers = 0
        inv.should_run = False
        inv.remote_invoker = False
        inv.sync = False
        inv.invokers = []
        inv.executor = MagicMock()
        return inv

    def test_drain_token_bucket_noop_when_no_workers_or_empty(self):
        inv = self._faas()
        inv.running_workers = 0
        inv._drain_token_bucket()
        inv.running_workers = 3
        inv._drain_token_bucket()
        assert inv.running_workers == 3

    def test_drain_token_bucket_consumes_until_zero(self):
        inv = self._faas()
        inv.running_workers = 2
        inv.job_monitor.token_bucket_q.put('#')
        inv.job_monitor.token_bucket_q.put('#')
        inv.job_monitor.token_bucket_q.put('#')
        inv._drain_token_bucket()
        assert inv.running_workers == 0
        assert inv.job_monitor.token_bucket_q.qsize() == 1

    def test_queue_call_ranges_chunks_ids(self):
        inv = self._faas()
        job = _job(chunksize=2)
        inv._queue_call_ranges(job, range(5))
        ranges = []
        while not inv.pending_calls_q.empty():
            queued_job, ids = inv.pending_calls_q.get()
            assert queued_job is job
            ranges.append(list(ids))
        assert ranges == [[0, 1], [2, 3], [4]]

    def test_invoke_job_remote_success(self):
        inv = self._faas()
        inv.compute_handler.invoke.return_value = 'act-r'
        inv._invoke_job_remote(_job())

    def test_invoke_job_remote_failure(self):
        inv = self._faas()
        inv.compute_handler.invoke.return_value = None
        with pytest.raises(Exception, match='Unable to spawn remote invoker'):
            inv._invoke_job_remote(_job())

    def test_invoke_task_requeues_when_activation_missing(self, monkeypatch):
        inv = self._faas()
        monkeypatch.setattr('lithops.invokers.time.sleep', lambda *_: None)
        inv.compute_handler.invoke.return_value = None
        job = _job()
        inv._invoke_task(job, [0, 1])
        queued_job, ids = inv.pending_calls_q.get_nowait()
        assert queued_job is job
        assert list(ids) == [0, 1]
        assert inv.job_monitor.token_bucket_q.get_nowait() == '#'

    def test_invoke_job_queues_all_when_at_max_workers(self):
        inv = self._faas()
        inv.should_run = True
        inv.running_workers = 8
        inv.max_workers = 8
        job = _job(total_calls=3, chunksize=1)
        inv._invoke_job(job)
        assert inv.pending_calls_q.qsize() == 3

    def test_run_job_starts_monitor_with_tokens(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.invokers.LOGS_DIR', str(tmp_path))
        inv = self._faas()
        inv._invoke_job = MagicMock()
        job = _job()
        futures = inv.run_job(job)
        inv.job_monitor.start.assert_called_once_with(
            fs=futures, job_id='M000', chunksize=1, generate_tokens=True
        )

    def test_invoke_job_uses_free_workers_and_queues_remainder(self):
        inv = self._faas()
        inv.max_workers = 2
        inv.executor = MagicMock()
        inv._start_async_invokers = MagicMock()
        job = _job(total_calls=5, chunksize=2)
        inv._invoke_job(job)
        inv._start_async_invokers.assert_called_once()
        assert inv.executor.submit.call_count == 2
        assert inv.running_workers == 2
        assert inv.pending_calls_q.qsize() == 1
        _, ids = inv.pending_calls_q.get()
        assert list(ids) == [4]

    def test_stop_drains_pending_queue_and_signals_invokers(self):
        inv = self._faas()
        inv.should_run = True
        threads = [MagicMock(), MagicMock()]
        inv.invokers = list(threads)
        inv.pending_calls_q.put((_job(), [0]))
        inv.pending_calls_q.put((_job(), [1]))
        inv.stop()
        assert inv.should_run is False
        assert inv.invokers == []
        for thread in threads:
            thread.join.assert_not_called()
        tokens = []
        while not inv.job_monitor.token_bucket_q.empty():
            tokens.append(inv.job_monitor.token_bucket_q.get_nowait())
        assert tokens == ['$', '$']
        pending = []
        while not inv.pending_calls_q.empty():
            pending.append(inv.pending_calls_q.get_nowait())
        assert pending == [(None, None), (None, None)]

    def test_start_async_invokers_starts_daemon_threads(self):
        inv = self._faas()
        inv.invoke_pool_threads = 8
        inv.should_run = True
        with patch('lithops.invokers.threading.Thread') as Thread:
            inv._start_async_invokers()
        assert Thread.call_count == FaaSInvoker.ASYNC_INVOKERS
        thread = Thread.return_value
        assert thread.daemon is True
        assert thread.start.call_count == FaaSInvoker.ASYNC_INVOKERS
        assert inv.job_monitor.token_bucket_q.qsize() == FaaSInvoker.ASYNC_INVOKERS
        assert len(inv.invokers) == FaaSInvoker.ASYNC_INVOKERS

    def test_invoke_task_uses_data_byte_strs_when_no_data_key(self):
        inv = self._faas()
        inv.compute_handler.invoke.return_value = 'act-1'
        job = _job(data_key=None, data_byte_strs=[b'a', b'b'], total_calls=2)
        inv._invoke_task(job, [0, 1])
        payload = inv.compute_handler.invoke.call_args[0][0]
        assert 'data_byte_ranges' not in payload
        assert payload['data_byte_strs'] == [b'a', b'b']
        assert payload['call_ids'] == ['00000', '00001']

    def test_invoke_task_slices_data_byte_ranges_for_chunk(self):
        inv = self._faas()
        inv.compute_handler.invoke.return_value = 'act-1'
        job = _job(
            total_calls=4,
            data_byte_ranges=[(0, 1), (2, 3), (4, 5), (6, 7)],
        )
        inv._invoke_task(job, [1, 2])
        payload = inv.compute_handler.invoke.call_args[0][0]
        assert payload['call_ids'] == ['00001', '00002']
        assert payload['data_byte_ranges'] == [(2, 3), (4, 5)]
        assert payload['chunksize'] == 1

    def test_invoke_job_remote_flag_skips_local_scheduling(self):
        inv = self._faas()
        inv.remote_invoker = True
        inv.compute_handler.invoke.return_value = 'act-r'
        inv._start_async_invokers = MagicMock()
        inv._invoke_job(_job())
        inv._start_async_invokers.assert_not_called()
        inv.compute_handler.pre_invoke.assert_called_once()
        payload = inv.compute_handler.invoke.call_args[0][0]
        assert payload['remote_invoker'] is True
        assert payload['job']['job_id'] == 'M000'
        assert inv.pending_calls_q.empty()

    def test_invoke_job_exact_fit_does_not_queue(self):
        inv = self._faas()
        inv.max_workers = 3
        inv.executor = MagicMock()
        inv._start_async_invokers = MagicMock()
        inv._invoke_job(_job(total_calls=3, chunksize=1))
        assert inv.executor.submit.call_count == 3
        assert inv.pending_calls_q.empty()
        assert inv.running_workers == 3

    def test_second_job_at_capacity_queues_all_without_restart(self):
        inv = self._faas()
        inv.should_run = True
        inv.running_workers = 8
        inv.max_workers = 8
        inv._start_async_invokers = MagicMock()
        inv._invoke_job(_job(total_calls=3, chunksize=1))
        inv._start_async_invokers.assert_not_called()
        assert inv.pending_calls_q.qsize() == 3

    def test_second_job_drains_leftover_tokens_before_direct_invoke(self):
        inv = self._faas()
        inv.should_run = True
        inv.running_workers = 3
        inv.max_workers = 8
        inv.executor = MagicMock()
        inv._start_async_invokers = MagicMock()
        inv.job_monitor.token_bucket_q.put('#')
        inv.job_monitor.token_bucket_q.put('#')
        inv._invoke_job(_job(total_calls=2, chunksize=1))
        inv._start_async_invokers.assert_not_called()
        assert inv.job_monitor.token_bucket_q.empty()
        assert inv.executor.submit.call_count == 2
        assert inv.running_workers == 3
        assert inv.pending_calls_q.empty()

    def test_stop_waits_for_invoker_threads_when_asked(self):
        inv = self._faas()
        inv.should_run = True
        threads = [MagicMock(), MagicMock()]
        inv.invokers = list(threads)
        inv.stop(wait=True)
        for thread in threads:
            thread.join.assert_called_once_with(timeout=inv.STOP_TIMEOUT)

    def test_stop_with_wait_blocks_until_the_invocations_are_done(self):
        # This is what replaced the blind sleep(5) in the remote invoker: the
        # async invoker threads drain the invocations already in flight only
        # after they leave their loop, and nothing else joins them
        inv = self._faas()
        inv.should_run = True
        started = threading.Event()
        finished = []

        def in_flight():
            started.set()
            time.sleep(0.3)
            finished.append('done')

        thread = threading.Thread(target=in_flight)
        inv.invokers = [thread]
        thread.start()
        assert started.wait(timeout=5)

        inv.stop(wait=True)
        assert finished == ['done'], 'stop returned before the call finished'
        assert not thread.is_alive()

    def test_stop_without_wait_returns_while_calls_are_in_flight(self):
        inv = self._faas()
        inv.should_run = True
        started = threading.Event()
        release = threading.Event()

        def in_flight():
            started.set()
            release.wait(timeout=5)

        thread = threading.Thread(target=in_flight, daemon=True)
        inv.invokers = [thread]
        thread.start()
        assert started.wait(timeout=5)
        try:
            inv.stop()
            assert thread.is_alive(), 'stop should not have waited'
        finally:
            release.set()
            thread.join(timeout=5)

    def test_stop_is_noop_when_no_async_invokers(self):
        inv = self._faas()
        inv.should_run = True
        inv.pending_calls_q.put((_job(), [0]))
        inv.stop()
        assert inv.should_run is True
        assert inv.pending_calls_q.qsize() == 1

    def test_invoke_job_calls_pre_invoke(self):
        inv = self._faas()
        inv.should_run = True
        inv.running_workers = 8
        inv.max_workers = 8
        job = _job(total_calls=1, chunksize=1)
        inv._invoke_job(job)
        inv.compute_handler.pre_invoke.assert_called_once_with(job)


class TestFaaSInvokerInit:

    def _handler(self):
        handler = MagicMock()
        handler.get_runtime_info.return_value = {
            'runtime_name': 'python:3',
            'runtime_memory': 256,
            'runtime_timeout': 300,
            'max_workers': 8,
        }
        return handler

    def _config(self, **backend):
        ibm_cf = {
            'invoke_pool_threads': 4,
            'remote_invoker': False,
        }
        ibm_cf.update(backend)
        return {
            'lithops': {
                'mode': SERVERLESS,
                'backend': 'ibm_cf',
                'storage': 'localhost',
                'telemetry': False,
            },
            'ibm_cf': ibm_cf,
            'localhost': {'storage_bucket': 'test-bucket'},
        }

    def test_init_reads_pool_threads_and_remote_invoker(self):
        inv = FaaSInvoker(
            self._config(remote_invoker=True, invoke_pool_threads=6),
            'sess-0',
            MagicMock(),
            self._handler(),
            MagicMock(),
        )
        try:
            assert inv.remote_invoker is True
            assert inv.sync is False
            assert inv.max_workers == 8
            assert inv.invoke_pool_threads == 6
            assert inv.should_run is False
            assert inv.pending_calls_q.empty()
        finally:
            inv.executor.shutdown(wait=False)

    def test_init_disables_remote_invoker_inside_worker(self, monkeypatch):
        monkeypatch.setenv('LITHOPS_WORKER', '1')
        inv = FaaSInvoker(
            self._config(remote_invoker=True),
            'sess-0',
            MagicMock(),
            self._handler(),
            MagicMock(),
        )
        try:
            assert inv.remote_invoker is False
            assert inv.sync is True
        finally:
            inv.executor.shutdown(wait=False)


def _wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f'timed out after {timeout}s')


class TestFaaSTokenBucketLoop:
    """Closed-loop token bucket with real invoker threads and a mocked backend."""

    def _live_faas(self, *, max_workers=1, async_invokers=1, pool_workers=16):
        inv = FaaSInvoker.__new__(FaaSInvoker)
        for key, value in _bare_invoker().__dict__.items():
            setattr(inv, key, value)
        inv.pending_calls_q = queue.Queue()
        inv.job_monitor = MagicMock()
        inv.job_monitor.token_bucket_q = queue.Queue()
        inv.running_workers = 0
        inv.should_run = False
        inv.remote_invoker = False
        inv.sync = False
        inv.invokers = []
        inv.executor = ThreadPoolExecutor(max_workers=pool_workers)
        inv.invoke_pool_threads = max(8, pool_workers)
        inv.ASYNC_INVOKERS = async_invokers
        inv.max_workers = max_workers
        return inv

    def test_token_unblocks_queued_invocation(self):
        invoked = []
        lock = threading.Lock()

        def invoke(payload):
            with lock:
                invoked.append(list(payload['call_ids']))
            return 'act-1'

        inv = self._live_faas()
        inv.compute_handler.invoke.side_effect = invoke
        inv.should_run = True
        job = _job(total_calls=2, chunksize=1)
        try:
            inv._start_async_invokers()
            inv._queue_call_ranges(job, range(2))
            _wait_until(lambda: len(invoked) == 1)
            with lock:
                assert invoked == [['00000']]
            assert inv.pending_calls_q.qsize() == 1

            inv.job_monitor.token_bucket_q.put('#')
            _wait_until(lambda: len(invoked) == 2)
            with lock:
                assert invoked == [['00000'], ['00001']]
        finally:
            inv.stop()
            inv.executor.shutdown(wait=True)

    def test_overflow_beyond_max_workers_waits_for_tokens(self):
        """10 workers, 20 calls: first wave runs now, the rest wait for tokens."""
        invoked = []
        lock = threading.Lock()

        def invoke(payload):
            with lock:
                invoked.append(list(payload['call_ids']))
            return 'act-1'

        max_workers = 10
        total_calls = 20
        async_invokers = FaaSInvoker.ASYNC_INVOKERS
        first_wave = max_workers + async_invokers
        leftover = total_calls - first_wave

        inv = self._live_faas(
            max_workers=max_workers, async_invokers=async_invokers
        )
        inv.compute_handler.invoke.side_effect = invoke
        job = _job(
            total_calls=total_calls,
            chunksize=1,
            data_byte_ranges=[(i, i) for i in range(total_calls)],
        )
        try:
            inv._invoke_job(job)
            _wait_until(lambda: len(invoked) == first_wave)
            assert inv.pending_calls_q.qsize() == leftover
            with lock:
                ids = [call_id for chunk in invoked for call_id in chunk]
            assert len(set(ids)) == first_wave

            for _ in range(leftover):
                inv.job_monitor.token_bucket_q.put('#')
            _wait_until(lambda: len(invoked) == total_calls)
            with lock:
                ids = [call_id for chunk in invoked for call_id in chunk]
            assert sorted(ids) == [f'{i:05d}' for i in range(total_calls)]
        finally:
            inv.stop()
            inv.executor.shutdown(wait=True)

    def test_completions_refill_bucket_and_drain_overflow(self):
        """Finished workers put tokens so the queued extra 10 calls all run."""
        invoked = []
        lock = threading.Lock()
        inv = self._live_faas(
            max_workers=10, async_invokers=FaaSInvoker.ASYNC_INVOKERS
        )

        def invoke(payload):
            with lock:
                invoked.append(list(payload['call_ids']))
            inv.job_monitor.token_bucket_q.put('#')
            return 'act-1'

        inv.compute_handler.invoke.side_effect = invoke
        job = _job(
            total_calls=20,
            chunksize=1,
            data_byte_ranges=[(i, i) for i in range(20)],
        )
        try:
            inv._invoke_job(job)
            _wait_until(lambda: len(invoked) == 20)
            with lock:
                ids = [call_id for chunk in invoked for call_id in chunk]
            assert sorted(ids) == [f'{i:05d}' for i in range(20)]
        finally:
            inv.stop()
            inv.executor.shutdown(wait=True)

    def test_overflow_with_chunksize_releases_one_token_per_worker(self):
        invoked = []
        lock = threading.Lock()

        def invoke(payload):
            with lock:
                invoked.append(list(payload['call_ids']))
            return 'act-1'

        inv = self._live_faas(max_workers=2, async_invokers=1)
        inv.compute_handler.invoke.side_effect = invoke
        job = _job(
            total_calls=8,
            chunksize=2,
            data_byte_ranges=[(i, i) for i in range(8)],
        )
        try:
            inv._invoke_job(job)
            # 2 direct workers + 1 primed async worker = 3 invokes, 6 calls
            _wait_until(lambda: len(invoked) == 3)
            assert inv.pending_calls_q.qsize() == 1
            inv.job_monitor.token_bucket_q.put('#')
            _wait_until(lambda: len(invoked) == 4)
            with lock:
                ids = [call_id for chunk in invoked for call_id in chunk]
            assert sorted(ids) == [f'{i:05d}' for i in range(8)]
        finally:
            inv.stop()
            inv.executor.shutdown(wait=True)

    def test_sync_waits_until_direct_invokes_finish(self):
        started = threading.Event()
        release = threading.Event()

        def invoke(payload):
            started.set()
            assert release.wait(timeout=2)
            return 'act-1'

        inv = self._live_faas(max_workers=1, async_invokers=1)
        inv.sync = True
        inv.compute_handler.invoke.side_effect = invoke
        job = _job(total_calls=1, chunksize=1)
        try:
            worker = threading.Thread(target=inv._invoke_job, args=(job,))
            worker.start()
            assert started.wait(timeout=2)
            assert worker.is_alive()
            release.set()
            worker.join(timeout=2)
            assert not worker.is_alive()
            assert inv.compute_handler.invoke.call_count == 1
        finally:
            release.set()
            inv.stop()
            inv.executor.shutdown(wait=True)

    def test_second_job_queues_until_tokens_after_workers_are_full(self):
        invoked = []
        lock = threading.Lock()

        def invoke(payload):
            with lock:
                invoked.append(list(payload['call_ids']))
            return 'act-1'

        inv = self._live_faas(max_workers=2, async_invokers=1)
        inv.compute_handler.invoke.side_effect = invoke
        job1 = _job(
            total_calls=2,
            chunksize=1,
            data_byte_ranges=[(0, 0), (1, 1)],
        )
        job2 = _job(
            job_id='M001',
            total_calls=2,
            chunksize=1,
            data_byte_ranges=[(0, 0), (1, 1)],
        )
        try:
            inv._invoke_job(job1)
            _wait_until(lambda: len(invoked) == 2)
            inv._invoke_job(job2)
            assert inv.pending_calls_q.qsize() == 2
            with lock:
                assert len(invoked) == 2
            inv.job_monitor.token_bucket_q.put('#')
            inv.job_monitor.token_bucket_q.put('#')
            _wait_until(lambda: len(invoked) == 4)
        finally:
            inv.stop()
            inv.executor.shutdown(wait=True)

    def test_run_job_invokes_and_starts_monitor_with_tokens(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.invokers.LOGS_DIR', str(tmp_path))
        invoked = []
        lock = threading.Lock()

        def invoke(payload):
            with lock:
                invoked.append(list(payload['call_ids']))
            return 'act-1'

        inv = self._live_faas(max_workers=2, async_invokers=1)
        inv.compute_handler.invoke.side_effect = invoke
        job = _job(
            total_calls=2,
            chunksize=1,
            data_byte_ranges=[(0, 0), (1, 1)],
        )
        try:
            futures = inv.run_job(job)
            _wait_until(lambda: len(invoked) == 2)
            assert len(futures) == 2
            assert all(f.invoked for f in futures)
            inv.job_monitor.start.assert_called_once_with(
                fs=futures,
                job_id='M000',
                chunksize=1,
                generate_tokens=True,
            )
        finally:
            inv.stop()
            inv.executor.shutdown(wait=True)

    def test_failed_invoke_returns_token_and_retries(self, monkeypatch):
        monkeypatch.setattr('lithops.invokers.time.sleep', lambda *_: None)
        invoked = []
        lock = threading.Lock()
        attempts = {'n': 0}

        def invoke(payload):
            with lock:
                invoked.append(list(payload['call_ids']))
                attempts['n'] += 1
                if attempts['n'] == 1:
                    return None
            return 'act-1'

        inv = self._live_faas()
        inv.max_workers = 0
        inv.compute_handler.invoke.side_effect = invoke
        job = _job(total_calls=1, chunksize=1)
        try:
            inv._invoke_job(job)
            _wait_until(lambda: len(invoked) >= 2)
            with lock:
                assert invoked[0] == ['00000']
                assert invoked[1] == ['00000']
        finally:
            inv.stop()
            inv.executor.shutdown(wait=True)


class TestExtendRuntime:

    def test_skips_build_when_meta_already_exists(self):
        job = SimpleNamespace(
            runtime_name='img:tag',
            ext_runtime_uuid='abc123',
            runtime_memory=256,
            runtime_timeout=60,
        )
        compute = MagicMock()
        compute.get_runtime_key.return_value = 'rk'
        internal = MagicMock()
        internal.get_runtime_meta.return_value = _matching_runtime_meta()
        extend_runtime(job, compute, internal)
        assert job.runtime_name == 'img:abc123'
        compute.build_runtime.assert_not_called()
        compute.deploy_runtime.assert_not_called()

    def test_builds_and_deploys_when_meta_missing(self, tmp_path, monkeypatch):
        local = tmp_path / 'ext'
        local.mkdir()
        job = SimpleNamespace(
            runtime_name='img:tag',
            ext_runtime_uuid='abc123',
            runtime_memory=256,
            runtime_timeout=60,
            local_tmp_dir=str(local),
        )
        compute = MagicMock()
        compute.get_runtime_key.return_value = 'rk'
        compute.deploy_runtime.return_value = _matching_runtime_meta()
        internal = MagicMock()
        internal.get_runtime_meta.return_value = None
        monkeypatch.chdir(tmp_path)
        extend_runtime(job, compute, internal)
        compute.build_runtime.assert_called_once()
        compute.deploy_runtime.assert_called_once()
        internal.put_runtime_meta.assert_called_once()
        assert not local.exists()
        assert job.runtime_name == 'img:abc123'

    def test_restores_cwd_if_build_runtime_raises(self, tmp_path, monkeypatch):
        local = tmp_path / 'ext'
        local.mkdir()
        job = SimpleNamespace(
            runtime_name='img:tag',
            ext_runtime_uuid='abc123',
            runtime_memory=256,
            runtime_timeout=60,
            local_tmp_dir=str(local),
        )
        compute = MagicMock()
        compute.get_runtime_key.return_value = 'rk'
        compute.build_runtime.side_effect = RuntimeError('build failed')
        internal = MagicMock()
        internal.get_runtime_meta.return_value = None
        monkeypatch.chdir(tmp_path)
        cwd = os.getcwd()
        with pytest.raises(RuntimeError, match='build failed'):
            extend_runtime(job, compute, internal)
        assert os.getcwd() == cwd
