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

import json
import logging
import queue
import threading
import time
from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from lithops.monitoring import JobMonitor
from lithops.monitoring.backends.rabbitmq import RabbitmqMonitor
from lithops.monitoring.backends.storage import StorageMonitor
from lithops.monitoring.backends import resolve_backend
from lithops.monitoring.monitor import (
    LOG_INTERVAL,
    Monitor,
    PollingMessageMonitor,
    _is_finished,
    _is_started,
    _status_id,
)
from lithops.monitoring.backends.rabbitmq import rabbitmq as rabbitmq_backend
from lithops.monitoring.backends.redis import redis as redis_backend
from lithops.monitoring.backends.aws_sqs import aws_sqs as sqs_backend
from lithops.monitoring.backends.azure_queue import azure_queue as azure_backend
from lithops.monitoring.backends.gcp_pubsub import gcp_pubsub as pubsub_backend
from lithops.utils import (
    _future_id,
    monitoring_queue_name,
    monitoring_queues,
    remote_invoker_queue_name,
)


class FakeFuture:
    def __init__(self, job_id, invoked=False, running=False, ready=False,
                 success=False, done=False, executor_id='sess-0', call_id='00000',
                 execution_timeout=10, activation_id=None):
        self.job_id = job_id
        self.invoked = invoked
        self.running = running
        self.ready = ready
        self.success = success
        self.done = done
        self.executor_id = executor_id
        self.call_id = call_id
        self.execution_timeout = execution_timeout
        self.activation_id = activation_id
        self._call_status = None
        self._new_futures = None
        self._status_query_count = 0

    def _set_running(self, call_status):
        self._call_status = call_status
        self.activation_id = call_status.get('activation_id')
        self.running = True
        self.invoked = False

    def _set_ready(self, call_status):
        self._call_status = call_status
        self.ready = True
        self.running = False

    def _set_futures(self, call_status):
        self._call_status = call_status
        self.ready = True
        self._new_futures = ['nested']


@contextmanager
def _client(module, factory, value):
    """
    Points a backend's client factory at a fake.

    The clients are built by a module-level factory rather than taken out of
    the config: a test seam that lives in the user's configuration is one
    more key every backend has to remember to filter out before handing the
    section to its SDK
    """
    with patch.object(module, factory, return_value=value):
        yield


def _monitor():
    return Monitor(
        executor_id='sess-0',
        internal_storage=None,
        token_bucket_q=None,
        job_chunksize={},
        generate_tokens=False,
        config={},
    )


