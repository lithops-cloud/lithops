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

import importlib
import signal
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lithops.utils import FuturesList, is_unix_system
from lithops.wait import (
    ALL_COMPLETED,
    ALWAYS,
    ANY_COMPLETED,
    WAIT_DUR_SEC,
    _as_future_list,
    _check_done,
    _create_executors_data_from_futures,
    _future_is_complete,
    _get_executor_data,
    _partition_futures,
    _poll_sleep_sec,
    _ready_futures,
    get_result,
    wait,
)

wait_mod = importlib.import_module('lithops.wait')


class FakeFuture:
    def __init__(self, *, done=False, success=False, ready=False, executor_id='sess-0',
                 job_id='M000', call_id='00000', storage_backend='localhost',
                 result=None, produce_output=True, futures=False):
        self.done = done
        self.success = success
        self.ready = ready
        self.executor_id = executor_id
        self.job_id = job_id
        self.call_id = call_id
        self._storage_config = {'backend': storage_backend}
        self._result = result
        self._produce_output = produce_output
        self.futures = futures
        self._new_futures = None

    def result(self, throw_except=True, internal_storage=None):
        self.done = True
        return self._result

    def status(self, throw_except=True, internal_storage=None):
        self.success = True
        return {'ok': True}


class TestWaitHelpers:

    def test_as_future_list_wraps_single_future(self):
        future = FakeFuture()
        assert _as_future_list(future) == [future]

    def test_as_future_list_keeps_list_and_futures_list(self):
        plain = [FakeFuture()]
        futures_list = FuturesList(plain)
        assert _as_future_list(plain) is plain
        assert _as_future_list(futures_list) is futures_list

    def test_future_is_complete_depends_on_download_results(self):
        success_only = FakeFuture(done=False, success=True)
        assert _future_is_complete(success_only, download_results=False) is True
        assert _future_is_complete(success_only, download_results=True) is False

        finished = FakeFuture(done=True, success=True)
        assert _future_is_complete(finished, download_results=True) is True

    def test_partition_preserves_order(self):
        first = FakeFuture(done=True, success=True)
        second = FakeFuture()
        third = FakeFuture(done=False, success=True)

        done, not_done = _partition_futures(
            [first, second, third], download_results=False
        )
        assert done == [first, third]
        assert not_done == [second]

        done, not_done = _partition_futures(
            [first, second, third], download_results=True
        )
        assert done == [first]
        assert not_done == [second, third]

    def test_partition_empty(self):
        assert _partition_futures([], False) == ([], [])

    def test_check_done_any_completed(self):
        pending = FakeFuture()
        finished = FakeFuture(done=True, success=True)
        assert _check_done([pending, pending], ANY_COMPLETED, False) is False
        assert _check_done([pending, finished], ANY_COMPLETED, False) is True

    def test_check_done_percentage_and_all_completed(self):
        finished = FakeFuture(done=True, success=True)
        pending = FakeFuture()
        fs = [finished, pending]
        assert _check_done(fs, 50, False) is True
        assert _check_done(fs, ALL_COMPLETED, False) is False
        assert _check_done([finished, finished], ALL_COMPLETED, False) is True

    def test_check_done_always_is_immediately_true(self):
        assert _check_done([FakeFuture()], ALWAYS, False) is True


class TestWait:

    def test_empty_input_returns_two_empty_lists(self):
        assert wait([]) == ([], [])
        assert wait(None) == ([], [])

    def test_returns_immediately_when_all_complete(self):
        future = FakeFuture(done=True, success=True)
        done, not_done = wait([future], show_progressbar=False)
        assert done == [future]
        assert not_done == []

    def test_wraps_single_complete_future(self):
        future = FakeFuture(done=True, success=True)
        done, not_done = wait(future, show_progressbar=False)
        assert done == [future]
        assert not_done == []


class TestCreateExecutorsData:

    @patch.object(wait_mod, 'InternalStorage')
    def test_groups_futures_and_reuses_matching_storage(self, mock_storage_cls):
        internal = MagicMock()
        internal.backend = 'localhost'
        first = FakeFuture(executor_id='a')
        second = FakeFuture(executor_id='a', call_id='00001')
        third = FakeFuture(executor_id='b', storage_backend='s3')

        groups = _create_executors_data_from_futures(
            [first, second, third], internal
        )
        by_id = {group.executor_id: group for group in groups}

        assert set(by_id) == {'a', 'b'}
        assert by_id['a'].futures == [first, second]
        assert by_id['a'].internal_storage is internal
        assert by_id['b'].futures == [third]
        mock_storage_cls.assert_called_once_with(third._storage_config)
        assert by_id['b'].internal_storage is mock_storage_cls.return_value


