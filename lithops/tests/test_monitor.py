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
from unittest.mock import MagicMock, patch


from lithops.monitor import (
    LOG_INTERVAL,
    JobMonitor,
    Monitor,
    RabbitmqMonitor,
    StorageMonitor,
    _is_finished,
    _is_started,
    _status_id,
)
from lithops import monitor as rabbit_monitor_module
from lithops.utils import (
    _future_id,
    monitoring_queue_name,
    monitoring_queues,
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

    def test_all_ready_swallows_unexpected_errors(self):
        class Broken:
            @property
            def ready(self):
                raise RuntimeError('boom')

        monitor = _monitor()
        monitor.futures.add(Broken())
        assert monitor._all_ready() is False


class TestJobMonitor:

    def test_defaults_to_storage_monitor_without_config(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)
        assert job_monitor.type == 'storage'
        assert job_monitor.storage_backend == 'localhost'

    def test_start_creates_monitor_and_records_chunksize(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)

        instance = MagicMock()
        instance.is_alive.return_value = False
        job_monitor.MonitorClass = MagicMock(return_value=instance)

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

        instance = MagicMock()
        instance.is_alive.return_value = False
        job_monitor.MonitorClass = MagicMock(return_value=instance)
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

    def test_stop_joins_a_live_monitor(self):
        storage = MagicMock()
        storage.get_storage_config.return_value = {'monitoring_interval': 2}
        storage.backend = 'localhost'
        job_monitor = JobMonitor('sess-0', storage)
        live = MagicMock()
        live.is_alive.return_value = True
        job_monitor.monitor = live
        job_monitor.stop()
        live.stop.assert_called_once()
        live.join.assert_called_once_with(timeout=5)

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

    def test_print_status_log_returns_previous_when_empty(self):
        monitor = _monitor()
        assert monitor._print_status_log('prev', 3) == ('prev', 3)

    def test_print_status_log_none_log_time_is_short_circuited(self):
        monitor = _monitor()
        monitor.add_futures([FakeFuture('M000', invoked=True)])
        # Historical: `log_time > LOG_INTERVAL` is not evaluated when counts change.
        counts, log_time = monitor._print_status_log(previous_log=None, log_time=None)
        assert counts == (1, 0, 0)
        assert log_time == 0

    def test_print_status_log_repeats_after_interval(self):
        monitor = _monitor()
        monitor.add_futures([FakeFuture('M000', invoked=True)])
        first, _ = monitor._print_status_log(previous_log=None, log_time=0)
        same, log_time = monitor._print_status_log(previous_log=first, log_time=0)
        assert log_time == 0
        _, log_time = monitor._print_status_log(
            previous_log=first, log_time=LOG_INTERVAL + 1
        )
        assert log_time == 0

    def test_print_status_log_does_not_repeat_when_all_finished(self, caplog):
        monitor = _monitor()
        monitor.add_futures([FakeFuture('M000', invoked=True, ready=True)])
        first, _ = monitor._print_status_log(previous_log=None, log_time=0)
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger='lithops.monitor'):
            counts, log_time = monitor._print_status_log(
                previous_log=first, log_time=LOG_INTERVAL + 1
            )
        assert counts == first
        assert log_time == LOG_INTERVAL + 1
        assert caplog.records == []

    def test_check_new_futures_updates_tracking_set(self):
        monitor = _monitor()
        future = FakeFuture('M000')
        monitor.add_futures([future])
        assert monitor._check_new_futures({'type': '__end__'}, future) is False
        assert monitor._check_new_futures({'new_futures': 'x'}, future) is True
        assert 'nested' in monitor.futures


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
        monitor._print_status_log = MagicMock(return_value=('log', 1))
        running = {(('sess-0', 'M000', '00000'), 'w1')}
        done = {('sess-0', 'M000', '00000')}
        monitor.internal_storage.get_job_status.return_value = (running, done)
        new, prev, log_time = monitor._poll_and_process_job_status(None, 0)
        assert new == done
        monitor.internal_storage.get_job_status.assert_called_once_with(
            'sess-0', job_ids=set()
        )
        monitor._generate_tokens.assert_called_once_with(running, done)
        monitor._tag_future_as_running.assert_called_once_with(running)
        monitor._tag_future_as_ready.assert_called_once_with(done)
        assert prev == 'log'
        assert log_time == 1

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
        monitor._print_status_log = MagicMock(return_value=('log', 1))
        monitor._poll_and_process_job_status(None, 0)
        assert monitor.token_bucket_q.get_nowait() == '#'
        assert future0.ready is True
        assert future1.ready is True

    def test_run_sleeps_shorter_when_new_done_then_polls_after_loop(self):
        monitor = self._storage()
        polls = []

        def poll(previous_log, log_time):
            polls.append(1)
            if len(polls) == 1:
                return {('sess-0', 'M000', '00000')}, previous_log, log_time
            monitor.should_run = False
            return set(), previous_log, log_time

        monitor._poll_and_process_job_status = poll
        sleeps = []
        test_thread = threading.current_thread()

        def sleep(seconds):
            if threading.current_thread() is test_thread:
                sleeps.append(seconds)

        with patch('lithops.monitor.time.sleep', side_effect=sleep):
            monitor.run()
        assert sleeps == [0.2]
        assert len(polls) == 3

    def test_run_skips_sleep_and_swallows_final_poll_errors_after_stop(self):
        monitor = self._storage()
        polls = []

        def poll(previous_log, log_time):
            polls.append(1)
            monitor.should_run = False
            if len(polls) > 1:
                raise RuntimeError('storage gone')
            return set(), previous_log, log_time

        monitor._poll_and_process_job_status = poll
        sleeps = []
        test_thread = threading.current_thread()

        def sleep(seconds):
            if threading.current_thread() is test_thread:
                sleeps.append(seconds)

        with patch('lithops.monitor.time.sleep', side_effect=sleep):
            monitor.run()
        assert sleeps == []
        assert len(polls) == 2