class TestMonitorFuturesTracking:

    def test_add_futures_tracks_jobs(self):
        monitor = _monitor()
        first = FakeFuture('M000')
        second = FakeFuture('M000')
        third = FakeFuture('M001')

        monitor.add_futures([first, second, third])

        assert monitor.futures == {first, second, third}
        assert monitor.present_jobs == {'M000', 'M001'}

    def test_add_futures_leaves_an_earlier_snapshot_alone(self):
        """
        The monitor thread lists the storage prefix of every job in
        present_jobs; growing that very set from another thread is what
        used to raise "Set changed size during iteration"
        """
        monitor = _monitor()
        monitor.add_futures([FakeFuture('M000')])
        snapshot = monitor.present_jobs
        monitor.add_futures([FakeFuture('M001')])
        assert snapshot == {'M000'}
        assert monitor.present_jobs == {'M000', 'M001'}

    def test_present_jobs_can_be_iterated_while_futures_are_added(self):
        monitor = _monitor()
        monitor.add_futures([FakeFuture(f'M{i:03d}') for i in range(50)])
        errors = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    for _job_id in monitor.present_jobs:
                        pass
                except RuntimeError as exc:
                    errors.append(exc)
                    return

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            for i in range(50, 1500):
                monitor.add_futures([FakeFuture(f'M{i:04d}')])
        finally:
            stop.set()
            thread.join(timeout=5)
        assert not errors

    def test_concurrent_adds_do_not_lose_a_job(self):
        """
        Guards the invariant, not the race: replacing present_jobs is a
        read-modify-write, so the rebind is locked to stop two submitting
        threads from reading the same set and dropping each other's job.
        A job missing from it is never listed and its futures never get a
        status. The interleaving is too narrow to provoke here, so this
        only pins the result down
        """
        monitor = _monitor()
        expected = {f'M{i:03d}' for i in range(200)}
        barrier = threading.Barrier(4)

        def adder(job_ids):
            barrier.wait()
            for job_id in job_ids:
                monitor.add_futures([FakeFuture(job_id)])

        jobs = sorted(expected)
        threads = [
            threading.Thread(target=adder, args=(jobs[i::4],))
            for i in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert monitor.present_jobs == expected

    def test_remove_futures_drops_job_ids_from_removed_set(self):
        monitor = _monitor()
        keep = FakeFuture('M000', done=True)
        drop = FakeFuture('M001', done=True)
        monitor.add_futures([keep, drop])

        monitor.remove_futures([drop])

        assert monitor.futures == {keep}
        assert monitor.present_jobs == {'M000'}

    def test_remove_futures_keeps_job_id_while_siblings_remain(self):
        monitor = _monitor()
        keep = FakeFuture('M000', done=True)
        drop = FakeFuture('M000', done=True)
        monitor.add_futures([keep, drop])

        monitor.remove_futures([drop])

        assert monitor.futures == {keep}
        assert monitor.present_jobs == {'M000'}

    def test_remove_futures_drops_job_id_when_last_sibling_is_removed(self):
        monitor = _monitor()
        last = FakeFuture('M000', done=True)
        other = FakeFuture('M001', done=True)
        monitor.add_futures([last, other])

        monitor.remove_futures([last])

        assert monitor.futures == {other}
        assert monitor.present_jobs == {'M001'}

    def test_all_ready_true_when_every_future_is_terminal(self):
        monitor = _monitor()
        monitor.add_futures([
            FakeFuture('M000', ready=True),
            FakeFuture('M000', success=True),
            FakeFuture('M000', done=True),
        ])
        assert monitor._all_ready() is True

    def test_all_ready_false_when_any_pending(self):
        monitor = _monitor()
        monitor.add_futures([
            FakeFuture('M000', ready=True),
            FakeFuture('M000'),
        ])
        assert monitor._all_ready() is False

    def test_all_ready_iterates_a_snapshot(self):
        """
        The futures set is read from the monitor thread and written from the
        threads that submit jobs. Every reader takes a snapshot under the
        lock, so a concurrent add can no longer raise "Set changed size
        during iteration" in the middle of a check
        """
        monitor = _monitor()
        monitor.add_futures([FakeFuture('M000', call_id=f'{i:05d}')
                             for i in range(200)])
        errors = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    monitor._all_ready()
                except RuntimeError as exc:
                    errors.append(exc)
                    return

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            for i in range(200, 2000):
                monitor.add_futures([FakeFuture('M001', call_id=f'{i:05d}')])
        finally:
            stop.set()
            thread.join(timeout=5)
        assert not errors


class TestJobMonitor:

    def test_defaults_to_storage_monitor_without_config(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)
        assert job_monitor.type == 'storage'
        assert job_monitor.storage_backend == 'localhost'
        assert StorageMonitor.prepare_config(None, storage) == {
            'monitoring_interval': 2
        }

    def test_start_creates_monitor_and_records_chunksize(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)

        instance = MagicMock()
        instance.is_alive.return_value = False
        job_monitor.MonitorClass = MagicMock(return_value=instance)
        job_monitor.MonitorClass.prepare_config.return_value = {
            'monitoring_interval': 2
        }

        futures = [FakeFuture('M000')]
        job_monitor.start(futures, job_id='M000', chunksize=4, generate_tokens=True)

        assert job_monitor.job_chunksize['M000'] == 4
        job_monitor.MonitorClass.assert_called_once()
        kwargs = job_monitor.MonitorClass.call_args.kwargs
        assert kwargs['generate_tokens'] is True
        assert kwargs['config'] == {'monitoring_interval': 2}
        instance.add_futures.assert_called_once_with(futures)
        instance.start.assert_called_once()

    def test_start_reuses_live_monitor(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)

        live = MagicMock()
        live.is_alive.return_value = True
        job_monitor.monitor = live
        job_monitor.MonitorClass = MagicMock()

        futures = [FakeFuture('M001')]
        job_monitor.start(futures, job_id='M001', chunksize=1)

        job_monitor.MonitorClass.assert_not_called()
        live.add_futures.assert_called_once_with(futures)
        live.start.assert_not_called()

    def test_rabbitmq_type_uses_backend_section_as_monitor_config(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        config = {
            'lithops': {'monitoring': 'rabbitmq'},
            'rabbitmq': {'amqp_url': 'amqp://guest@localhost'},
        }
        job_monitor = JobMonitor('sess-0', storage, config=config)
        assert job_monitor.type == 'rabbitmq'
        assert job_monitor.MonitorClass is RabbitmqMonitor
        assert RabbitmqMonitor.prepare_config(config, storage) == {
            'amqp_url': 'amqp://guest@localhost'
        }

        instance = MagicMock()
        instance.is_alive.return_value = False
        job_monitor.MonitorClass = MagicMock(return_value=instance)
        job_monitor.MonitorClass.prepare_config.return_value = {
            'amqp_url': 'amqp://guest@localhost'
        }
        job_monitor.start([FakeFuture('M000')])
        assert job_monitor.MonitorClass.call_args.kwargs['config'] == {
            'amqp_url': 'amqp://guest@localhost'
        }

    def test_remove_and_stop_are_noops_without_a_live_monitor(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)
        job_monitor.remove([FakeFuture('M000')])
        job_monitor.stop()

    def test_stop_does_not_wait_for_a_live_monitor(self):
        """
        stop() runs after every wait() whose futures are all done, not only
        at shutdown. Joining there made the caller wait out a poll interval
        of the backend every time; the thread is a daemon and winds down on
        its own
        """
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)
        live = MagicMock()
        live.is_alive.return_value = True
        job_monitor.monitor = live
        job_monitor.stop()
        live.stop.assert_called_once()
        live.join.assert_not_called()

    def test_cleanup_waits_for_the_monitor_before_deleting(self):
        """
        The queue, topic or key is deleted under the thread that reads from
        it otherwise
        """
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)
        live = MagicMock()
        live.is_alive.side_effect = [True, False]
        job_monitor.monitor = live
        job_monitor.cleanup()
        live.stop.assert_called_once()
        live.join.assert_called_once_with(timeout=JobMonitor.STOP_TIMEOUT)
        assert live.method_calls.index(('cleanup', (), {})) > \
            live.method_calls.index(('join', (), {'timeout': JobMonitor.STOP_TIMEOUT}))

    def test_a_stopped_monitor_is_replaced_not_revived(self):
        """
        Its loop would return on the next round without ever picking the new
        futures up. The old thread is waited for first: two threads reading
        the same queue split the statuses between them, and the one on its
        way out takes what it reads to the grave
        """
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)

        stopped = MagicMock()
        stopped.should_run = False
        stopped.is_alive.side_effect = [True, False, False]
        job_monitor.monitor = stopped

        fresh = MagicMock()
        fresh.is_alive.return_value = False
        job_monitor.MonitorClass = MagicMock(return_value=fresh)
        job_monitor.MonitorClass.prepare_config.return_value = {}

        job_monitor.start([FakeFuture('M001')])

        stopped.join.assert_called_once_with(timeout=JobMonitor.STOP_TIMEOUT)
        assert job_monitor.monitor is fresh
        fresh.start.assert_called_once()

    def test_stop_releases_resources_of_a_finished_monitor(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)
        finished = MagicMock()
        finished.is_alive.return_value = False
        job_monitor.monitor = finished
        job_monitor.stop()
        finished.stop.assert_called_once()
        finished.join.assert_not_called()

    def test_cleanup_delegates_to_the_backend(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)
        job_monitor.cleanup()
        backend = MagicMock()
        job_monitor.monitor = backend
        job_monitor.cleanup()
        backend.cleanup.assert_called_once()

    def test_is_alive_without_a_started_monitor(self):
        """
        wait() asks this of the monitor of the executor it was called on,
        which has no thread of its own until something is invoked through it
        """
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)
        assert job_monitor.monitor is None
        assert job_monitor.is_alive() is False

    def test_unknown_backend_raises(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        with pytest.raises(ValueError, match='Unknown monitoring backend'):
            JobMonitor(
                'sess-0', storage,
                config={'lithops': {'monitoring': 'nope'}},
            )

    def test_backend_kwarg_overrides_config(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor(
            'sess-0', storage,
            backend='storage',
            config={'lithops': {'monitoring': 'rabbitmq'}},
        )
        assert job_monitor.type == 'storage'
        assert job_monitor.MonitorClass is StorageMonitor


class TestMonitoringQueueName:
    """
    The remote invoker follows the calls of the client's executor from
    inside a worker. A message taken off a queue is gone, so the two of
    them reading the same one would split the statuses between them and
    leave the client waiting on calls it never hears about again
    """

    def test_the_invoker_queue_is_not_the_executor_queue(self):
        assert (
            remote_invoker_queue_name('sess-0')
            != monitoring_queue_name('sess-0')
        )

    def test_a_monitor_reads_its_executor_queue_by_default(self):
        monitor = _monitor()
        assert monitor.monitoring_queue_name() == monitoring_queue_name('sess-0')

    def test_the_config_can_name_the_queue_instead(self):
        monitor = Monitor(
            'sess-0', None, queue.Queue(), {}, False,
            {'queue_name': remote_invoker_queue_name('sess-0')},
        )
        assert monitor.monitoring_queue_name() == 'lithops-sess-0-invoker'

    def test_every_message_backend_honours_the_name(self):
        from lithops.tests.mp_fakeredis import FakeRedis
        from lithops.monitoring.backends.redis import RedisMonitor
        from lithops.monitoring.backends.aws_sqs import SqsMonitor

        named = remote_invoker_queue_name('sess-0')
        sqs = MagicMock()
        sqs.create_queue.return_value = {'QueueUrl': 'url'}
        built = []
        with _client(redis_backend, 'redis_client', FakeRedis()):
            built.append(RedisMonitor(
                'sess-0', None, queue.Queue(), {}, False,
                {'queue_name': named},
            ))
        with _client(sqs_backend, 'sqs_client', sqs):
            built.append(SqsMonitor(
                'sess-0', None, queue.Queue(), {}, False,
                {'queue_name': named},
            ))
        for monitor in built:
            assert monitor.queue == named, type(monitor).__name__

    def test_job_monitor_passes_the_name_without_touching_the_config(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        config = {'lithops': {'monitoring': 'redis'}, 'redis': {}}
        named = remote_invoker_queue_name('sess-0')

        with _client(redis_backend, 'redis_client', MagicMock()):
            job_monitor = JobMonitor(
                'sess-0', storage, config=config, queue_name=named
            )
            job_monitor.prepare()
            assert job_monitor.monitor.queue == named
            # prepare_config() hands back the caller's own section
            assert 'queue_name' not in config['redis']

            default = JobMonitor('sess-0', storage, config=config)
            default.prepare()
            assert default.monitor.queue == monitoring_queue_name('sess-0')


class TestMonitorHelpers:

    def test_future_and_status_ids_match(self):
        future = FakeFuture('M000', call_id='00007')
        status = {
            'executor_id': 'sess-0',
            'job_id': 'M000',
            'call_id': '00007',
        }
        assert _future_id(future) == _status_id(status) == ('sess-0', 'M000', '00007')

    def test_is_finished_and_is_started(self):
        pending = FakeFuture('M000', invoked=True)
        running = FakeFuture('M000', running=True)
        ready = FakeFuture('M000', ready=True)
        assert _is_finished(pending) is False
        assert _is_started(pending) is False
        assert _is_started(running) is True
        assert _is_finished(ready) is True
        assert _is_started(ready) is True


class TestTimeoutAndStatusLog:

    @pytest.fixture(autouse=True)
    def _propagate_monitor_logs(self):
        """
        Lets caplog see the monitor debug log. Other tests in the suite
        run setup_lithops_logger(), which stops the 'lithops' logger
        from propagating to the root handler caplog installs, so without
        this the assertions below either fail or pass vacuously
        """
        lithops_logger = logging.getLogger('lithops')
        propagate = lithops_logger.propagate
        lithops_logger.propagate = True
        try:
            yield
        finally:
            lithops_logger.propagate = propagate

    def test_timeout_checker_marks_expired_running_future_ready(self):
        monitor = _monitor()
        future = FakeFuture('M000', running=True, execution_timeout=1, activation_id='act-1')
        future._call_status = {'worker_start_tstamp': time.time() - 100}
        monitor._future_timeout_checker([future])
        assert future.ready is True
        assert future._call_status['exception'] is True
        assert future._call_status['type'] == '__end__'

    def test_timeout_checker_ignores_futures_without_call_status(self):
        monitor = _monitor()
        future = FakeFuture('M000', running=True)
        monitor._future_timeout_checker([future])
        assert future.ready is False

    def test_print_status_log_is_silent_without_futures(self, caplog):
        monitor = _monitor()
        with caplog.at_level(logging.DEBUG, logger='lithops.monitoring.monitor'):
            monitor._print_status_log()
        assert caplog.records == []

    def test_print_status_log_emits_the_first_snapshot(self, caplog):
        monitor = _monitor()
        monitor.add_futures([FakeFuture('M000', invoked=True)])
        with caplog.at_level(logging.DEBUG, logger='lithops.monitoring.monitor'):
            monitor._print_status_log()
        assert 'Pending: 1' in caplog.text
        assert monitor._last_status_counts == (1, 0, 0)

    def test_print_status_log_repeats_after_the_interval(self, caplog):
        monitor = _monitor()
        monitor.add_futures([FakeFuture('M000', invoked=True)])
        monitor._print_status_log()
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger='lithops.monitoring.monitor'):
            monitor._print_status_log()
        assert caplog.records == []

        monitor._last_status_log_time -= LOG_INTERVAL + 1
        with caplog.at_level(logging.DEBUG, logger='lithops.monitoring.monitor'):
            monitor._print_status_log()
        assert 'Pending: 1' in caplog.text

    def test_print_status_log_throttles_count_changes_until_the_interval(
        self, caplog
    ):
        monitor = _monitor()
        future = FakeFuture('M000', invoked=True)
        monitor.add_futures([future])
        monitor._print_status_log()
        future.invoked = False
        future.running = True
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger='lithops.monitoring.monitor'):
            monitor._print_status_log()
        assert caplog.records == []
        assert monitor._last_status_counts == (0, 1, 0)

    def test_print_status_log_emits_when_the_job_completes(self, caplog):
        monitor = _monitor()
        future = FakeFuture('M000', invoked=True)
        monitor.add_futures([future])
        monitor._print_status_log()
        future.invoked = False
        future.ready = True
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger='lithops.monitoring.monitor'):
            monitor._print_status_log()
        assert 'Done: 1' in caplog.text

    def test_print_status_log_force_emits_a_changed_snapshot(self, caplog):
        monitor = _monitor()
        future = FakeFuture('M000', invoked=True)
        monitor.add_futures([future])
        monitor._print_status_log()
        future.invoked = False
        future.running = True
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger='lithops.monitoring.monitor'):
            monitor._print_status_log(force=True)
        assert 'Running: 1' in caplog.text

    def test_print_status_log_force_keeps_quiet_when_nothing_moved(self, caplog):
        monitor = _monitor()
        monitor.add_futures([FakeFuture('M000', invoked=True, ready=True)])
        monitor._print_status_log()
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger='lithops.monitoring.monitor'):
            monitor._print_status_log(force=True)
        assert caplog.records == []

    def test_check_new_futures_tracks_and_indexes_the_nested_ones(self):
        """
        The nested futures go through add_futures(), so their job id reaches
        present_jobs and their call ids reach the index. Adding them straight
        to the set left the storage monitor never listing their prefix, and
        the message monitors with no way to match their statuses
        """
        nested = FakeFuture('A000', call_id='00042', executor_id='sess-0-1')

        class Outer(FakeFuture):
            def _set_futures(self, call_status):
                self._call_status = call_status
                self.ready = True
                self._new_futures = [nested]

        monitor = _monitor()
        future = Outer('M000')
        monitor.add_futures([future])
        assert monitor._check_new_futures({'type': '__end__'}, future) is False
        assert monitor._check_new_futures({'new_futures': 'x'}, future) is True
        assert nested in monitor.futures
        assert 'A000' in monitor.present_jobs
        assert monitor.future_by_id(_future_id(nested)) is nested