class TestPollSleep:

    def test_localhost_and_non_storage_use_short_interval(self):
        local = SimpleNamespace(type='storage', storage_backend='localhost')
        rabbit = SimpleNamespace(type='rabbitmq', storage_backend='s3')
        assert _poll_sleep_sec(local, None) == 0.1
        assert _poll_sleep_sec(rabbit, 3) == 0.1

    def test_remote_storage_uses_wait_dur_or_default(self):
        remote = SimpleNamespace(type='storage', storage_backend='s3')
        assert _poll_sleep_sec(remote, None) == WAIT_DUR_SEC
        assert _poll_sleep_sec(remote, 3) == 3
        # Historical: 0 is falsy so the default interval is used.
        assert _poll_sleep_sec(remote, 0) == WAIT_DUR_SEC


class TestReadyFuturesAndExecutorData:

    def test_ready_futures_status_only_includes_ready_and_pending(self):
        ready = FakeFuture(ready=True, call_id='00000')
        success = FakeFuture(success=True, call_id='00001')
        pending = FakeFuture(call_id='00002')
        exec_data = SimpleNamespace(futures=[ready, success, pending])
        assert _ready_futures(exec_data, download_results=False) == [ready]

    def test_ready_futures_download_includes_success_until_done(self):
        success = FakeFuture(ready=True, success=True, call_id='00000')
        done = FakeFuture(done=True, success=True, ready=True, call_id='00001')
        exec_data = SimpleNamespace(futures=[success, done])
        assert _ready_futures(exec_data, download_results=True) == [success]

    def test_ready_futures_over_every_state_combination(self):
        """
        This used to intersect a set of the futures whose status had arrived
        with a set of the ones not fetched yet, walking the list four times
        and building a call id per future on each. It is one filter now, and
        this pins the two down as the same answer for every state a future
        can be in
        """
        import itertools

        combos = list(itertools.product([False, True], repeat=3))
        futures = [
            FakeFuture(ready=r, success=s, done=d, call_id=f'{i:05d}')
            for i, (r, s, d) in enumerate(combos)
        ]
        exec_data = SimpleNamespace(futures=futures)

        assert _ready_futures(exec_data, download_results=False) == [
            f for f in futures if f.ready and not (f.success or f.done)
        ]
        assert _ready_futures(exec_data, download_results=True) == [
            f for f in futures if (f.ready or f.success) and not f.done
        ]

    def test_ready_futures_does_not_look_at_call_ids(self):
        """
        Two futures of the same job never share a call id, so matching them
        up by id was only ever asking two things of the same future — at the
        cost of a tuple per future, four times per poll, ten polls a second
        """
        ready = FakeFuture(ready=True, call_id='00000')
        other = FakeFuture(ready=True, call_id='00000')
        exec_data = SimpleNamespace(futures=[ready, other])
        assert _ready_futures(exec_data, download_results=False) == [
            ready, other
        ]

    def test_check_done_any_completed_stops_at_the_first(self):
        """
        Counting every future to compare the total against one is a full
        pass per poll, on the caller's thread
        """
        seen = []

        class Counted(FakeFuture):
            @property
            def success(self):
                seen.append(self.call_id)
                return True

            @success.setter
            def success(self, value):
                pass

        fs = [Counted(call_id=f'{i:05d}') for i in range(100)]
        assert _check_done(fs, ANY_COMPLETED, False) is True
        assert len(seen) == 1

    def test_get_executor_data_fetches_status_and_extends_new_futures(self):
        parent = FakeFuture(ready=True, call_id='00000')
        child = FakeFuture(call_id='00001')
        parent._new_futures = [child]
        exec_data = SimpleNamespace(futures=[parent], internal_storage=MagicMock())
        fs = [parent]
        pbar = MagicMock()
        pbar.n = 0
        pbar.total = 1

        fetched = _get_executor_data(
            fs, exec_data, download_results=False, throw_except=True,
            threadpool_size=2, pbar=pbar,
        )

        assert fetched == 1
        assert parent.success is True
        assert child in fs
        assert child in exec_data.futures
        assert pbar.total == 2
        pbar.update.assert_called()

    def test_get_executor_data_downloads_results(self):
        future = FakeFuture(ready=True, success=True, result=42)
        exec_data = SimpleNamespace(futures=[future], internal_storage=MagicMock())
        fetched = _get_executor_data(
            [future], exec_data, download_results=True, throw_except=True,
            threadpool_size=1, pbar=None,
        )
        assert fetched == 1
        assert future.done is True


