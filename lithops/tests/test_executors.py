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
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import lithops
from lithops.constants import LOCALHOST, SERVERLESS, STANDALONE
from lithops.executors import (
    FunctionExecutor,
    LocalhostExecutor,
    ServerlessExecutor,
    StandaloneExecutor,
    _FixedModeExecutor,
    _missing_plotting_extra,
    _omit_none,
)
from lithops.storage.utils import create_job_key
from lithops.tests.conftest import TESTS_PREFIX
from lithops.tests.functions import (
    echo_object,
    raise_value_error,
    simple_map_function,
    simple_reduce_function,
    sleep_seconds,
)
from lithops.utils import FuturesList
from lithops.wait import ALL_COMPLETED, ALWAYS, ANY_COMPLETED


def _bare_executor(**attrs):
    """Build a FunctionExecutor without running __init__ (no storage/backend)."""
    executor = FunctionExecutor.__new__(FunctionExecutor)
    defaults = {
        'config': {},
        'futures': [],
        'cleaned_jobs': set(),
        'total_jobs': 0,
        'last_call': None,
        'data_cleaner': False,
        'executor_id': 'sess-0',
        'internal_storage': MagicMock(),
        'compute_handler': MagicMock(),
        'invoker': MagicMock(),
        'job_monitor': MagicMock(),
    }
    defaults.update(attrs)
    for key, value in defaults.items():
        setattr(executor, key, value)
    return executor


class FakeFuture:
    def __init__(self, **kwargs):
        self.done = False
        self.success = False
        self.error = False
        self.futures = None
        self._produce_output = True
        self._read = False
        self.job_id = 'M000'
        self.job_key = 'sess-0/M000'
        self.executor_id = 'sess-0'
        self.function_name = 'fn'
        self.runtime_memory = 256
        self.stats = {'worker_exec_time': 1.0}
        self._result = None
        self._exception_set = False
        self._mapreduce = False
        for key, value in kwargs.items():
            setattr(self, key, value)

    def result(self, throw_except=True, internal_storage=None):
        return self._result

    def _set_mapreduce(self):
        self._read = True
        self._produce_output = False
        self._mapreduce = True

    def _set_exception(self):
        self._exception_set = True


class TestExecutorHelpers:

    def test_omit_none_keeps_falsey_non_none_values(self):
        assert _omit_none({'a': 1, 'b': None, 'c': 0, 'd': False, 'e': ''}) == {
            'a': 1, 'c': 0, 'd': False, 'e': ''
        }

    def test_missing_plotting_extra_mentions_method(self):
        err = _missing_plotting_extra('plot')
        assert isinstance(err, ModuleNotFoundError)
        assert 'plot()' in str(err)
        assert 'lithops[plotting]' in str(err)

    def test_build_config_overwrite_splits_lithops_and_backend(self):
        overwrite = FunctionExecutor._build_config_overwrite(
            mode='localhost',
            backend=None,
            storage='localhost',
            monitoring=None,
            kwargs={'runtime': 'python3', 'unused': None},
        )
        assert overwrite['lithops'] == {'mode': 'localhost', 'storage': 'localhost'}
        assert overwrite['backend'] == {'runtime': 'python3'}

    def test_as_future_list_keeps_list_and_futures_list(self):
        plain = [1, 2]
        futures_list = FuturesList([1, 2])
        assert FunctionExecutor._as_future_list(plain) is plain
        assert FunctionExecutor._as_future_list(futures_list) is futures_list

    def test_as_future_list_wraps_single_future(self):
        future = FakeFuture()
        assert FunctionExecutor._as_future_list(future) == [future]

    def test_disable_iterdata_output_only_for_futures_list(self):
        future = FakeFuture(_produce_output=True)
        FunctionExecutor._disable_iterdata_output([future])
        assert future._produce_output is True

        wrapped = FakeFuture(_produce_output=True)
        FunctionExecutor._disable_iterdata_output(FuturesList([wrapped]))
        assert wrapped._produce_output is False

    def test_create_job_id_increments_and_zero_fills(self):
        executor = _bare_executor(total_jobs=0)
        assert executor._create_job_id('A') == 'A000'
        assert executor._create_job_id('M') == 'M001'
        assert executor.total_jobs == 2

    def test_create_compute_handler_localhost_versions(self):
        with patch('lithops.executors.LocalhostHandlerV1') as v1, \
                patch('lithops.executors.extract_localhost_config', return_value={'version': 1}):
            executor = _bare_executor(mode=LOCALHOST, config={'localhost': {}})
            assert executor._create_compute_handler() is v1.return_value
            v1.assert_called_once()

        with patch('lithops.executors.LocalhostHandlerV2') as v2, \
                patch('lithops.executors.extract_localhost_config', return_value={}):
            executor = _bare_executor(mode=LOCALHOST, config={'localhost': {}})
            assert executor._create_compute_handler() is v2.return_value

    def test_create_compute_handler_unknown_mode_returns_none(self):
        executor = _bare_executor(mode='mystery', config={})
        assert executor._create_compute_handler() is None