class TestStorageMonitorTokensAndTags:

    def _storage(self, generate_tokens=True, chunksize=2):
        storage = MagicMock()
        q = queue.Queue()
        return StorageMonitor(
            executor_id='sess-0',
            internal_storage=storage,
            token_bucket_q=q,
            job_chunksize={'M000': chunksize},
            generate_tokens=generate_tokens,
            config={'monitoring_interval': 1},
        )

    def test_generate_tokens_skips_when_disabled(self):
        monitor = self._storage(generate_tokens=False)
        monitor._generate_tokens({(('sess-0', 'M000', '00000'), 'w1')}, set())
        assert monitor.token_bucket_q.empty()

    def test_generate_tokens_emits_when_chunk_completes(self):
        monitor = self._storage()
        running = {
            (('sess-0', 'M000', '00000'), 'w1'),
            (('sess-0', 'M000', '00001'), 'w1'),
        }
        done = {('sess-0', 'M000', '00000'), ('sess-0', 'M000', '00001')}
        monitor.present_jobs.add('M000')
        monitor._generate_tokens(running, done)
        assert monitor.token_bucket_q.get_nowait() == '#'
        assert 'w1' in monitor.workers_done

    def test_generate_tokens_waits_for_full_chunk_then_does_not_repeat(self):
        monitor = self._storage()
        running = {
            (('sess-0', 'M000', '00000'), 'w1'),
            (('sess-0', 'M000', '00001'), 'w1'),
        }
        first_done = {('sess-0', 'M000', '00000')}
        all_done = first_done | {('sess-0', 'M000', '00001')}
        monitor.present_jobs.add('M000')
        monitor._generate_tokens(running, first_done)
        assert monitor.token_bucket_q.empty()
        monitor._generate_tokens(running, all_done)
        assert monitor.token_bucket_q.get_nowait() == '#'
        monitor._generate_tokens(running, all_done)
        assert monitor.token_bucket_q.empty()

    def test_generate_tokens_one_per_worker(self):
        monitor = self._storage(chunksize=1)
        running = {
            (('sess-0', 'M000', '00000'), 'w1'),
            (('sess-0', 'M000', '00001'), 'w2'),
        }
        done = {('sess-0', 'M000', '00000'), ('sess-0', 'M000', '00001')}
        monitor.present_jobs.add('M000')
        monitor._generate_tokens(running, done)
        tokens = [
            monitor.token_bucket_q.get_nowait(),
            monitor.token_bucket_q.get_nowait(),
        ]
        assert tokens == ['#', '#']
        assert monitor.token_bucket_q.empty()

    def test_generate_tokens_skips_job_not_present(self):
        monitor = self._storage()
        running = {
            (('sess-0', 'M000', '00000'), 'w1'),
            (('sess-0', 'M000', '00001'), 'w1'),
        }
        done = {('sess-0', 'M000', '00000'), ('sess-0', 'M000', '00001')}
        monitor._generate_tokens(running, done)
        assert monitor.token_bucket_q.empty()

    def test_tag_future_as_running_from_callids(self):
        monitor = self._storage()
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        callids_running = {(('sess-0', 'M000', '00000'), 'act-9')}
        monitor._tag_future_as_running(callids_running)
        assert future.running is True
        assert future.activation_id == 'act-9'

    def test_tag_future_as_ready_queries_matching_ids(self):
        monitor = self._storage()
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        monitor.internal_storage.get_call_status.return_value = {
            'type': '__end__',
            'activation_id': 'act-9',
        }
        monitor._tag_future_as_ready({('sess-0', 'M000', '00000')})
        assert future.ready is True
        assert future._call_status['activation_id'] == 'act-9'

    def test_tag_future_as_ready_queries_only_matching_ids_when_not_near_complete(
        self,
    ):
        monitor = self._storage()
        futures = [
            FakeFuture('M000', invoked=True, call_id=f'{i:05d}')
            for i in range(20)
        ]
        monitor.add_futures(futures)
        monitor.internal_storage.get_call_status.return_value = {
            'type': '__end__',
            'activation_id': 'act',
        }
        monitor._tag_future_as_ready({('sess-0', 'M000', '00003')})
        queried = [
            call.args for call in monitor.internal_storage.get_call_status.call_args_list
        ]
        assert queried == [('sess-0', 'M000', '00003')]
        assert futures[3].ready is True
        assert futures[0].ready is False

    def test_poll_and_process_returns_new_done_ids_and_tags(self):
        monitor = self._storage()
        monitor._generate_tokens = MagicMock()
        monitor._tag_future_as_running = MagicMock()
        monitor._tag_future_as_ready = MagicMock()
        monitor._print_status_log = MagicMock()
        running = {(('sess-0', 'M000', '00000'), 'w1')}
        done = {('sess-0', 'M000', '00000')}
        monitor.internal_storage.get_job_status.return_value = (running, done)
        new = monitor._poll_and_process_job_status()
        assert new == done
        monitor.internal_storage.get_job_status.assert_called_once_with(
            'sess-0', job_ids=set()
        )
        monitor._generate_tokens.assert_called_once_with(running, done)
        monitor._tag_future_as_running.assert_called_once_with(running)
        monitor._tag_future_as_ready.assert_called_once_with(done)
        monitor._print_status_log.assert_called_once_with()

    def test_poll_and_process_emits_token_when_chunk_completes(self):
        monitor = self._storage()
        future0 = FakeFuture('M000', invoked=True, call_id='00000')
        future1 = FakeFuture('M000', invoked=True, call_id='00001')
        monitor.add_futures([future0, future1])
        running = {
            (('sess-0', 'M000', '00000'), 'w1'),
            (('sess-0', 'M000', '00001'), 'w1'),
        }
        done = {('sess-0', 'M000', '00000'), ('sess-0', 'M000', '00001')}
        monitor.internal_storage.get_job_status.return_value = (running, done)
        monitor.internal_storage.get_call_status.return_value = {
            'type': '__end__',
            'activation_id': 'w1',
        }
        monitor._print_status_log = MagicMock()
        monitor._poll_and_process_job_status()
        assert monitor.token_bucket_q.get_nowait() == '#'
        assert future0.ready is True
        assert future1.ready is True

    def test_run_sleeps_shorter_when_new_done_then_polls_after_loop(self):
        monitor = self._storage()
        polls = []

        def poll():
            polls.append(1)
            if len(polls) == 1:
                return {('sess-0', 'M000', '00000')}
            monitor.should_run = False
            return set()

        monitor._poll_and_process_job_status = poll
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            return monitor.should_run

        monitor.sleep = sleep
        monitor.run()
        assert sleeps == [0.2]
        assert len(polls) == 3

    def test_run_skips_sleep_and_swallows_final_poll_errors_after_stop(self):
        monitor = self._storage()
        polls = []

        def poll():
            polls.append(1)
            monitor.should_run = False
            if len(polls) > 1:
                raise RuntimeError('storage gone')
            return set()

        monitor._poll_and_process_job_status = poll
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            return monitor.should_run

        monitor.sleep = sleep
        monitor.run()
        assert sleeps == []
        assert len(polls) == 2


class TestRabbitmqMonitorTags:

    def _rabbit(self):
        """
        A monitor built through its own __init__, with pika mocked out, so
        it has the attributes the class actually relies on
        """
        pika = rabbitmq_backend.pika
        with patch.object(pika, 'URLParameters'), \
                patch.object(pika, 'BlockingConnection'):
            return RabbitmqMonitor(
                'sess-0', None, queue.Queue(), {'M000': 1}, True,
                {'amqp_url': 'amqp://guest:guest@localhost:5672'},
            )

    def test_the_declared_queue_is_the_one_the_workers_publish_to(self):
        # The monitor declares and consumes one queue; the workers derive the
        # names they publish to from the same helper. If these two ever drift
        # apart, every rabbitmq job hangs without a word
        pika = rabbitmq_backend.pika
        with patch.object(pika, 'URLParameters'), \
                patch.object(pika, 'BlockingConnection') as connection:
            monitor = RabbitmqMonitor(
                'sess-0', None, queue.Queue(), {'M000': 1}, True,
                {'amqp_url': 'amqp://guest:guest@localhost:5672'},
            )

        assert monitor.queue == monitoring_queue_name('sess-0')
        assert monitoring_queues('sess-0') == [monitor.queue]
        declared = connection.return_value.channel.return_value.queue_declare
        assert declared.call_args.kwargs['queue'] == monitor.queue

    def test_tag_running_and_ready_by_call_status(self):
        monitor = self._rabbit()
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        init = {
            'type': '__init__',
            'executor_id': 'sess-0',
            'job_id': 'M000',
            'call_id': '00000',
            'activation_id': 'act-1',
        }
        monitor._tag_future_as_running(init)
        assert future.running is True
        end = {
            'type': '__end__',
            'executor_id': 'sess-0',
            'job_id': 'M000',
            'call_id': '00000',
            'activation_id': 'act-1',
            'chunksize': 1,
        }
        monitor._tag_future_as_ready(end)
        assert future.ready is True

    def test_generate_tokens_emits_after_chunksize_completions(self):
        monitor = self._rabbit()
        status = {
            'activation_id': 'w1',
            'executor_id': 'sess-0',
            'job_id': 'M000',
            'call_id': '00000',
            'chunksize': 1,
        }
        monitor._generate_tokens(status)
        assert monitor.token_bucket_q.get_nowait() == '#'

    def test_generate_tokens_waits_for_chunksize_completions(self):
        monitor = self._rabbit()
        first = {
            'activation_id': 'w1',
            'executor_id': 'sess-0',
            'job_id': 'M000',
            'call_id': '00000',
            'chunksize': 2,
        }
        monitor._generate_tokens(first)
        assert monitor.token_bucket_q.empty()
        second = dict(first, call_id='00001')
        monitor._generate_tokens(second)
        assert monitor.token_bucket_q.get_nowait() == '#'

    def _consuming(self, monitor, *payloads):
        """
        Points the monitor at a channel whose consume() generator yields
        these payloads and then reports the inactivity timeout
        """
        channel = MagicMock()
        messages = [(MagicMock(), None, p.encode()) for p in payloads]
        messages.append((None, None, None))
        channel.consume.return_value = iter(messages)
        connection = MagicMock()
        connection.is_closed = False
        connection.channel.return_value = channel
        monitor.connection = connection
        monitor.POLL_TIMEOUT = 0.01
        return channel

    def test_a_poll_applies_every_consumed_status(self):
        monitor = self._rabbit()
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        _init, init_raw = _status(kind='__init__')
        _end, end_raw = _status(kind='__end__')
        channel = self._consuming(monitor, init_raw, end_raw)

        monitor._poll_once()

        assert future.ready is True
        assert channel.consume.call_args.kwargs['inactivity_timeout'] == 0.01
        assert channel.consume.call_args.kwargs['auto_ack'] is True

    def test_a_nested_status_read_early_is_applied_in_the_same_batch(self):
        """
        The consumer only returns once the queue has gone quiet, so a held
        status has to be applied as each message is handled rather than
        after the batch, or it waits a whole inactivity timeout
        """
        monitor = self._rabbit()
        nested_id = 'sess-0-A000-00000-1'
        nested = FakeFuture('M000', running=True, executor_id=nested_id)

        class Outer(FakeFuture):
            def _set_futures(self, call_status):
                self._call_status = call_status
                self.ready = True
                self._new_futures = [nested]

        monitor.add_futures([Outer('A000', invoked=True, call_id='00000')])

        nested_end, _raw = _status(kind='__end__')
        nested_end['executor_id'] = nested_id
        outer_end, _raw = _status(call_id='00000', kind='__end__')
        outer_end['job_id'] = 'A000'
        outer_end['new_futures'] = True

        # The nested __end__ is read first, before its future is known
        self._consuming(
            monitor, json.dumps(nested_end), json.dumps(outer_end)
        )
        monitor._poll_once()

        assert nested.ready is True

    def test_stop_closes_the_connection_from_the_monitor_thread(self):
        """
        pika's BlockingConnection belongs to one thread, so the close that
        unblocks the consumer is handed to it instead of being called here
        """
        monitor = self._rabbit()
        connection = MagicMock()
        monitor.connection = connection
        monitor.stop()
        assert monitor.should_run is False
        connection.add_callback_threadsafe.assert_called_once_with(
            connection.close
        )
        connection.close.assert_not_called()