class TestWaitPolling:

    def test_always_polls_once_without_looping(self):
        future = FakeFuture()
        monitor = MagicMock()
        monitor.type = 'storage'
        monitor.storage_backend = 'localhost'
        internal = MagicMock()
        internal.backend = 'localhost'
        with patch.object(wait_mod, '_get_executor_data', return_value=0) as get:
            wait(
                [future],
                return_when=ALWAYS,
                show_progressbar=False,
                job_monitor=monitor,
                internal_storage=internal,
            )
            get.assert_called_once()

    def test_keyboard_interrupt_reraises_after_logging(self):
        future = FakeFuture()
        with patch.object(
            wait_mod,
            '_create_executors_data_from_futures',
            side_effect=KeyboardInterrupt,
        ):
            with pytest.raises(KeyboardInterrupt):
                wait([future], show_progressbar=False)

    def test_starts_and_stops_monitor_when_none_provided(self):
        future = FakeFuture()
        monitor = MagicMock()
        monitor.type = 'storage'
        monitor.storage_backend = 'localhost'
        monitor.is_alive.return_value = True
        internal = MagicMock()
        internal.backend = 'localhost'

        def get_data(fs, exec_data, **kwargs):
            future.success = True
            return 1

        with patch.object(wait_mod, 'JobMonitor', return_value=monitor) as cls, \
                patch.object(wait_mod, '_get_executor_data', side_effect=get_data), \
                patch.object(wait_mod.time, 'sleep'):
            wait(
                [future],
                show_progressbar=False,
                internal_storage=internal,
            )
        cls.assert_called_once()
        monitor.start.assert_called_once()
        monitor.stop.assert_called_once()

    def test_timeout_registers_sigalrm_with_interpolated_message(self):
        if not is_unix_system():
            pytest.skip('SIGALRM waiting timeout is unix-only')
        future = FakeFuture()
        monitor = MagicMock()
        monitor.type = 'storage'
        monitor.storage_backend = 'localhost'
        monitor.is_alive.return_value = True
        internal = MagicMock()
        internal.backend = 'localhost'
        handlers = {}

        def fake_signal(sig, handler):
            handlers[sig] = handler

        def get_data(fs, exec_data, **kwargs):
            future.success = True
            return 1

        with patch.object(wait_mod.signal, 'signal', side_effect=fake_signal), \
                patch.object(wait_mod.signal, 'alarm') as alarm, \
                patch.object(wait_mod, '_get_executor_data', side_effect=get_data), \
                patch.object(wait_mod.time, 'sleep'):
            wait(
                [future],
                timeout=17,
                show_progressbar=False,
                job_monitor=monitor,
                internal_storage=internal,
            )

        alarm.assert_any_call(17)
        alarm.assert_called_with(0)
        assert 'Timeout of 17 seconds exceeded' in handlers[signal.SIGALRM].args[0]

    def test_all_completed_restarts_dead_monitor_and_sleeps_on_empty_poll(self):
        future = FakeFuture()
        monitor = MagicMock()
        monitor.type = 'storage'
        monitor.storage_backend = 'localhost'
        monitor.is_alive.side_effect = [False, True]
        internal = MagicMock()
        internal.backend = 'localhost'
        polls = {'n': 0}

        def get_data(fs, exec_data, **kwargs):
            polls['n'] += 1
            if polls['n'] == 1:
                return 0
            future.success = True
            future.done = True
            return 3

        sleeps = []
        test_thread = threading.current_thread()

        def sleep(seconds):
            if threading.current_thread() is test_thread:
                sleeps.append(seconds)

        with patch.object(wait_mod, '_get_executor_data', side_effect=get_data), \
                patch.object(wait_mod.time, 'sleep', side_effect=sleep):
            wait(
                [future],
                return_when=ALL_COMPLETED,
                show_progressbar=False,
                job_monitor=monitor,
                internal_storage=internal,
            )

        monitor.start.assert_called_once_with(fs=[future])
        assert sleeps == [0.1, 0]

    def test_wait_tracks_nested_futures_until_they_complete(self):
        child = FakeFuture(call_id='00001')
        parent = FakeFuture(ready=True, call_id='00000')

        def parent_status(**kwargs):
            parent.success = True
            parent._new_futures = [child]
            child.ready = True
            return {'ok': True}

        parent.status = parent_status
        monitor = MagicMock()
        monitor.type = 'storage'
        monitor.storage_backend = 'localhost'
        monitor.is_alive.return_value = True
        internal = MagicMock()
        internal.backend = 'localhost'

        with patch.object(wait_mod.time, 'sleep'):
            done, not_done = wait(
                [parent],
                show_progressbar=False,
                job_monitor=monitor,
                internal_storage=internal,
            )

        assert parent.success is True
        assert child.success is True
        assert child in done
        assert parent in done
        assert not_done == []


class TestGetResult:

    def test_returns_produced_results_and_skips_nested(self):
        produced = FakeFuture(done=True, success=True, result=1)
        nested = FakeFuture(done=True, success=True, result=2, futures=True)
        silent = FakeFuture(done=True, success=True, result=3, produce_output=False)
        assert get_result(
            [produced, nested, silent], show_progressbar=False
        ) == [1]