class TestRabbitmqMonitorTags:

    def _rabbit(self):
        monitor = RabbitmqMonitor.__new__(RabbitmqMonitor)
        Monitor.__init__(
            monitor, 'sess-0', None, queue.Queue(), {'M000': 1}, True, {}
        )
        return monitor

    def test_the_declared_queue_is_the_one_the_workers_publish_to(self):
        # The monitor declares and consumes one queue; the workers derive the
        # names they publish to from the same helper. If these two ever drift
        # apart, every rabbitmq job hangs without a word
        pika = rabbit_monitor_module.pika
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

    def test_run_processes_init_and_end_until_all_ready(self):
        monitor = self._rabbit()
        future = FakeFuture('M000', invoked=True, call_id='00000')
        monitor.add_futures([future])
        monitor.queue = 'lithops-sess-0'
        monitor.should_run = True
        monitor._print_status_log = MagicMock(return_value=(None, 0))

        channel = MagicMock()
        monitor.connection = MagicMock()
        monitor.connection.channel.return_value = channel

        def consume():
            callback = channel.basic_consume.call_args[0][1]
            init = json.dumps({
                'type': '__init__',
                'executor_id': 'sess-0',
                'job_id': 'M000',
                'call_id': '00000',
                'activation_id': 'act-1',
            }).encode()
            end = json.dumps({
                'type': '__end__',
                'executor_id': 'sess-0',
                'job_id': 'M000',
                'call_id': '00000',
                'activation_id': 'act-1',
                'chunksize': 1,
            }).encode()
            callback(channel, None, None, init)
            callback(channel, None, None, end)

        channel.start_consuming.side_effect = consume
        with patch('lithops.monitor.threading.Thread'):
            monitor.run()
        assert future.ready is True
        channel.stop_consuming.assert_called()