def _status(call_id='00000', kind='__init__', chunksize=1):
    payload = {
        'type': kind,
        'executor_id': 'sess-0',
        'job_id': 'M000',
        'call_id': call_id,
        'activation_id': 'act-1',
        'chunksize': chunksize,
        'worker_start_tstamp': time.time(),
    }
    return payload, json.dumps(payload)


def _run_polling_until_idle(monitor, payloads):
    """
    Feeds a polling monitor the given payloads then stops it, so run()
    returns without waiting for an external stop()
    """
    pending = list(payloads)

    def receive(timeout):
        if pending:
            yield pending.pop(0)
        else:
            monitor.should_run = False

    monitor._receive_messages = receive
    monitor.run()


class TestPollingMessageMonitor:

    def test_run_keeps_going_after_all_ready_until_stop(self):
        class FakePoll(PollingMessageMonitor):
            backend_name = 'fake'
            POLL_TIMEOUT = 0.01

            def _receive_messages(self, timeout):
                time.sleep(timeout)
                return []

        monitor = FakePoll(
            'sess-0', None, queue.Queue(), {}, False, {}
        )
        future = FakeFuture('M000', invoked=True, ready=True)
        monitor.add_futures([future])
        thread = threading.Thread(target=monitor.run)
        thread.start()
        thread.join(timeout=0.05)
        assert thread.is_alive()
        monitor.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()

    def test_stop_does_not_wait_for_a_blocking_read(self):
        """
        SQS, Pub/Sub and Azure Queue block in their own read, which nothing
        outside the thread can cut short. stop() runs after every wait()
        whose futures are all done, so waiting for one there cost a poll
        interval per map. cleanup() is what waits, once per executor
        """
        class Blocking(PollingMessageMonitor):
            backend_name = 'blocking'
            POLL_TIMEOUT = 1

            def _receive_messages(self, timeout):
                time.sleep(self.POLL_TIMEOUT)
                return []

        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        job_monitor = JobMonitor('sess-0', storage)
        job_monitor.MonitorClass = Blocking
        with patch.object(Blocking, 'prepare_config', return_value={}):
            job_monitor.prepare()
        monitor = job_monitor.monitor
        monitor.start()
        try:
            time.sleep(0.2)
            started = time.time()
            job_monitor.stop()
            assert time.time() - started < 0.5
            assert monitor.should_run is False
        finally:
            job_monitor.cleanup()
        assert not monitor.is_alive()

    def test_an_idle_wait_ends_as_soon_as_the_monitor_is_stopped(self):
        """
        Azure Queue does not long poll at all: the loop does the waiting.
        Sleeping through it meant the thread outlived stop() by a whole
        poll interval, which cleanup() then had to sit through
        """
        class NoLongPoll(PollingMessageMonitor):
            backend_name = 'no-long-poll'
            POLL_TIMEOUT = 30

            def _receive_messages(self, timeout):
                return []

        monitor = NoLongPoll('sess-0', None, queue.Queue(), {}, False, {})
        thread = threading.Thread(target=monitor.run)
        thread.start()
        time.sleep(0.2)
        started = time.time()
        monitor.stop()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert time.time() - started < 1

    def test_a_status_arriving_before_its_future_is_not_lost(self):
        """
        A nested executor publishes its call statuses to the queue of every
        executor up the chain, so they can arrive before the __end__ of the
        outer call that tells this monitor those futures exist. A queue read
        is destructive, so a status dropped here would hang wait() for ever
        """
        class FakePoll(PollingMessageMonitor):
            backend_name = 'fake'
            POLL_TIMEOUT = 0.01

            def _receive_messages(self, timeout):
                return []

        monitor = FakePoll('sess-0', None, queue.Queue(), {}, False, {})
        nested = FakeFuture(
            'M000', running=True, executor_id='sess-0-A000-00000-1'
        )
        # The nested __end__ lands while only the outer future is tracked
        payload, _raw = _status(kind='__end__')
        payload['executor_id'] = 'sess-0-A000-00000-1'
        monitor._apply_status_message(payload)
        assert nested.ready is False

        # ...and is applied as soon as the future shows up
        monitor.add_futures([nested])
        assert nested.ready is True

    def test_a_held_status_frees_a_worker_token_only_once(self):
        """
        A status held back and applied later must be counted for the token
        bucket exactly once: counting it on arrival as well would free the
        worker before its whole chunk is really done
        """
        class FakePoll(PollingMessageMonitor):
            backend_name = 'fake'

            def _receive_messages(self, timeout):
                return []

        tokens = queue.Queue()
        monitor = FakePoll(
            'sess-0', None, tokens, {'M000': 2}, True, {}
        )
        payload, _raw = _status(kind='__end__', chunksize=2)

        # Arrives before its future is tracked: held, and no token yet
        monitor._apply_status_message(payload)
        assert tokens.qsize() == 0

        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        assert future.ready is True
        # One call of a two-call chunk is done, so still no token
        assert tokens.qsize() == 0

        # The second call completes the chunk, and frees exactly one token
        second, _raw = _status(call_id='00001', kind='__end__', chunksize=2)
        monitor.add_futures([
            FakeFuture('M000', invoked=True, call_id='00001')
        ])
        monitor._apply_status_message(second)
        assert tokens.qsize() == 1

    def test_stop_does_not_delete_cleanup_does_once(self):
        class FakePoll(PollingMessageMonitor):
            backend_name = 'fake'
            deletes = 0

            def _receive_messages(self, timeout):
                return []

            def _delete_resources(self):
                type(self).deletes += 1

        monitor = FakePoll(
            'sess-0', None, queue.Queue(), {}, False, {}
        )
        monitor.stop()
        assert FakePoll.deletes == 0
        monitor.cleanup()
        monitor.cleanup()
        assert FakePoll.deletes == 1

    def test_run_paces_a_backend_that_does_not_long_poll(self):
        """
        Azure Queue Storage returns right away on an empty queue, so the
        loop has to do the waiting itself instead of spinning on it
        """
        class FakePoll(PollingMessageMonitor):
            backend_name = 'fake'
            POLL_TIMEOUT = 0.2
            polls = 0

            def _receive_messages(self, timeout):
                type(self).polls += 1
                return []

        monitor = FakePoll('sess-0', None, queue.Queue(), {}, False, {})
        thread = threading.Thread(target=monitor.run)
        thread.start()
        time.sleep(0.5)
        monitor.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert FakePoll.polls <= 4

    def test_run_survives_a_failing_poll(self):
        """
        A poll that raises must not take the thread down: nothing else
        moves the futures along, so wait() would block for ever
        """
        class FakePoll(PollingMessageMonitor):
            backend_name = 'fake'
            POLL_TIMEOUT = 0.01
            polls = 0

            def _receive_messages(self, timeout):
                type(self).polls += 1
                if type(self).polls == 1:
                    raise ConnectionError('transient')
                _payload, raw = _status(kind='__end__')
                yield raw

        monitor = FakePoll('sess-0', None, queue.Queue(), {}, False, {})
        future = FakeFuture('M000', invoked=True, running=True)
        monitor.add_futures([future])
        thread = threading.Thread(target=monitor.run)
        thread.start()
        for _ in range(200):
            if future.ready:
                break
            time.sleep(0.01)
        assert thread.is_alive()
        assert future.ready is True
        monitor.stop()
        thread.join(timeout=2)


