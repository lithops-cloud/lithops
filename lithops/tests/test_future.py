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

import base64
import pickle
import zlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import lithops
from lithops.future import ResponseFuture, _pickle_from_encoded, _stats_from_prefixed_keys


class HasAmbiguousTruthValue:
    """An object with an ambiguous truth value, simulates pandas.DataFrame and numpy.NDArray."""

    def __init__(self, data):
        self.data = data

    def __bool__(self):
        raise ValueError(
            f"The truth value of a {type(self).__name__} is ambiguous. "
            "Use a.empty, a.bool(), a.item(), a.any() or a.all()."
        )


STORAGE_CONFIG = {
    'backend': 'localhost',
    'localhost': {'storage_bucket': 'test-bucket'},
}


def _job(**overrides):
    values = dict(
        job_id='M000',
        job_key='sess-0/M000',
        executor_id='sess-0',
        function_name='fn',
        execution_timeout=300,
        runtime_name='python',
        runtime_memory=256,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _future(job_metadata=None, **job_kwargs):
    return ResponseFuture('00000', _job(**job_kwargs), job_metadata or {}, STORAGE_CONFIG)


class TestStatsHelper:

    def test_keeps_func_host_and_worker_prefixes(self):
        mapping = {
            'func_name': 'fn',
            'host_submit_tstamp': 1.0,
            'worker_start_tstamp': 2.0,
            'activation_id': 'skip-me',
            'type': '__end__',
        }
        assert _stats_from_prefixed_keys(mapping) == {
            'func_name': 'fn',
            'host_submit_tstamp': 1.0,
            'worker_start_tstamp': 2.0,
        }

    def test_empty_mapping(self):
        assert _stats_from_prefixed_keys({}) == {}


class TestResponseFutureState:

    def test_new_future_collects_job_metadata_stats(self):
        future = _future({'func_name': 'fn', 'ignored': True})
        assert future.new
        assert not future.invoked
        assert not future.ready
        assert not future.success
        assert not future.done
        assert not future.error
        assert future.stats['func_name'] == 'fn'
        assert 'ignored' not in future.stats

    def test_success_includes_error_state(self):
        future = _future()
        future._set_state(ResponseFuture.State.Error)
        assert future.error
        assert future.success
        assert future.done

    def test_done_includes_unknown(self):
        future = _future()
        future._set_state(ResponseFuture.State.Unknown)
        assert future.done
        assert not future.success

    def test_set_running_and_ready(self):
        future = _future()
        future._set_running({'activation_id': 'act-1'})
        assert future.running
        assert future.activation_id == 'act-1'
        future._set_ready({'activation_id': 'act-1', 'type': '__end__'})
        assert future.ready

    def test_set_mapreduce_marks_successful_future_done(self):
        future = _future()
        future._set_state(ResponseFuture.State.Success)
        future._set_mapreduce()
        assert future.done
        assert future._produce_output is False
        assert future._read is True

    def test_set_mapreduce_does_not_advance_unsuccessful_future(self):
        future = _future()
        future._set_invoked()
        future._set_mapreduce()
        assert future.invoked
        assert future._produce_output is False

    def test_status_and_result_reject_new_state(self):
        future = _future()
        with pytest.raises(ValueError, match='task not yet invoked'):
            future.status()
        with pytest.raises(ValueError, match='Task not yet invoked'):
            future.result()

    def test_cancel_is_not_implemented(self):
        future = _future()
        with pytest.raises(NotImplementedError):
            future.cancel()
        with pytest.raises(NotImplementedError):
            future.cancelled()

    def test_status_returns_cached_call_status_when_done(self):
        future = _future()
        future._call_status = {'already': 'done'}
        future._set_state(ResponseFuture.State.Done)
        assert future.status() == {'already': 'done'}

    def test_write_activation_logs(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.future.LOGS_DIR', str(tmp_path))
        fn_log = tmp_path / 'functions.log'
        monkeypatch.setattr('lithops.future.FN_LOG_FILE', str(fn_log))

        future = _future()
        future.activation_id = 'act-9'
        raw = 'hello\nworld\n'
        future._call_status = {
            'logs': base64.b64encode(zlib.compress(raw.encode())).decode(),
        }

        future._write_activation_logs()

        job_log = (tmp_path / 'sess-0-M000.log').read_text()
        assert "Activation: 'python' (act-9)" in job_log
        assert 'hello' in job_log
        assert fn_log.read_text() == job_log

    def test_write_activation_logs_recreates_missing_log_dir(self, tmp_path, monkeypatch):
        logs_dir = tmp_path / 'missing' / 'logs'
        monkeypatch.setattr('lithops.future.LOGS_DIR', str(logs_dir))
        fn_log = tmp_path / 'missing' / 'functions.log'
        monkeypatch.setattr('lithops.future.FN_LOG_FILE', str(fn_log))

        future = _future()
        future.activation_id = 'act-9'
        raw = 'hello\nworld\n'
        future._call_status = {
            'logs': base64.b64encode(zlib.compress(raw.encode())).decode(),
        }

        future._write_activation_logs()

        assert (logs_dir / 'sess-0-M000.log').exists()
        assert fn_log.exists()

    def test_set_exception_marks_unfinished_future_unknown(self):
        future = _future()
        future._set_invoked()
        future._set_exception()
        assert future._read is True
        assert future.done
        assert future._state == ResponseFuture.State.Unknown

    def test_set_exception_does_not_change_already_done_state(self):
        future = _future()
        future._set_state(ResponseFuture.State.Done)
        future._set_exception()
        assert future._state == ResponseFuture.State.Done
        assert future._read is True

    def test_futures_property_tracks_new_futures(self):
        future = _future()
        assert future.futures is False
        future._new_futures = []
        assert future.futures is True


def _encode(obj):
    return str(pickle.dumps(obj))


def _end_status(**overrides):
    status = {
        'type': '__end__',
        'exception': False,
        'activation_id': 'act-1',
        'func_result_size': 1,
        'worker_start_tstamp': 1.0,
        'worker_end_tstamp': 2.5,
        'host_submit_tstamp': 0.5,
    }
    status.update(overrides)
    return status


class TestPickleHelper:

    def test_roundtrip(self):
        assert _pickle_from_encoded(_encode({'k': 1})) == {'k': 1}


class TestResponseFutureStatusAndResult:

    def test_poll_check_only_returns_without_waiting(self):
        future = _future()
        future._set_invoked()
        storage = MagicMock()
        storage.get_storage_config.return_value = STORAGE_CONFIG
        storage.get_call_status.return_value = None
        assert future.status(internal_storage=storage, check_only=True) is None
        storage.get_call_status.assert_called_once()

    def test_poll_retries_until_status_appears(self, monkeypatch):
        future = _future()
        future._set_invoked()
        storage = MagicMock()
        storage.get_storage_config.return_value = STORAGE_CONFIG
        storage.get_call_status.side_effect = [None, None, _end_status(result=_encode(9))]
        monkeypatch.setattr('lithops.future.time.sleep', lambda *_: None)
        status = future.status(internal_storage=storage, wait_dur_sec=0)
        assert storage.get_call_status.call_count == 3
        assert status['activation_id'] == 'act-1'
        assert future.done
        assert future.result(internal_storage=storage) == 9

    def test_status_creates_internal_storage_when_missing(self):
        future = _future()
        future._set_invoked()
        with patch('lithops.future.InternalStorage') as storage_cls:
            inst = storage_cls.return_value
            inst.get_storage_config.return_value = STORAGE_CONFIG
            inst.get_call_status.return_value = _end_status(func_result_size=0)
            future.status()
            storage_cls.assert_called_once_with(STORAGE_CONFIG)
        assert future._produce_output is False
        assert future.done

    def test_status_refetches_init_call_status(self):
        future = _future()
        future._set_invoked()
        future._call_status = {'type': '__init__', 'activation_id': 'boot'}
        storage = MagicMock()
        storage.get_storage_config.return_value = STORAGE_CONFIG
        storage.get_call_status.return_value = _end_status(result=_encode('ok'))
        future.status(internal_storage=storage)
        assert future.activation_id == 'act-1'
        assert future.done

    def test_exception_is_reraised_by_default(self):
        future = _future()
        future._set_invoked()
        storage = MagicMock()
        storage.get_storage_config.return_value = STORAGE_CONFIG
        storage.get_call_status.return_value = _end_status(
            exception=True,
            exc_info=_encode((ValueError, ValueError('boom'), None)),
        )
        with pytest.raises(ValueError, match='boom'):
            future.status(internal_storage=storage)
        assert future.error

    def test_exception_can_be_suppressed(self):
        future = _future()
        future._set_invoked()
        storage = MagicMock()
        storage.get_storage_config.return_value = STORAGE_CONFIG
        storage.get_call_status.return_value = _end_status(
            exception=True,
            exc_info=_encode((ValueError, ValueError('boom'), None)),
        )
        assert future.status(internal_storage=storage, throw_except=False) is None
        assert future.error

    def test_handler_exception_strips_marker_argument(self):
        future = _future()
        future._set_invoked()
        storage = MagicMock()
        storage.get_storage_config.return_value = STORAGE_CONFIG
        storage.get_call_status.return_value = _end_status(
            exception=True,
            exc_info=_encode((Exception, Exception('HANDLER', 'inner'), None)),
        )
        with pytest.raises(Exception, match='inner'):
            future.status(internal_storage=storage)
        assert future._handler_exception is True

    def test_pickle_fail_wraps_exception_dict(self):
        future = _future()
        future._set_invoked()
        storage = MagicMock()
        storage.get_storage_config.return_value = STORAGE_CONFIG
        storage.get_call_status.return_value = _end_status(
            exception=True,
            exc_pickle_fail=True,
            exc_info=_encode({'exc_value': 'pickle-broke', 'exc_traceback': None}),
        )
        with pytest.raises(Exception, match='pickle-broke'):
            future.status(internal_storage=storage)

    def test_new_futures_wraps_a_single_response_future(self):
        nested = _future()
        future = _future()
        future._set_invoked()
        storage = MagicMock()
        storage.get_storage_config.return_value = STORAGE_CONFIG
        storage.get_call_status.return_value = _end_status(
            new_futures=_encode(nested),
            func_result_size=0,
        )
        future.status(internal_storage=storage)
        assert len(future._new_futures) == 1
        assert isinstance(future._new_futures[0], ResponseFuture)
        assert future._new_futures[0].call_id == nested.call_id
        assert future.result(internal_storage=storage) == future._new_futures

    def test_new_futures_keeps_a_list(self):
        nested = [_future(), _future()]
        future = _future()
        future._set_invoked()
        storage = MagicMock()
        storage.get_storage_config.return_value = STORAGE_CONFIG
        storage.get_call_status.return_value = _end_status(
            new_futures=_encode(nested),
        )
        future.status(internal_storage=storage)
        assert isinstance(future._new_futures, list)
        assert len(future._new_futures) == 2
        assert {f.call_id for f in future._new_futures} == {nested[0].call_id, nested[1].call_id}

    def test_result_polls_output_then_unpickles(self, monkeypatch):
        future = _future()
        future._set_invoked()
        future._call_status = _end_status()
        future._set_state(ResponseFuture.State.Success)
        storage = MagicMock()
        storage.get_call_output.side_effect = [None, pickle.dumps('later')]
        monkeypatch.setattr('lithops.future.time.sleep', lambda *_: None)
        assert future.result(internal_storage=storage, retries=5, wait_dur_sec=0) == 'later'
        assert future.done
        assert future.stats['host_result_query_count'] == 2

    def test_result_missing_output_raises_by_default(self, monkeypatch):
        future = _future()
        future._set_invoked()
        future._call_status = _end_status()
        future._set_state(ResponseFuture.State.Success)
        storage = MagicMock()
        storage.get_call_output.return_value = None
        monkeypatch.setattr('lithops.future.time.sleep', lambda *_: None)
        with pytest.raises(Exception, match='Unable to get the result'):
            future.result(internal_storage=storage, retries=2, wait_dur_sec=0)

    def test_result_missing_output_can_be_suppressed(self, monkeypatch):
        future = _future()
        future._set_invoked()
        future._call_status = _end_status()
        future._set_state(ResponseFuture.State.Success)
        storage = MagicMock()
        storage.get_call_output.return_value = None
        monkeypatch.setattr('lithops.future.time.sleep', lambda *_: None)
        assert future.result(
            internal_storage=storage, retries=1, wait_dur_sec=0, throw_except=False
        ) is None
        assert future.error

    def test_result_creates_storage_when_not_done(self):
        future = _future()
        future._set_invoked()
        with patch('lithops.future.InternalStorage') as storage_cls:
            inst = storage_cls.return_value
            inst.get_storage_config.return_value = STORAGE_CONFIG
            inst.get_call_status.return_value = _end_status(result=_encode('x'))
            assert future.result() == 'x'
            storage_cls.assert_called_once()


def test_fn_returns_obj_with_ambiguous_truth_value():
    def returns_obj_with_ambiguous_truth_value(param):
        return HasAmbiguousTruthValue(param)

    fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
    future = fexec.call_async(returns_obj_with_ambiguous_truth_value, "Hello World!")
    result = future.result()
    assert result.data == "Hello World!"