class TestExecutorSubclasses:

    def test_fixed_mode_hierarchy(self):
        assert issubclass(ServerlessExecutor, FunctionExecutor)
        assert issubclass(StandaloneExecutor, FunctionExecutor)
        assert issubclass(LocalhostExecutor, FunctionExecutor)
        assert issubclass(ServerlessExecutor, _FixedModeExecutor)
        assert ServerlessExecutor._mode == SERVERLESS
        assert StandaloneExecutor._mode == STANDALONE

    @patch.object(FunctionExecutor, '__init__', return_value=None)
    def test_serverless_executor_pins_mode(self, mock_init):
        ServerlessExecutor(config={'lithops': {}})
        assert mock_init.call_args.kwargs['mode'] == SERVERLESS

    @patch.object(FunctionExecutor, '__init__', return_value=None)
    def test_standalone_executor_pins_mode(self, mock_init):
        StandaloneExecutor(config={'lithops': {}})
        assert mock_init.call_args.kwargs['mode'] == STANDALONE

    @patch.object(FunctionExecutor, '__init__', return_value=None)
    def test_localhost_executor_pins_backend_and_storage(self, mock_init):
        LocalhostExecutor()
        assert mock_init.call_args.kwargs['backend'] == LOCALHOST
        assert mock_init.call_args.kwargs['storage'] == LOCALHOST


class TestSubmitAndCleanup:

    def test_submit_map_uses_job_prefix_and_disables_futures_list_output(self):
        executor = _bare_executor(total_jobs=0)
        job = MagicMock()
        submitted = [FakeFuture(_produce_output=True)]
        iterdata = FuturesList(submitted)

        with patch.object(executor, '_run_map_job', return_value=(job, submitted)) as run_map:
            job_id, out_job, out_fs = executor._submit_map(
                lambda x: x, iterdata, job_prefix='A'
            )

        assert job_id == 'A000'
        assert out_job is job
        assert out_fs is submitted
        assert submitted[0]._produce_output is False
        assert run_map.call_args.kwargs['job_id'] == 'A000'
        assert run_map.call_args.kwargs['iterdata'] is iterdata

    def test_cleanup_jobs_omits_exception_kwarg_on_success(self):
        executor = _bare_executor()
        future = FakeFuture()
        with patch.object(executor, 'clean') as clean:
            executor._cleanup_jobs([future])
        executor.compute_handler.clear.assert_called_once_with({future.job_key})
        clean.assert_called_once_with(clean_cloudobjects=False, force=False)

    def test_cleanup_jobs_passes_exception_and_force(self):
        executor = _bare_executor()
        future = FakeFuture()
        error = RuntimeError('boom')
        with patch.object(executor, 'clean') as clean:
            executor._cleanup_jobs([future], exception=error, force=True)
        executor.compute_handler.clear.assert_called_once_with(
            {future.job_key}, exception=error
        )
        clean.assert_called_once_with(clean_cloudobjects=False, force=True)

    def test_clean_does_not_wrap_futures_list(self):
        future = FakeFuture(executor_id='abc-0', job_id='M000', done=True)
        futures = FuturesList([future])
        executor = _bare_executor(cleaned_jobs=set(), executor_id='abc-0')

        with patch('lithops.executors._dump_cleaner_data') as dump, \
                patch('lithops.executors.sp.Popen'):
            executor.clean(fs=futures, clean_cloudobjects=False)

        assert create_job_key('abc-0', 'M000') in executor.cleaned_jobs
        dumped_jobs = dump.call_args_list[-1][0][0]['jobs_to_clean']
        assert create_job_key('abc-0', 'M000') in dumped_jobs

    def test_clean_fn_invalidates_function_cache(self):
        from lithops.job.job import FUNCTION_CACHE
        from lithops.storage.utils import create_func_key

        drop = create_func_key('abc-0', 'deadbeef')
        keep = create_func_key('other-1', 'deadbeef')
        saved = set(FUNCTION_CACHE)
        FUNCTION_CACHE.update({drop, keep})
        try:
            executor = _bare_executor(cleaned_jobs=set(), executor_id='abc-0')
            with patch('lithops.executors._dump_cleaner_data'), \
                    patch('lithops.executors.sp.Popen'):
                executor.clean(clean_fn=True, clean_cloudobjects=False)
            assert drop not in FUNCTION_CACHE
            assert keep in FUNCTION_CACHE
        finally:
            FUNCTION_CACHE.clear()
            FUNCTION_CACHE.update(saved)

    def test_dump_cleaner_data_recreates_missing_dir(self, tmp_path, monkeypatch):
        import pickle
        from lithops.executors import _dump_cleaner_data

        cleaner_dir = tmp_path / 'cleaner'
        monkeypatch.setattr('lithops.executors.CLEANER_DIR', str(cleaner_dir))

        _dump_cleaner_data({'jobs_to_clean': {'job-1'}})

        dumped = list(cleaner_dir.iterdir())
        assert len(dumped) == 1
        with dumped[0].open('rb') as fh:
            assert pickle.load(fh) == {'jobs_to_clean': {'job-1'}}