class TestMessageLossAndRecovery:
    """
    RabbitMQ acknowledges on delivery and a Redis BLPOP removes the entry,
    so those two deliver a status at most once. Anything that drops a
    message between the read and the future is a call that never finishes
    """

    class FakePoll(PollingMessageMonitor):
        backend_name = 'fake'
        POLL_TIMEOUT = 0.01
        STORAGE_SWEEP_INTERVAL = 0

        def _receive_messages(self, timeout):
            return []

    def _monitor(self, storage=None, tokens=None, chunksize=None):
        return self.FakePoll(
            'sess-0', storage, tokens or queue.Queue(),
            chunksize or {}, chunksize is not None, {},
        )

    def test_applying_a_status_does_not_iterate_the_futures_set(self):
        """
        Guards the cause, which a race is too narrow to provoke on demand.

        Tagging used to scan the futures set, and the threads that submit
        jobs grow that very set. "Set changed size during iteration"
        surfaced in the poll loop as a logged error, and the message it was
        carrying was already off the queue: the call then stayed running
        until its execution timeout, or for ever. Tagging is a lookup in an
        index kept beside the set now, so there is no iteration left to
        interrupt
        """
        class NeverIterated(set):
            def __iter__(self):
                raise AssertionError('the futures set was iterated')

        monitor = self._monitor()
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        with monitor._futures_lock:
            monitor.futures = NeverIterated(set(monitor.futures))

        init, _raw = _status(kind='__init__')
        monitor._apply_status_message(init)
        assert future.running is True
        end, _raw = _status(kind='__end__')
        monitor._apply_status_message(end)
        assert future.ready is True

    def test_applying_statuses_while_futures_are_added_loses_nothing(self):
        """
        Pins the result the invariant above buys: every status finds its
        future, and none is left held, while another thread keeps adding
        """
        monitor = self._monitor()
        tracked = [
            FakeFuture('M000', invoked=True, call_id=f'{i:05d}')
            for i in range(300)
        ]
        monitor.add_futures(tracked)

        errors = []
        applied = threading.Event()

        def apply_statuses():
            try:
                for future in tracked:
                    payload, _raw = _status(
                        call_id=future.call_id, kind='__end__'
                    )
                    monitor._apply_status_message(payload)
            except Exception as exc:  # noqa: BLE001 - recorded, not handled
                errors.append(exc)
            finally:
                applied.set()

        thread = threading.Thread(target=apply_statuses)
        thread.start()
        for i in range(300, 2000):
            monitor.add_futures([FakeFuture('M001', call_id=f'{i:05d}')])
        applied.wait(timeout=10)
        thread.join(timeout=5)

        assert not errors
        assert all(f.ready for f in tracked)
        assert not monitor._held_status

    def test_a_redelivered_end_frees_one_token_not_two(self):
        """
        SQS, Pub/Sub and Azure Queue redeliver a message whose status was
        applied but whose delete or ack did not go through. Counting the
        same call twice would free the worker before its chunk is done
        """
        tokens = queue.Queue()
        monitor = self._monitor(tokens=tokens, chunksize={'M000': 2})
        monitor.add_futures([
            FakeFuture('M000', invoked=True, call_id='00000'),
            FakeFuture('M000', invoked=True, call_id='00001'),
        ])

        first, _raw = _status(call_id='00000', kind='__end__', chunksize=2)
        monitor._apply_status_message(first)
        monitor._apply_status_message(dict(first))
        assert tokens.qsize() == 0

        second, _raw = _status(call_id='00001', kind='__end__', chunksize=2)
        monitor._apply_status_message(second)
        assert tokens.qsize() == 1
        monitor._apply_status_message(dict(second))
        assert tokens.qsize() == 1

    def test_a_status_of_a_tracked_future_is_never_held(self):
        """
        A second __init__ of a call that is already running used to be held
        back, because tagging reported "no match" for a future it had in
        fact found. Held statuses of futures that never come back are a leak
        """
        monitor = self._monitor()
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        payload, _raw = _status(kind='__init__')
        monitor._apply_status_message(payload)
        monitor._apply_status_message(dict(payload))
        assert future.running is True
        assert monitor._held_status == {}

    def test_held_statuses_do_not_grow_without_bound(self):
        monitor = self._monitor()
        monitor.MAX_HELD_STATUS = 10
        for i in range(50):
            payload, _raw = _status(call_id=f'{i:05d}', kind='__end__')
            monitor._apply_status_message(payload)
        assert len(monitor._held_status) == 10
        # The newest are the ones kept
        assert ('sess-0', 'M000', '00049') in monitor._held_status

    def test_the_storage_sweep_recovers_a_lost_end(self):
        """
        The worker writes every __end__ to the storage as well. Without
        reading it back, a lost message shows up as an execution timeout for
        a call that in fact succeeded
        """
        storage = MagicMock()
        monitor = self._monitor(storage=storage)
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])

        done = {('sess-0', 'M000', '00000')}
        storage.get_job_status.return_value = (set(), done)
        storage.get_call_status.return_value = {
            'type': '__end__', 'activation_id': 'act-1', 'chunksize': 1,
        }

        monitor._storage_sweep()

        assert future.ready is True
        storage.get_job_status.assert_called_once_with(
            'sess-0', job_ids={'M000'}
        )
        storage.get_call_status.assert_called_once_with(
            'sess-0', 'M000', '00000'
        )

    def test_the_storage_sweep_leaves_a_call_that_is_still_running(self):
        storage = MagicMock()
        monitor = self._monitor(storage=storage)
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        storage.get_job_status.return_value = (set(), set())

        monitor._storage_sweep()

        assert future.ready is False
        storage.get_call_status.assert_not_called()

    def test_the_storage_sweep_recovers_a_call_that_never_reported_running(self):
        """
        Losing both statuses of a call is what hangs wait() for ever: the
        timeout checker only looks at futures it saw start
        """
        storage = MagicMock()
        monitor = self._monitor(storage=storage)
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        monitor._future_timeout_checker()
        assert future.ready is False

        storage.get_job_status.return_value = (
            set(), {('sess-0', 'M000', '00000')}
        )
        storage.get_call_status.return_value = {'type': '__end__'}
        monitor._storage_sweep()
        assert future.ready is True

    def test_the_sweep_only_looks_once_the_channel_has_gone_quiet(self):
        """
        A channel that is delivering has nothing for the sweep to recover,
        and a sweep lists every status key of every live job: on a large map
        that is a page of listing per thousand calls, every interval
        """
        storage = MagicMock()
        storage.get_job_status.return_value = (set(), set())
        monitor = self._monitor(storage=storage)
        monitor.STORAGE_SWEEP_INTERVAL = 30
        monitor._sweep_interval = 30
        monitor.add_futures([FakeFuture('M000', invoked=True)])

        # A status just arrived, so there is nothing to look for
        monitor._last_message_tstamp = time.time()
        monitor._sweep_storage(time.time() - 3600)
        storage.get_job_status.assert_not_called()

        # ...and the channel then goes quiet
        monitor._last_message_tstamp = time.time() - 31
        monitor._sweep_storage(time.time() - 3600)
        storage.get_job_status.assert_called_once()

    def test_applying_a_status_counts_as_the_channel_being_alive(self):
        monitor = self._monitor()
        monitor._last_message_tstamp = 0
        monitor.add_futures([
            FakeFuture('M000', invoked=True, call_id='00000')
        ])
        payload, _raw = _status(kind='__init__')
        monitor._apply_status_message(payload)
        assert monitor._last_message_tstamp > 0

    def test_a_sweep_that_finds_nothing_backs_off(self):
        """
        A long-running job is quiet by nature, and sweeping it every minute
        costs a full listing each time for nothing
        """
        storage = MagicMock()
        storage.get_job_status.return_value = (set(), set())
        monitor = self._monitor(storage=storage)
        monitor.STORAGE_SWEEP_INTERVAL = 10
        monitor.MAX_SWEEP_INTERVAL = 40
        monitor._sweep_interval = 10
        monitor.add_futures([FakeFuture('M000', invoked=True)])

        intervals = []
        for _ in range(5):
            monitor._last_message_tstamp = 0
            monitor._sweep_storage(0)
            intervals.append(monitor._sweep_interval)
        assert intervals == [20, 40, 40, 40, 40]

    def test_a_sweep_that_recovers_something_goes_back_to_the_base_interval(self):
        storage = MagicMock()
        monitor = self._monitor(storage=storage)
        monitor.STORAGE_SWEEP_INTERVAL = 10
        monitor._sweep_interval = 80
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        storage.get_job_status.return_value = (
            set(), {('sess-0', 'M000', '00000')}
        )
        storage.get_call_status.return_value = {'type': '__end__'}

        monitor._last_message_tstamp = 0
        monitor._sweep_storage(0)

        assert future.ready is True
        assert monitor._sweep_interval == 10

    def test_a_failing_sweep_does_not_take_the_monitor_down(self):
        storage = MagicMock()
        storage.get_job_status.side_effect = RuntimeError('storage gone')
        monitor = self._monitor(storage=storage)
        monitor.STORAGE_SWEEP_INTERVAL = 1
        monitor.add_futures([FakeFuture('M000', invoked=True)])
        assert monitor._sweep_storage(0) > 0


class TestBackendContract:
    """
    "Adding a backend is adding a package" only holds if a package that
    does not hold up its end says so, instead of quietly monitoring nothing
    """

    def _in_backends(self, name='fake'):
        return {'__module__': f'lithops.monitoring.backends.{name}.{name}'}

    def test_backend_name_comes_from_the_package(self):
        cls = type('Good', (PollingMessageMonitor,), dict(
            self._in_backends(),
            _receive_messages=lambda self, timeout: iter(()),
        ))
        assert cls.backend_name == 'fake'

    def test_a_backend_name_that_disagrees_is_rejected(self):
        with pytest.raises(TypeError, match='backend package'):
            type('Drifted', (Monitor,), dict(
                self._in_backends(),
                backend_name='something-else',
                run=lambda self: None,
            ))

    def test_a_backend_that_consumes_nothing_is_rejected(self):
        with pytest.raises(TypeError, match='neither run'):
            type('Empty', (Monitor,), dict(self._in_backends()))

    def test_a_helper_class_can_opt_out(self):
        cls = type('Helper', (Monitor,), dict(self._in_backends()),
                   abstract=True)
        assert cls.backend_name is None

    def test_classes_outside_the_backends_package_are_left_alone(self):
        cls = type('Local', (Monitor,), {'__module__': 'somewhere.else'})
        assert cls.backend_name is None

    def test_exports_are_checked_against_the_base_classes(self):
        from lithops.monitoring.backends import load_backend_attr
        module = MagicMock()
        module.MonitoringBackend = 'not a class'
        with patch(
            'lithops.monitoring.backends.importlib.import_module',
            return_value=module,
        ):
            with pytest.raises(ValueError, match='not a Monitor subclass'):
                load_backend_attr('fake', 'MonitoringBackend')

    def test_a_missing_export_is_reported(self):
        from lithops.monitoring.backends import load_backend_attr
        module = SimpleNamespace()
        with patch(
            'lithops.monitoring.backends.importlib.import_module',
            return_value=module,
        ):
            with pytest.raises(ValueError, match='exports no CallStatus'):
                load_backend_attr('fake', 'CallStatus')

    def test_every_built_in_backend_holds_up_its_end(self):
        from lithops.monitoring.backends import load_backend_attr
        from lithops.monitoring.status import CallStatus
        for name in (
            'storage', 'rabbitmq', 'redis',
            'aws_sqs', 'gcp_pubsub', 'azure_queue',
        ):
            backend = load_backend_attr(name, 'MonitoringBackend')
            status = load_backend_attr(name, 'CallStatus')
            assert backend.backend_name == name
            assert issubclass(backend, Monitor)
            assert issubclass(status, CallStatus)

    def test_the_client_and_the_worker_resolve_the_same_backend(self):
        """
        create_call_status() used to read the key straight out of the config
        while the client fell back to storage, so a config with no
        'monitoring' key had the worker raise instead of reporting
        """
        for config in (
            None, {}, {'lithops': {}}, {'lithops': {'monitoring': None}},
        ):
            assert resolve_backend(config) == 'storage'
        assert resolve_backend({'lithops': {'monitoring': 'RabbitMQ'}}) \
            == 'rabbitmq'
        assert resolve_backend({'lithops': {'monitoring': 'redis'}}, 'STORAGE') \
            == 'storage'


class TestCallStatusPublishing:

    @pytest.fixture(autouse=True)
    def _no_clients_left_over(self):
        """
        The clients are kept for the process, so one test would otherwise
        hand its client to the next
        """
        from lithops.monitoring.status import close_shared_clients
        close_shared_clients()
        yield
        close_shared_clients()

    def _job(self, backend='redis'):
        return SimpleNamespace(
            config={'lithops': {'monitoring': backend}, backend: {}},
            start_tstamp=0,
            host_submit_tstamp=0,
            call_id='00000',
            job_id='M000',
            executor_id='sess-0',
            chunksize=1,
            monitoring_queues=['lithops-sess-0'],
        )

    def _status_cls(self, publish):
        from lithops.monitoring.status import MessageCallStatus

        class Fake(MessageCallStatus):
            service_name = 'fake'
            RETRY_SLEEP = 0
            closed = 0

            def _publish(self, payload):
                publish(payload)

            def close(self):
                type(self).closed += 1

        return Fake

    def _plain_status_cls(self, publish=lambda payload: None):
        """The same, but keeping the real close() so it can be exercised"""
        from lithops.monitoring.status import MessageCallStatus

        class Plain(MessageCallStatus):
            service_name = 'plain'
            RETRY_SLEEP = 0

            def _publish(self, payload):
                publish(payload)

        return Plain

    def test_a_publish_that_keeps_failing_still_writes_to_the_storage(self):
        cls = self._status_cls(
            lambda payload: (_ for _ in ()).throw(ConnectionError('down'))
        )
        storage = MagicMock()
        status = cls(self._job(), storage)
        status.send_finish_event()
        # The client reads this back through MessageMonitor._storage_sweep()
        assert storage.put_data.call_count == 1

    def test_the_attempts_are_backed_off(self):
        attempts = []
        cls = self._status_cls(
            lambda payload: (_ for _ in ()).throw(ConnectionError('down'))
        )
        cls.RETRY_SLEEP = 0.2
        cls.MAX_RETRY_SLEEP = 1
        status = cls(self._job(), MagicMock())
        with patch(
            'lithops.monitoring.status.time.sleep', side_effect=attempts.append
        ):
            status.send_init_event()
        assert attempts == [0.2, 0.4, 0.8, 1]

    def test_the_client_is_released_after_the_last_status(self):
        cls = self._status_cls(lambda payload: None)
        status = cls(self._job(), MagicMock())
        status.send_init_event()
        assert cls.closed == 0
        status.send_finish_event()
        assert cls.closed == 1

    def test_the_client_is_released_even_when_the_last_status_fails(self):
        cls = self._status_cls(
            lambda payload: (_ for _ in ()).throw(ConnectionError('down'))
        )
        cls.RETRY_SLEEP = 0
        storage = MagicMock()
        storage.put_data.side_effect = RuntimeError('storage gone')
        status = cls(self._job(), storage)
        with pytest.raises(RuntimeError):
            status.send_finish_event()
        assert cls.closed == 1

    def test_every_backend_keeps_one_client_for_the_process(self):
        """
        A warm container runs one call after another, each building its own
        call status. Opening a connection per call costs far more than the
        publish it carries, so the client is kept and released at exit
        """
        from lithops.monitoring.status import (
            _SHARED_CLIENTS, close_shared_clients,
        )
        from lithops.monitoring.backends.redis.status import RedisCallStatus
        from lithops.monitoring.backends.aws_sqs.status import SqsCallStatus
        from lithops.monitoring.backends.azure_queue.status import (
            AzureQueueCallStatus,
        )
        from lithops.monitoring.backends.gcp_pubsub.status import (
            GcpPubsubCallStatus,
        )

        cases = [
            (RedisCallStatus, 'redis', redis_backend, 'redis_client',
             'client'),
            (SqsCallStatus, 'aws_sqs', sqs_backend, 'sqs_client', 'client'),
            (AzureQueueCallStatus, 'azure_queue', azure_backend,
             'queue_service', 'service'),
            (GcpPubsubCallStatus, 'gcp_pubsub', pubsub_backend,
             'pubsub_clients', 'publisher'),
        ]
        for cls, name, module, factory, attr in cases:
            close_shared_clients()
            built = MagicMock()
            value = (built, MagicMock()) if factory == 'pubsub_clients' \
                else built
            with patch.object(module, factory, return_value=value) as build:
                for _ in range(3):
                    status = cls(self._job(name), MagicMock())
                    getattr(status, attr)
                    status.send_finish_event()
                assert build.call_count == 1, name
                assert built.close.called is False, name
            assert _SHARED_CLIENTS, name
            close_shared_clients()
            assert built.close.called or built.stop.called, name

    def test_reuse_can_be_turned_off(self):
        """
        The escape hatch for a runtime where a client that outlives the call
        does not survive the fork of the next one
        """
        from lithops.monitoring.status import (
            REUSE_CLIENTS_ENV, _SHARED_CLIENTS,
        )

        cls = self._plain_status_cls()
        clients = []
        with patch.dict('os.environ', {REUSE_CLIENTS_ENV: '0'}):
            for _ in range(3):
                status = cls(self._job(), MagicMock())
                client = MagicMock()
                clients.append(client)
                status.__dict__['client'] = status.obtain_client(
                    'client', lambda c=client: c
                )
                status.send_finish_event()

        assert len(clients) == 3
        assert not _SHARED_CLIENTS
        for client in clients:
            client.close.assert_called_once()

    def test_one_client_serves_every_call_of_the_process(self):
        """
        A worker runs the calls of its chunk one after another
        """
        cls = self._plain_status_cls()
        built = []
        for _ in range(5):
            status = cls(self._job(), MagicMock())
            status.obtain_client('client', lambda: built.append(1) or 'c')
            status.send_finish_event()
        assert len(built) == 1

    def test_a_shared_client_is_not_closed_with_the_call(self):
        from lithops.monitoring.status import close_shared_clients

        client = MagicMock()
        cls = self._plain_status_cls()
        status = cls(self._job(), MagicMock())
        status.__dict__['client'] = status.obtain_client(
            'client', lambda: client
        )
        status.send_finish_event()
        client.close.assert_not_called()
        close_shared_clients()
        client.close.assert_called_once()

    def test_two_brokers_do_not_share_a_client(self):
        """
        The settings are part of what makes a client shareable: a process
        reporting to two brokers must not publish to one through the other
        """
        cls = self._plain_status_cls()
        first = cls(self._job(), MagicMock())
        first.config['redis'] = {'host': 'one'}
        second = cls(self._job(), MagicMock())
        second.config['redis'] = {'host': 'two'}
        a = first.obtain_client('client', MagicMock)
        b = second.obtain_client('client', MagicMock)
        assert a is not b

    def test_a_client_that_failed_is_not_handed_to_the_next_call(self):
        cls = self._plain_status_cls()
        status = cls(self._job(), MagicMock())
        first = status.obtain_client('client', MagicMock)
        status.discard_client('client')
        second = cls(self._job(), MagicMock()).obtain_client(
            'client', MagicMock
        )
        assert second is not first

    def test_rabbitmq_replaces_a_connection_that_died(self):
        """
        The broker drops a connection idle past the heartbeat, and a long
        function is exactly that. A shared one must be replaced, not reused
        """
        from lithops.monitoring.backends.rabbitmq.status import (
            RabbitmqCallStatus,
        )

        job = self._job('rabbitmq')
        job.config['rabbitmq'] = {'amqp_url': 'amqp://guest@localhost'}
        dead_conn, dead_ch = MagicMock(), MagicMock()
        dead_conn.is_open = False
        live_conn, live_ch = MagicMock(), MagicMock()
        live_conn.is_open = live_ch.is_open = True

        status = RabbitmqCallStatus(job, MagicMock())
        status.obtain_client('_amqp', lambda: (dead_conn, dead_ch))
        with patch.object(
            status, '_connect', return_value=(live_conn, live_ch)
        ):
            assert status._channel() is live_ch

        # ...and the replacement is what the next call gets
        nxt = RabbitmqCallStatus(job, MagicMock())
        assert nxt.obtain_client('_amqp', MagicMock) == (live_conn, live_ch)

    def test_releasing_a_client_that_was_never_built_builds_nothing(self):
        from lithops.monitoring.backends.redis.status import RedisCallStatus

        with patch.object(redis_backend, 'redis_client') as build:
            status = RedisCallStatus(self._job(), MagicMock())
            status.close()
            build.assert_not_called()

    def test_no_client_is_built_before_the_first_status(self):
        """
        The worker builds the call status and then forks the JobRunner off.
        A network client that already exists at that point is what the
        fork() safety check of the Apple frameworks aborts the child over
        """
        from lithops.monitoring.backends.redis.status import RedisCallStatus
        from lithops.monitoring.backends.aws_sqs.status import SqsCallStatus
        from lithops.monitoring.backends.azure_queue.status import (
            AzureQueueCallStatus,
        )
        from lithops.monitoring.backends.gcp_pubsub.status import (
            GcpPubsubCallStatus,
        )

        cases = [
            (RedisCallStatus, 'redis', redis_backend, 'redis_client'),
            (SqsCallStatus, 'aws_sqs', sqs_backend, 'sqs_client'),
            (AzureQueueCallStatus, 'azure_queue', azure_backend,
             'queue_service'),
            (GcpPubsubCallStatus, 'gcp_pubsub', pubsub_backend,
             'pubsub_clients'),
        ]
        for cls, name, module, factory in cases:
            with patch.object(module, factory) as build:
                cls(self._job(name), MagicMock())
                assert build.call_count == 0, name