class TestWaitAndGetResult:

    @patch('lithops.executors.wait')
    def test_wait_partitions_by_done_when_downloading_results(self, mock_wait):
        finished = FakeFuture(done=True, success=True)
        pending = FakeFuture(done=False, success=False)
        executor = _bare_executor()

        done, notdone = executor.wait(
            [finished, pending], download_results=True, show_progressbar=False
        )

        assert list(done) == [finished]
        assert list(notdone) == [pending]

    @patch('lithops.executors.wait')
    def test_wait_treats_success_as_done_when_not_downloading(self, mock_wait):
        success = FakeFuture(done=False, success=True)
        pending = FakeFuture(done=False, success=False)
        executor = _bare_executor()

        done, notdone = executor.wait(
            [success, pending], download_results=False, show_progressbar=False
        )

        assert list(done) == [success]
        assert list(notdone) == [pending]

    @patch('lithops.executors.wait')
    def test_wait_cleans_when_all_completed(self, mock_wait):
        future = FakeFuture(done=True, success=True)
        executor = _bare_executor(data_cleaner=True)

        with patch.object(executor, '_cleanup_jobs') as cleanup:
            executor.wait([future], return_when=ALL_COMPLETED, show_progressbar=False)

        cleanup.assert_called_once()
        assert cleanup.call_args.kwargs.get('force', False) is False
        assert cleanup.call_args.kwargs.get('exception') is None

    @patch('lithops.executors.wait')
    def test_wait_stops_monitor_when_all_tracked_futures_are_done(self, mock_wait):
        future = FakeFuture(done=True, success=True)
        executor = _bare_executor(futures=[future])
        executor.wait([future], return_when=ALL_COMPLETED, show_progressbar=False)
        executor.job_monitor.stop.assert_called_once()

    @patch('lithops.executors.wait')
    def test_wait_keeps_monitor_when_other_futures_are_pending(self, mock_wait):
        done = FakeFuture(done=True, success=True)
        pending = FakeFuture(done=False, success=False)
        executor = _bare_executor(futures=[done, pending])
        executor.wait([done], return_when=ALL_COMPLETED, show_progressbar=False)
        executor.job_monitor.stop.assert_not_called()

    @patch('lithops.executors.wait', side_effect=RuntimeError('boom'))
    def test_wait_exception_stops_invoker_and_reraises(self, mock_wait):
        future = FakeFuture()
        executor = _bare_executor(data_cleaner=True)

        with patch.object(executor, '_cleanup_jobs') as cleanup:
            with pytest.raises(RuntimeError, match='boom'):
                executor.wait([future], show_progressbar=False)

        executor.invoker.stop.assert_called_once()
        executor.job_monitor.remove.assert_called_once()
        assert future._exception_set is True
        assert cleanup.call_args.kwargs['force'] is True
        assert isinstance(cleanup.call_args.kwargs['exception'], RuntimeError)

    def test_get_result_unwraps_single_non_map_result(self):
        future = FakeFuture(_result=42)
        executor = _bare_executor(last_call='call_async', futures=[future])

        with patch.object(executor, 'wait', return_value=([future], [])):
            assert executor.get_result() == 42
        assert future._read is True

    def test_get_result_keeps_list_for_map(self):
        future = FakeFuture(_result=42)
        executor = _bare_executor(last_call='map', futures=[future])

        with patch.object(executor, 'wait', return_value=([future], [])):
            assert executor.get_result() == [42]

    def test_get_result_skips_nested_and_already_read_futures(self):
        nested = FakeFuture(futures=[FakeFuture()], _result='nested')
        consumed = FakeFuture(_read=True, _result='old')
        pending = FakeFuture(_result='new')
        executor = _bare_executor(
            last_call='map_reduce',
            futures=[nested, consumed, pending],
        )

        with patch.object(
            executor, 'wait', return_value=([nested, consumed, pending], [])
        ):
            assert executor.get_result() == 'new'

    def test_plot_returns_when_no_ready_futures(self):
        executor = _bare_executor(futures=[FakeFuture(success=False, done=False)])
        assert executor.plot() is None

    def test_plot_calls_timeline_and_histogram(self):
        future = FakeFuture(success=True, done=True, error=False)
        executor = _bare_executor(futures=[future])
        fake_plots = MagicMock()
        with patch.dict(sys.modules, {'lithops.plots': fake_plots}):
            executor.plot(dst='/tmp/out', figsize=(4, 3))
        fake_plots.create_timeline.assert_called_once_with(
            [future], '/tmp/out', (4, 3)
        )
        fake_plots.create_histogram.assert_called_once_with(
            [future], '/tmp/out', (4, 3)
        )

    def test_plot_missing_extra_raises(self):
        future = FakeFuture(success=True, done=True, error=False)
        executor = _bare_executor(futures=[future])
        with patch.dict(sys.modules, {'lithops.plots': None}):
            with pytest.raises(ModuleNotFoundError, match=r'plot\(\)'):
                executor.plot()

    def test_job_summary_warns_when_backend_has_no_calc_cost(self):
        pytest.importorskip('pandas')
        executor = _bare_executor()
        executor.compute_handler.backend = SimpleNamespace(name='localhost')
        with patch('lithops.executors.logger.warning') as warn:
            executor.job_summary()
        warn.assert_called_once()
        assert "isn't supported" in warn.call_args[0][0]

    def test_job_summary_writes_csv_when_backend_supports_cost(
        self, tmp_path, monkeypatch
    ):
        pytest.importorskip('pandas')
        monkeypatch.setattr('lithops.executors.constants.LOGS_DIR', str(tmp_path))
        backend = MagicMock()
        backend.calc_cost.return_value = 1.25
        executor = _bare_executor(
            futures=[
                FakeFuture(
                    job_id='M000', function_name='fn', runtime_memory=128,
                    stats={'worker_exec_time': 0.5},
                ),
                FakeFuture(
                    job_id='M000', function_name='fn', runtime_memory=128,
                    stats={'worker_exec_time': 1.5},
                ),
            ]
        )
        executor.compute_handler.backend = backend
        executor.log_path = None
        executor.job_summary()
        assert executor.log_path
        assert os.path.exists(executor.log_path)
        text = open(executor.log_path).read()
        assert 'Summary' in text
        assert 'M000' in text

    def test_map_reduce_always_skips_waiting_for_map(self):
        executor = _bare_executor(total_jobs=0)
        map_futures = [FakeFuture(job_id='M000')]
        reduce_futures = [FakeFuture(job_id='R000')]
        job = MagicMock()
        with patch.object(
            executor, '_submit_map', return_value=('M000', job, map_futures)
        ), patch.object(executor, 'wait') as wait, patch.object(
            executor, '_run_reduce_job', return_value=reduce_futures
        ):
            result = executor.map_reduce(
                lambda x: x, [1], lambda xs: xs, spawn_reducer=ALWAYS
            )
        wait.assert_not_called()
        assert map_futures[0]._mapreduce is True
        assert list(result) == map_futures + reduce_futures