class TestRedisMonitor:

    def _redis(self, client):
        from lithops.monitoring.backends.redis import RedisMonitor
        with _client(redis_backend, 'redis_client', client):
            return RedisMonitor(
                'sess-0', None, queue.Queue(), {'M000': 1}, True, {},
            )

    def test_the_list_is_the_one_the_workers_publish_to(self):
        from lithops.tests.mp_fakeredis import FakeRedis
        monitor = self._redis(FakeRedis())
        assert monitor.queue == monitoring_queue_name('sess-0')
        assert monitoring_queues('sess-0') == [monitor.queue]

    def test_run_processes_init_and_end(self):
        from lithops.tests.mp_fakeredis import FakeRedis
        client = FakeRedis()
        monitor = self._redis(client)
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        _, init_body = _status(kind='__init__')
        _, end_body = _status(kind='__end__')
        _run_polling_until_idle(monitor, [init_body, end_body])
        assert future.ready is True

    def test_stop_keeps_the_list_cleanup_deletes_it(self):
        from lithops.tests.mp_fakeredis import FakeRedis
        client = FakeRedis()
        monitor = self._redis(client)
        client.rpush(monitor.queue, b'leftover')
        monitor.stop()
        assert client.llen(monitor.queue) == 1
        monitor.cleanup()
        assert client.llen(monitor.queue) == 0
        monitor.cleanup()
        assert client.llen(monitor.queue) == 0

    def test_call_status_publishes_to_every_queue_in_the_chain(self):
        from lithops.monitoring.backends.redis.status import RedisCallStatus
        from lithops.tests.mp_fakeredis import FakeRedis
        client = FakeRedis()
        job = SimpleNamespace(
            config={'lithops': {'monitoring': 'redis'}, 'redis': {}},
            start_tstamp=0,
            host_submit_tstamp=0,
            call_id='00000',
            job_id='M000',
            executor_id='sess-0',
            chunksize=1,
            monitoring_queues=['lithops-parent', 'lithops-sess-0'],
        )
        with _client(redis_backend, 'redis_client', client):
            status = RedisCallStatus(job, MagicMock())
            status.status['type'] = '__init__'
            status._publish('{"type": "__init__"}')
        assert client.llen('lithops-parent') == 1
        assert client.llen('lithops-sess-0') == 1

    def test_only_the_keys_redis_accepts_reach_the_client(self):
        """
        The 'redis' section is shared with the storage, multiprocessing and
        joblib backends, which put keys of their own in it. redis.Redis()
        raises TypeError on any it does not know, so the section is filtered
        by what the constructor takes rather than by a list of exclusions
        """
        from lithops.monitoring.backends.redis.redis import _redis_params
        params = _redis_params({
            'host': 'localhost',
            'port': 6379,
            'password': 'secret',
            'storage_bucket': 'storage',
            'user_agent': 'lithops',
            'some_backend_key': 'value',
        })
        assert params == {
            'host': 'localhost', 'port': 6379, 'password': 'secret'
        }

    def test_a_blocking_read_takes_the_rest_of_the_batch_with_it(self):
        """
        BLPOP hands over one status at a time. Draining what is already on
        the list in the same round trip is what keeps a map of n calls from
        costing n round trips, and n sweeps of the futures, to monitor
        """
        from lithops.tests.mp_fakeredis import FakeRedis
        client = FakeRedis()
        monitor = self._redis(client)
        for i in range(5):
            _payload, raw = _status(call_id=f'{i:05d}', kind='__end__')
            client.rpush(monitor.queue, raw.encode())

        received = list(monitor._receive_messages(1))

        assert len(received) == 5
        assert client.llen(monitor.queue) == 0

    def test_the_batch_comes_off_the_list_in_one_lpop(self):
        """
        LPOP takes a count from Redis 6.2 on, and returns only what is
        there, so a thousand statuses cost the same round trip as one. Over
        a network the round trips are the whole cost of monitoring a map
        """
        client = MagicMock()
        _payload, raw = _status(kind='__end__')
        client.blpop.return_value = (b'q', raw.encode())
        client.lpop.return_value = [raw.encode()] * 4
        monitor = self._redis(client)

        received = list(monitor._receive_messages(1))

        assert len(received) == 5
        client.lpop.assert_called_once_with(
            monitor.queue, monitor.BATCH_SIZE - 1
        )
        client.pipeline.assert_not_called()

    def test_a_redis_older_than_6_2_falls_back_to_a_pipeline(self):
        client = MagicMock()
        _payload, raw = _status(kind='__end__')
        client.blpop.return_value = (b'q', raw.encode())
        client.lpop.side_effect = TypeError('lpop() takes 2 arguments')
        pipe = client.pipeline.return_value
        pipe.execute.return_value = [raw.encode(), None]
        monitor = self._redis(client)

        received = list(monitor._receive_messages(1))

        assert len(received) == 2
        assert monitor._lpop_count is False
        client.pipeline.assert_called_once()

    def test_a_client_that_cannot_pipeline_falls_back_to_one_at_a_time(self):
        from lithops.tests.mp_fakeredis import FakeRedis
        client = FakeRedis()
        monitor = self._redis(client)
        _payload, raw = _status(kind='__end__')
        client.rpush(monitor.queue, raw.encode())
        with patch.object(
            monitor.client, 'pipeline', side_effect=AttributeError('no')
        ):
            received = list(monitor._receive_messages(1))
        assert received == [raw]
        assert monitor._can_batch is False

    def test_stop_drops_the_connections_under_the_blocking_read(self):
        """
        stop() runs after every wait() that finds its futures done, not only
        at shutdown. Leaving the BLPOP to reach its own timeout costs a
        second or two every time, which is most of a test run
        """
        client = MagicMock()
        monitor = self._redis(client)
        monitor.stop()
        assert monitor.should_run is False
        client.connection_pool.disconnect.assert_called_once()
        monitor._close_receiver()
        client.close.assert_called_once()

    def test_the_monitor_does_not_share_its_client(self):
        """
        stop() tears the pool down, so the client has to be this monitor's
        own: the redis section is shared with the storage, multiprocessing
        and joblib backends, and taking their connections with it would
        break them
        """
        import redis as redis_sdk
        from lithops.monitoring.backends.redis.redis import redis_client
        first = redis_client({'host': 'localhost'})
        second = redis_client({'host': 'localhost'})
        assert isinstance(first, redis_sdk.Redis)
        assert first is not second
        assert first.connection_pool is not second.connection_pool

    def test_a_stopped_monitor_still_deletes_its_list(self):
        """
        cleanup() runs after stop(), so it talks to a pool that was just
        disconnected. redis-py opens a connection again by itself
        """
        client = MagicMock()
        monitor = self._redis(client)
        monitor.stop()
        monitor.cleanup()
        client.delete.assert_called_once_with(monitor.queue)


class TestSqsMonitor:

    def _sqs(self, client):
        from lithops.monitoring.backends.aws_sqs import SqsMonitor
        client.create_queue.return_value = {'QueueUrl': 'https://sqs/lithops-sess-0'}
        with _client(sqs_backend, 'sqs_client', client):
            return SqsMonitor(
                'sess-0', None, queue.Queue(), {'M000': 1}, True,
                {'region': 'us-east-1'},
            )

    def test_the_created_queue_is_the_one_the_workers_publish_to(self):
        client = MagicMock()
        monitor = self._sqs(client)
        assert monitor.queue == monitoring_queue_name('sess-0')
        client.create_queue.assert_called_once_with(QueueName='lithops-sess-0')
        assert monitor.queue_url == 'https://sqs/lithops-sess-0'

    def test_run_processes_init_and_end_and_deletes_messages(self):
        client = MagicMock()
        monitor = self._sqs(client)
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        _, init_body = _status(kind='__init__')
        _, end_body = _status(kind='__end__')
        client.receive_message.side_effect = [
            {'Messages': [
                {'Body': init_body, 'ReceiptHandle': 'h1'},
                {'Body': end_body, 'ReceiptHandle': 'h2'},
            ]},
            {'Messages': []},
        ]
        orig = monitor._receive_messages

        def receive(timeout):
            items = list(orig(timeout))
            for item in items:
                yield item
            if not items:
                monitor.should_run = False

        monitor._receive_messages = receive
        monitor.run()
        assert future.ready is True
        deleted = [c.kwargs['ReceiptHandle'] for c in client.delete_message.call_args_list]
        assert deleted == ['h1', 'h2']

    def test_stop_keeps_the_queue_cleanup_deletes_it(self):
        client = MagicMock()
        monitor = self._sqs(client)
        monitor.stop()
        client.delete_queue.assert_not_called()
        assert monitor.queue_url == 'https://sqs/lithops-sess-0'
        monitor.cleanup()
        client.delete_queue.assert_called_once_with(
            QueueUrl='https://sqs/lithops-sess-0'
        )
        assert monitor.queue_url is None

    def test_call_status_sends_to_every_queue_in_the_chain(self):
        from lithops.monitoring.backends.aws_sqs.status import SqsCallStatus
        client = MagicMock()
        client.get_queue_url.side_effect = [
            {'QueueUrl': 'https://sqs/parent'},
            {'QueueUrl': 'https://sqs/own'},
        ]
        job = SimpleNamespace(
            config={'lithops': {'monitoring': 'aws_sqs'}, 'aws_sqs': {}},
            start_tstamp=0,
            host_submit_tstamp=0,
            call_id='00000',
            job_id='M000',
            executor_id='sess-0',
            chunksize=1,
            monitoring_queues=['lithops-parent', 'lithops-sess-0'],
        )
        with _client(sqs_backend, 'sqs_client', client):
            status = SqsCallStatus(job, MagicMock())
            status._publish('{"type": "__init__"}')
        urls = [c.kwargs['QueueUrl'] for c in client.send_message.call_args_list]
        assert urls == ['https://sqs/parent', 'https://sqs/own']