class TestExecutorLocalhost:
    """Live localhost checks for the refactored public API."""

    def test_call_async_job_prefix_and_unwrapped_result(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        future = fexec.call_async(lambda x: x + 1, 1)
        assert future.job_id.startswith('A')
        assert fexec.last_call == 'call_async'
        assert fexec.get_result() == 2

    def test_map_job_prefix_and_list_result(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map(lambda x: x * 2, [1, 2, 3])
        assert all(future.job_id.startswith('M') for future in futures)
        assert fexec.last_call == 'map'
        assert fexec.get_result() == [2, 4, 6]

    def test_map_reduce_map_and_reduce_job_ids(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(
            simple_map_function,
            [(1, 1), (2, 2)],
            simple_reduce_function,
        )
        job_ids = {future.job_id for future in futures}
        assert any(job_id.startswith('M') for job_id in job_ids)
        assert any(job_id.startswith('R') for job_id in job_ids)
        assert fexec.last_call == 'map_reduce'
        assert fexec.get_result() == 6

    def test_map_reduce_spawn_reducer_always_and_percentage(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(
            simple_map_function,
            [(1, 1), (2, 2)],
            simple_reduce_function,
            spawn_reducer=ALWAYS,
        )
        assert any(future.job_id.startswith('R') for future in futures)
        assert fexec.get_result() == 6

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map_reduce(
            simple_map_function,
            [(1, 1), (2, 2), (3, 3), (4, 4)],
            simple_reduce_function,
            spawn_reducer=50,
        )
        assert fexec.get_result() == 20

    def test_map_local_file_partitions(self, tmp_path):
        path = tmp_path / 'data.txt'
        text = 'alpha beta gamma delta\n' * 20
        path.write_text(text)
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map(
            echo_object, str(path), obj_chunk_number=2, obj_newline=None
        )
        result = fexec.get_result()
        assert len(futures) == 2
        assert ''.join(result) == text

    def test_map_local_file_chunk_size(self, tmp_path):
        path = tmp_path / 'data.txt'
        text = 'x' * 100
        path.write_text(text)
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map(
            echo_object, str(path), obj_chunk_size=40, obj_newline=None
        )
        result = fexec.get_result()
        assert len(futures) == 3
        assert ''.join(result) == text

    def test_map_local_directory(self, tmp_path):
        folder = tmp_path / 'files'
        folder.mkdir()
        (folder / 'a.txt').write_text('one')
        (folder / 'b.txt').write_text('two')
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map(echo_object, str(folder))
        assert sorted(fexec.get_result()) == ['one', 'two']

    def test_context_manager_and_localhost_executor(self):
        with lithops.LocalhostExecutor(config=pytest.lithops_config) as fexec:
            fexec.map(simple_map_function, [(3, 4)])
            assert fexec.get_result() == [7]
            assert fexec.mode == LOCALHOST
            assert fexec.backend == LOCALHOST

    def test_get_result_reraises_worker_exception(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map(raise_value_error, [1])
        with pytest.raises(ValueError, match='worker failed'):
            fexec.get_result()

    def test_get_result_throw_except_false_does_not_reraise(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map(raise_value_error, [1])
        fexec.get_result(throw_except=False)

    def test_wait_any_completed_and_percentage(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map(sleep_seconds, [0, 2, 2])
        done, notdone = fexec.wait(futures, return_when=ANY_COMPLETED)
        assert len(done) >= 1
        fexec.wait(futures)
        assert fexec.get_result() == [0, 2, 2]

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map(sleep_seconds, [0, 0, 3, 3])
        done, notdone = fexec.wait(futures, return_when=50)
        assert len(done) >= 2
        fexec.wait()

    def test_execution_timeout(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map(sleep_seconds, [30], timeout=3)
        with pytest.raises(Exception):
            fexec.get_result()

    def test_clean_after_job(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map(lambda x: x, [1, 2])
        assert fexec.get_result() == [1, 2]
        fexec.clean(force=True)
        assert fexec.cleaned_jobs

    def test_map_obj_parameter_over_storage_prefix(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        bucket = fexec.storage.bucket
        prefix = TESTS_PREFIX + '/echo-obj/'
        key = prefix + 'a.txt'
        fexec.storage.put_object(bucket, key, b'alpha')
        url = fexec.config['lithops']['storage'] + '://' + bucket + '/' + prefix
        try:
            fexec.map(echo_object, url)
            assert fexec.get_result() == ['alpha']
        finally:
            fexec.storage.delete_object(bucket, key)