class TestGcpPubsubMonitor:

    def _monitor(self, publisher, subscriber):
        from lithops.monitoring.backends.gcp_pubsub import GcpPubsubMonitor
        with patch.object(
            pubsub_backend, 'pubsub_clients',
            return_value=(publisher, subscriber),
        ):
            return GcpPubsubMonitor(
                'sess-0', None, queue.Queue(), {'M000': 1}, True,
                {'project_name': 'proj'},
            )

    def test_the_created_topic_is_the_one_the_workers_publish_to(self):
        publisher = MagicMock()
        subscriber = MagicMock()
        monitor = self._monitor(publisher, subscriber)
        assert monitor.queue == monitoring_queue_name('sess-0')
        publisher.create_topic.assert_called_once_with(
            name='projects/proj/topics/lithops-sess-0'
        )
        subscriber.create_subscription.assert_called_once_with(
            name='projects/proj/subscriptions/lithops-sess-0',
            topic='projects/proj/topics/lithops-sess-0',
            ack_deadline_seconds=30,
        )

    def test_run_processes_init_and_end_and_acks_messages(self):
        publisher = MagicMock()
        subscriber = MagicMock()
        monitor = self._monitor(publisher, subscriber)
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        _, init_body = _status(kind='__init__')
        _, end_body = _status(kind='__end__')

        def _msg(body, ack_id):
            item = MagicMock()
            item.ack_id = ack_id
            item.message.data = body.encode('utf-8')
            return item

        first = MagicMock()
        first.received_messages = [_msg(init_body, 'a1'), _msg(end_body, 'a2')]
        empty = MagicMock()
        empty.received_messages = []
        subscriber.pull.side_effect = [first, empty]
        orig = monitor._receive_messages

        def receive(timeout):
            items = list(orig(timeout))
            for item in items:
                yield item
            if not items:
                monitor.should_run = False

        monitor._receive_messages = receive
        monitor.run()
        assert future.ready is True
        subscriber.acknowledge.assert_called_once_with(
            subscription='projects/proj/subscriptions/lithops-sess-0',
            ack_ids=['a1', 'a2'],
        )

    def test_stop_keeps_the_topic_cleanup_deletes_it(self):
        publisher = MagicMock()
        subscriber = MagicMock()
        monitor = self._monitor(publisher, subscriber)
        monitor.stop()
        publisher.delete_topic.assert_not_called()
        subscriber.delete_subscription.assert_not_called()
        monitor.cleanup()
        subscriber.delete_subscription.assert_called_once_with(
            subscription='projects/proj/subscriptions/lithops-sess-0'
        )
        publisher.delete_topic.assert_called_once_with(
            topic='projects/proj/topics/lithops-sess-0'
        )
        assert monitor.topic_path is None
        assert monitor.subscription_path is None

    def test_call_status_publishes_to_every_topic_in_the_chain(self):
        from lithops.monitoring.backends.gcp_pubsub.status import GcpPubsubCallStatus
        publisher = MagicMock()
        job = SimpleNamespace(
            config={
                'lithops': {'monitoring': 'gcp_pubsub'},
                'gcp_pubsub': {'project_name': 'proj'},
            },
            start_tstamp=0,
            host_submit_tstamp=0,
            call_id='00000',
            job_id='M000',
            executor_id='sess-0',
            chunksize=1,
            monitoring_queues=['lithops-parent', 'lithops-sess-0'],
        )
        with patch.object(
            pubsub_backend, 'pubsub_clients',
            return_value=(publisher, MagicMock()),
        ):
            status = GcpPubsubCallStatus(job, MagicMock())
            status._publish('{"type": "__init__"}')
        topics = [c.args[0] for c in publisher.publish.call_args_list]
        assert topics == [
            'projects/proj/topics/lithops-parent',
            'projects/proj/topics/lithops-sess-0',
        ]
        for call in publisher.publish.call_args_list:
            assert call.args[1] == b'{"type": "__init__"}'


class TestAzureQueueMonitor:

    def _monitor(self, service):
        from lithops.monitoring.backends.azure_queue import AzureQueueMonitor
        queue_client = MagicMock()
        service.create_queue.return_value = queue_client
        with _client(azure_backend, 'queue_service', service):
            monitor = AzureQueueMonitor(
                'sess-0', None, queue.Queue(), {'M000': 1}, True, {},
            )
        return monitor, queue_client

    def test_the_created_queue_is_the_one_the_workers_publish_to(self):
        service = MagicMock()
        monitor, _queue_client = self._monitor(service)
        assert monitor.queue == monitoring_queue_name('sess-0')
        service.create_queue.assert_called_once_with('lithops-sess-0')

    def test_run_processes_init_and_end_and_deletes_messages(self):
        service = MagicMock()
        monitor, queue_client = self._monitor(service)
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        _, init_body = _status(kind='__init__')
        _, end_body = _status(kind='__end__')

        def _msg(body):
            item = MagicMock()
            item.content = body
            return item

        queue_client.receive_messages.side_effect = [
            [_msg(init_body), _msg(end_body)],
            [],
        ]
        orig = monitor._receive_messages

        def receive(timeout):
            items = list(orig(timeout))
            for item in items:
                yield item
            if not items:
                monitor.should_run = False

        monitor._receive_messages = receive
        monitor.run()
        assert future.ready is True
        assert queue_client.delete_message.call_count == 2

    def test_stop_keeps_the_queue_cleanup_deletes_it(self):
        service = MagicMock()
        monitor, _queue_client = self._monitor(service)
        monitor.stop()
        service.delete_queue.assert_not_called()
        monitor.cleanup()
        service.delete_queue.assert_called_once_with('lithops-sess-0')
        assert monitor.queue_client is None

    def test_call_status_sends_to_every_queue_in_the_chain(self):
        from lithops.monitoring.backends.azure_queue.status import (
            AzureQueueCallStatus,
        )
        parent = MagicMock()
        own = MagicMock()
        service = MagicMock()
        service.get_queue_client.side_effect = lambda name: {
            'lithops-parent': parent,
            'lithops-sess-0': own,
        }[name]
        job = SimpleNamespace(
            config={'lithops': {'monitoring': 'azure_queue'}, 'azure_queue': {}},
            start_tstamp=0,
            host_submit_tstamp=0,
            call_id='00000',
            job_id='M000',
            executor_id='sess-0',
            chunksize=1,
            monitoring_queues=['lithops-parent', 'lithops-sess-0'],
        )
        with _client(azure_backend, 'queue_service', service):
            status = AzureQueueCallStatus(job, MagicMock())
            status._publish('{"type": "__init__"}')
        parent.send_message.assert_called_once_with('{"type": "__init__"}')
        own.send_message.assert_called_once_with('{"type": "__init__"}')


class TestAzureQueueNames:
    """
    Azure Queue Storage takes 3 to 63 lowercase letters, digits and single
    hyphens. A name that does not fit is rejected by the service, and the
    executor that built it fails at construction
    """

    def test_a_plain_name_only_loses_its_case(self):
        from lithops.monitoring.backends.azure_queue.azure_queue import (
            azure_queue_name,
        )
        assert azure_queue_name('lithops-ABC123-0') == 'lithops-abc123-0'

    def test_characters_azure_rejects_are_replaced(self):
        from lithops.monitoring.backends.azure_queue.azure_queue import (
            azure_queue_name,
        )
        assert azure_queue_name('lithops-a_b/c-0') == 'lithops-a-b-c-0'

    def test_a_long_name_is_cut_and_kept_unique(self):
        from lithops.monitoring.backends.azure_queue.azure_queue import (
            azure_queue_name, QUEUE_NAME_MAX_LEN,
        )
        first = azure_queue_name('lithops-' + 'a' * 90)
        second = azure_queue_name('lithops-' + 'a' * 91)
        assert len(first) == QUEUE_NAME_MAX_LEN
        assert first != second

    def test_a_short_name_is_padded_to_the_minimum(self):
        from lithops.monitoring.backends.azure_queue.azure_queue import (
            azure_queue_name,
        )
        assert len(azure_queue_name('AB')) >= 3

    def test_the_monitor_and_the_workers_agree_on_the_name(self):
        from lithops.monitoring.backends.azure_queue.azure_queue import (
            azure_queue_name,
        )
        from lithops.monitoring.backends.azure_queue.status import (
            AzureQueueCallStatus,
        )
        service = MagicMock()
        with _client(azure_backend, 'queue_service', service):
            from lithops.monitoring.backends.azure_queue import (
                AzureQueueMonitor,
            )
            monitor = AzureQueueMonitor(
                'SESS-0', None, queue.Queue(), {}, False, {},
            )
        job = SimpleNamespace(
            config={'lithops': {'monitoring': 'azure_queue'}, 'azure_queue': {}},
            start_tstamp=0, host_submit_tstamp=0, call_id='00000',
            job_id='M000', executor_id='SESS-0', chunksize=1,
            monitoring_queues=[monitoring_queue_name('SESS-0')],
        )
        with _client(azure_backend, 'queue_service', service):
            status = AzureQueueCallStatus(job, MagicMock())
            assert status._targets() == [monitor.queue]
        assert monitor.queue == azure_queue_name(
            monitoring_queue_name('SESS-0')
        )


def _localhost_redis():
    try:
        import redis
        client = redis.Redis(
            host='localhost', port=6379,
            socket_connect_timeout=0.5, socket_timeout=1,
        )
        client.ping()
        return client
    except Exception:
        return None


@pytest.mark.skipif(_localhost_redis() is None, reason='Redis is not running on localhost')
class TestRedisAgainstAServer:

    def test_publish_consume_and_delete_the_list(self):
        from lithops.monitoring.backends.redis import RedisMonitor
        from lithops.monitoring.backends.redis.status import RedisCallStatus

        client = _localhost_redis()
        list_name = monitoring_queue_name('sess-live')
        client.delete(list_name)
        try:
            monitor = RedisMonitor(
                'sess-live', None, queue.Queue(), {'M000': 1}, False,
                {'host': 'localhost'},
            )
            future = FakeFuture(
                'M000', invoked=True, call_id='00000', executor_id='sess-live'
            )
            monitor.add_futures([future])
            job = SimpleNamespace(
                config={'lithops': {'monitoring': 'redis'}, 'redis': {'host': 'localhost'}},
                start_tstamp=time.time(),
                host_submit_tstamp=time.time(),
                call_id='00000',
                job_id='M000',
                executor_id='sess-live',
                chunksize=1,
                monitoring_queues=[list_name],
            )
            status = RedisCallStatus(job, MagicMock())
            status.send_init_event()
            status.send_finish_event()
            thread = threading.Thread(target=monitor.run)
            thread.start()
            deadline = time.time() + 5
            while not future.ready and time.time() < deadline:
                time.sleep(0.05)
            assert future.ready is True
            monitor.stop()
            thread.join(timeout=5)
            monitor.cleanup()
            assert client.llen(list_name) == 0
        finally:
            client.delete(list_name)
