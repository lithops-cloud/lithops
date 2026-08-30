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

import io
import logging
import pickle
import zipfile
from collections import namedtuple
from unittest.mock import MagicMock, patch

import pytest

from lithops import constants
from lithops.utils import (
    CountDownLatch,
    CURRENT_PY_VERSION,
    FuturesList,
    WrappedStreamingBody,
    WrappedStreamingBodyPartition,
    _as_future_list,
    _future_id,
    agg_data,
    b64str_to_bytes,
    b64str_to_dict,
    bytes_to_b64str,
    convert_bools_to_string,
    create_executor_id,
    create_futures_list,
    dict_to_b64str,
    docker_login,
    find_free_port,
    format_data,
    get_default_backend,
    get_default_container_name,
    get_docker_path,
    get_executor_id,
    get_mode,
    is_linux_system,
    is_lithops_worker,
    is_notebook,
    is_object_processing_function,
    is_podman,
    is_unix_system,
    iterchunks,
    MONITORING_QUEUES_ENV,
    monitoring_queue_name,
    monitoring_queues,
    log_prefix,
    run_command,
    sdb_to_dict,
    setup_lithops_logger,
    ShutdownSafeStreamHandler,
    sizeof_fmt,
    split_object_url,
    split_path,
    timeout_handler,
    verify_args,
    verify_runtime_name,
    version_str,
)


class TestGetModeAndBackend:

    def test_get_default_backend_known_modes(self):
        assert get_default_backend(constants.LOCALHOST) == constants.LOCALHOST
        assert get_default_backend(constants.SERVERLESS) == constants.SERVERLESS_BACKEND_DEFAULT
        assert get_default_backend(constants.STANDALONE) == constants.STANDALONE_BACKEND_DEFAULT

    def test_get_default_backend_falsy_mode_returns_none(self):
        assert get_default_backend(None) is None
        assert get_default_backend('') is None
        assert get_default_backend(0) is None

    def test_get_default_backend_unknown_mode_keeps_historical_typo(self):
        with pytest.raises(Exception, match='Unknown execution mode: mystery'):
            get_default_backend('mystery')

    def test_get_mode_none_uses_default(self):
        assert get_mode(None) == constants.MODE_DEFAULT

    def test_get_mode_known_backends(self):
        assert get_mode(constants.LOCALHOST) == constants.LOCALHOST
        assert get_mode(constants.SERVERLESS_BACKEND_DEFAULT) == constants.SERVERLESS
        assert get_mode(constants.STANDALONE_BACKEND_DEFAULT) == constants.STANDALONE

    def test_get_mode_falsy_unknown_returns_none(self):
        assert get_mode('') is None

    def test_get_mode_unknown_backend_raises(self):
        with pytest.raises(Exception, match='Unknown compute backend: mystery'):
            get_mode('mystery')


class TestFormatData:

    def test_wraps_scalar_and_converts_range_and_set(self):
        assert format_data(7, None) == [7]
        assert format_data(range(3), None) == [0, 1, 2]
        assert set(format_data({1, 2}, None)) == {1, 2}

    def test_keeps_list_and_futures_list_identity(self):
        data = [1, 2]
        futures = FuturesList([object(), object()])
        assert format_data(data, None) is data
        assert format_data(futures, None) is futures

    def test_tuple_extra_args_concatenated(self):
        assert format_data([(1,), (2,)], (10,)) == [(1, 10), (2, 10)]

    def test_tuple_extra_args_must_be_tuple(self):
        with pytest.raises(Exception, match='extra_args must contain args in a tuple'):
            format_data([(1,)], [10])

    def test_dict_extra_args_merged_in_place(self):
        first = {'a': 1}
        result = format_data([first], {'b': 2})
        assert result == [{'a': 1, 'b': 2}]
        assert first is result[0]

    def test_dict_extra_args_must_be_dict(self):
        with pytest.raises(Exception, match='extra_args must contain kwargs in a dictionary'):
            format_data([{'a': 1}], ('b',))

    def test_scalar_plus_extra_args_becomes_tuple(self):
        assert format_data([1, 2], (9, 8)) == [(1, 9, 8), (2, 9, 8)]

    def test_namedtuple_plus_extra_args_is_not_concatenated(self):
        Point = namedtuple('Point', 'x y')
        pt = Point(1, 2)
        # Historical: `type(namedtuple) is tuple` is false, so extra_args are
        # wrapped with the namedtuple instead of concatenated.
        assert format_data([pt], (9,)) == [(pt, 9)]


def _response_future():
    """A ResponseFuture with none of the state the constructor would set"""
    from lithops.future import ResponseFuture
    return ResponseFuture.__new__(ResponseFuture)


class TestVerifyArgs:

    def test_futures_list_becomes_future_kwargs(self):
        futures = FuturesList(['f1', 'f2'])
        assert verify_args(lambda x: x, futures, None) == [
            {'future': 'f1'},
            {'future': 'f2'},
        ]

    def test_a_plain_list_of_futures_is_a_chain_too(self):
        """
        A slice of a FuturesList, or one built by a comprehension, is a plain
        list. Binding a future as if it were data fails with an error that
        says nothing about chaining
        """
        futures = [_response_future(), _response_future()]
        assert verify_args(lambda x, y: x, futures, None) == [
            {'future': futures[0]},
            {'future': futures[1]},
        ]

    def test_a_slice_of_a_futures_list_still_chains(self):
        futures = FuturesList([_response_future() for _ in range(3)])
        assert verify_args(lambda x: x, futures[:2], None) == [
            {'future': futures[0]},
            {'future': futures[1]},
        ]

    def test_futures_mixed_with_plain_data_raises(self):
        with pytest.raises(ValueError, match='mixes futures'):
            verify_args(lambda x: x, [_response_future(), 7], None)

    def test_extra_args_with_a_chain_raises(self):
        """
        The worker binds the previous result to the whole signature, leaving
        no room for them. Every activation would fail on a missing argument
        """
        futures = FuturesList([_response_future()])
        with pytest.raises(ValueError, match='extra_args is not supported'):
            verify_args(lambda x, factor: x, futures, (10,))

    def test_an_empty_futures_list_submits_nothing(self):
        assert verify_args(lambda x: x, FuturesList(), None) == []

    def test_positional_and_dict_binding(self):
        def fn(a, b):
            return a + b

        assert verify_args(fn, [(1, 2)], None) == [{'a': 1, 'b': 2}]
        assert verify_args(fn, [{'a': 1, 'b': 2, 'extra': 3}], None) == [
            {'a': 1, 'b': 2, 'extra': 3}
        ]

    def test_dict_missing_required_name_raises(self):
        def fn(a, b):
            return a + b

        with pytest.raises(ValueError, match='Check the args names'):
            verify_args(fn, [{'a': 1}], None)

    def test_var_keyword_allows_arbitrary_dicts(self):
        def fn(**kwargs):
            return kwargs

        assert verify_args(fn, [{'x': 1}], None) == [{'x': 1}]


class TestMiscUtils:

    def test_iterchunks(self):
        assert list(iterchunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
        assert list(iterchunks([], 3)) == []

    def test_agg_data(self):
        blob, ranges = agg_data([b'ab', b'cde'])
        assert blob == b'abcde'
        assert ranges == [(0, 1), (2, 4)]

    def test_split_object_url(self):
        assert split_object_url('cos://bucket/dir/file.txt') == (
            'ibm_cos', 'bucket', 'dir', 'file.txt'
        )
        assert split_object_url('s3://bucket/prefix/') == (
            'aws_s3', 'bucket', 'prefix', ''
        )
        assert split_object_url('bucket') == (None, 'bucket', '', '')
        assert split_object_url('bucket/key') == (None, 'bucket', '', 'key')

    def test_split_path(self):
        assert split_path('/bucket/dir/key') == ('bucket', 'dir/key')
        assert split_path('bucket') == ('bucket', None)
        assert split_path('bucket/') == ('bucket', '')

    def test_convert_bools_to_string_mutates_in_place(self):
        env = {'flag': True, 'count': 1, 'name': 'x'}
        assert convert_bools_to_string(env) is env
        assert env == {'flag': 'True', 'count': 1, 'name': 'x'}

    def test_is_lithops_worker(self, monkeypatch):
        monkeypatch.delenv('LITHOPS_WORKER', raising=False)
        assert is_lithops_worker() is False
        monkeypatch.setenv('LITHOPS_WORKER', '1')
        assert is_lithops_worker() is True

    def test_version_str_and_current_py_version(self):
        assert version_str((3, 12, 1)) == '3.12'
        assert CURRENT_PY_VERSION == version_str(__import__('sys').version_info)

    def test_verify_runtime_name(self):
        verify_runtime_name('python:3.12')
        with pytest.raises(AssertionError, match='not valid'):
            verify_runtime_name('bad name')

    def test_timeout_handler_raises(self):
        with pytest.raises(TimeoutError, match='too slow'):
            timeout_handler('too slow', None, None)

    def test_b64_dict_roundtrip(self):
        payload = {'a': 1, 'b': 'x'}
        assert b64str_to_dict(dict_to_b64str(payload)) == payload

    def test_is_object_processing_function(self):
        assert is_object_processing_function(lambda obj: obj)
        assert not is_object_processing_function(lambda x: x)

    def test_countdown_latch(self):
        latch = CountDownLatch(2)
        assert latch.done is False
        latch.unlock()
        assert latch.done is False
        latch.unlock()
        assert latch.done is True
        latch.wait()

    def test_countdown_latch_wait_returns_immediately_when_already_done(self):
        latch = CountDownLatch(0)
        latch.wait()
        assert latch.done is True

    def test_log_prefix_builds_executor_job_and_call_identity(self):
        assert log_prefix('sess-0') == 'ExecutorID sess-0'
        assert log_prefix('sess-0', 'M000') == 'ExecutorID sess-0 | JobID M000'
        assert log_prefix('sess-0', 'M000', '00007') == (
            'ExecutorID sess-0 | JobID M000 | CallID 00007'
        )

    def test_log_prefix_omits_job_when_only_call_is_set(self):
        # call_id without job_id is unusual but must not invent a JobID segment.
        assert log_prefix('sess-0', call_id='00007') == 'ExecutorID sess-0 | CallID 00007'

    def test_as_future_list_and_future_id(self):
        future = type('F', (), {'executor_id': 'e', 'job_id': 'j', 'call_id': 'c'})()
        assert _as_future_list(future) == [future]
        plain = [future]
        assert _as_future_list(plain) is plain
        assert _future_id(future) == ('e', 'j', 'c')

    def test_create_executor_id_reuses_session_and_increments(self, monkeypatch):
        monkeypatch.delenv('__LITHOPS_SESSION_ID', raising=False)
        monkeypatch.delenv('__LITHOPS_TOTAL_EXECUTORS', raising=False)
        first = create_executor_id(lenght=4)
        second = create_executor_id(lenght=4)
        session, num = first.rsplit('-', 1)
        assert len(session) == 4
        assert num == '0'
        assert second == f'{session}-1'
        assert get_executor_id() == second

    def test_monitoring_queue_chain_matches_the_shapes_in_use(self, monkeypatch):
        # These are the chains the id-derived formula produced, and every id
        # shape Lithops builds today. The chain must not change for them
        monkeypatch.delenv(MONITORING_QUEUES_ENV, raising=False)
        assert monitoring_queues('sess-0') == ['lithops-sess-0']

        # An executor created inside a worker task, whose session id is
        # job_key-call_id, or inside a remote invoker, whose session id is
        # job_key: both inherit the client's queue through the environment
        monkeypatch.setenv(MONITORING_QUEUES_ENV, '["lithops-sess-0"]')
        assert monitoring_queues('sess-0-M000-00000-0') == [
            'lithops-sess-0', 'lithops-sess-0-M000-00000-0'
        ]
        assert monitoring_queues('sess-0-M000-0') == [
            'lithops-sess-0', 'lithops-sess-0-M000-0'
        ]

    def test_monitoring_queue_chain_goes_deeper_than_the_old_formula(
        self, monkeypatch
    ):
        # The id-derived formula emitted 'lithops-sess-0-M000-0-M000' here,
        # a session id no monitor ever declares a queue for
        monkeypatch.setenv(
            MONITORING_QUEUES_ENV,
            '["lithops-sess-0", "lithops-sess-0-M000-0"]',
        )
        assert monitoring_queues('sess-0-M000-0-M000-0') == [
            'lithops-sess-0',
            'lithops-sess-0-M000-0',
            'lithops-sess-0-M000-0-M000-0',
        ]

    def test_monitoring_queues_does_not_repeat_a_queue(self, monkeypatch):
        monkeypatch.setenv(MONITORING_QUEUES_ENV, '["lithops-sess-0"]')
        assert monitoring_queues('sess-0') == ['lithops-sess-0']

    def test_monitoring_queues_ignores_a_malformed_environment(
        self, monkeypatch
    ):
        monkeypatch.setenv(MONITORING_QUEUES_ENV, 'not json')
        assert monitoring_queues('sess-0') == ['lithops-sess-0']

    def test_monitoring_queue_name(self):
        assert monitoring_queue_name('sess-0') == 'lithops-sess-0'

    def test_sizeof_fmt(self):
        assert sizeof_fmt(0) == '0.0B'
        assert sizeof_fmt(500) == '500.0B'
        assert sizeof_fmt(2048).endswith('KiB')
        assert sizeof_fmt(-2048).startswith('-')

    def test_bytes_b64_roundtrip(self):
        payload = b'hello'
        assert b64str_to_bytes(bytes_to_b64str(payload)) == payload

    def test_sdb_to_dict(self):
        item = {'Attributes': [{'Name': 'a', 'Value': '1'}, {'Name': 'b', 'Value': 'x'}]}
        assert sdb_to_dict(item) == {'a': '1', 'b': 'x'}

    def test_is_unix_and_linux(self, monkeypatch):
        monkeypatch.setattr('lithops.utils.platform.system', lambda: 'Darwin')
        assert is_unix_system() is True
        assert is_linux_system() is False
        monkeypatch.setattr('lithops.utils.platform.system', lambda: 'Windows')
        assert is_unix_system() is False
        monkeypatch.setattr('lithops.utils.platform.system', lambda: 'Linux')
        assert is_linux_system() is True

    def test_is_notebook_without_ipython(self):
        assert is_notebook() is False

    def test_create_futures_list_attaches_executor(self):
        executor = type('E', (), {'config': {'x': 1}})()
        fl = create_futures_list(['a'], executor)
        assert isinstance(fl, FuturesList)
        assert list(fl) == ['a']
        assert fl.executor is executor
        assert fl.config == {'x': 1}

    def test_split_object_url_unknown_scheme_is_kept(self):
        assert split_object_url('gs://bucket/dir/file') == (
            'gs', 'bucket', 'dir', 'file'
        )

    def test_format_data_without_extra_args_returns_same_list(self):
        data = [1, 2]
        assert format_data(data, None) is data
        assert format_data(data, []) is data

    def test_verify_args_with_tuple_extra_args(self):
        def fn(a, b):
            return a + b

        assert verify_args(fn, [(1,)], (2,)) == [{'a': 1, 'b': 2}]

    def test_get_docker_path_prefers_docker_then_podman(self, monkeypatch):
        monkeypatch.setattr('lithops.utils.shutil.which', lambda name: {
            'docker': '/usr/bin/docker',
            'podman': None,
        }[name])
        assert get_docker_path() == '/usr/bin/docker'
        monkeypatch.setattr('lithops.utils.shutil.which', lambda name: {
            'docker': None,
            'podman': '/usr/bin/podman',
        }[name])
        assert get_docker_path() == '/usr/bin/podman'
        monkeypatch.setattr('lithops.utils.shutil.which', lambda name: None)
        with pytest.raises(Exception, match='docker/podman command not found'):
            get_docker_path()

    def test_docker_login_requires_credentials(self):
        with pytest.raises(Exception, match='docker_user and docker_password'):
            docker_login(None, None, 'docker.io')
        with pytest.raises(Exception, match='docker_server is required'):
            docker_login('u', 'p', '')

    def test_get_default_container_name_variants(self):
        cfg = {'docker_server': 'docker.io', 'docker_user': 'alice'}
        name = get_default_container_name('ibm_cf', cfg, 'lithops')
        assert name.startswith('docker.io/alice/lithops-v')
        cfg = {'docker_server': 'icr.io', 'docker_namespace': 'ns'}
        name = get_default_container_name('ibm_cf', cfg, 'lithops')
        assert name.startswith('icr.io/ns/lithops-v')
        cfg = {
            'docker_server': 'us-docker.pkg.dev',
            'region': 'us',
            'project_name': 'proj',
        }
        name = get_default_container_name('gcp', cfg, 'lithops')
        assert name.startswith('us-docker.pkg.dev/proj/lithops/lithops-v')
        cfg = {'docker_server': 'example.registry'}
        name = get_default_container_name('k8s', cfg, 'lithops')
        assert name.startswith('example.registry/lithops-v')

    def test_get_default_container_name_missing_docker_user(self):
        with pytest.raises(Exception, match='docker_user'):
            get_default_container_name('ibm_cf', {'docker_server': 'docker.io'}, 'r')

    def test_is_podman(self, monkeypatch):
        monkeypatch.setattr(
            'lithops.utils.sp.check_output', lambda *a, **k: b'podman'
        )
        assert is_podman('/usr/bin/podman') is True
        monkeypatch.setattr(
            'lithops.utils.sp.check_output',
            lambda *a, **k: (_ for _ in ()).throw(Exception('nope')),
        )
        assert is_podman('/usr/bin/docker') is False

    def test_create_handler_zip(self, tmp_path):
        from lithops.utils import create_handler_zip
        entry = tmp_path / 'entry.py'
        entry.write_text('print(1)\n')
        dest = tmp_path / 'handler.zip'
        create_handler_zip(str(dest), [str(entry)])
        assert zipfile.is_zipfile(dest)
        with zipfile.ZipFile(dest) as zf:
            names = zf.namelist()
            assert 'entry.py' in names
            assert any(name.startswith('lithops/') for name in names)

    def test_create_handler_zip_skips_output_zip_and_caches(
        self, tmp_path, monkeypatch
    ):
        from lithops.utils import create_handler_zip

        pkg = tmp_path / 'lithops'
        pkg.mkdir()
        (pkg / '__init__.py').write_text('')
        (pkg / '__pycache__').mkdir()
        (pkg / '__pycache__' / 'mod.cpython-312.pyc').write_bytes(b'nope')
        pytest_cache = pkg / '.pytest_cache'
        pytest_cache.mkdir()
        (pytest_cache / 'v').write_text('nope')
        leftover = pkg / 'leftover.zip'
        leftover.write_bytes(b'PK' + b'\x00' * 32)

        monkeypatch.setattr('lithops.__file__', str(pkg / '__init__.py'))

        entry = tmp_path / 'entry.py'
        entry.write_text('print(1)\n')
        dest = pkg / 'handler.zip'
        create_handler_zip(str(dest), [str(entry)])

        with zipfile.ZipFile(dest) as zf:
            names = zf.namelist()
        assert 'entry.py' in names
        assert 'lithops/__init__.py' in names
        assert not any('__pycache__' in name for name in names)
        assert not any('.pytest_cache' in name for name in names)
        assert not any(name.endswith('.zip') for name in names)

    def test_wrapped_streaming_body_read_seek_and_eof(self):
        body = WrappedStreamingBody(io.BytesIO(b'hello world'), 11)
        assert body.read(5) == b'hello'
        assert body.tell() == 5
        # Historical: whence=0 does not apply offset; it returns the current pos.
        assert body.seek(0) == 5
        assert body.seek(2, 1) == 7
        assert body.seek(0, 2) == 11
        with pytest.raises(Exception, match='Unsupported'):
            body.seek(-1, 2)

        class Empty:
            def read(self, n=None):
                return ""

        with pytest.raises(EOFError):
            WrappedStreamingBody(Empty(), 1).read()

    def test_wrapped_streaming_body_partition_first_chunk(self):
        data = b'aaa\nbbb\nccc\n'
        part = WrappedStreamingBodyPartition(
            io.BytesIO(data), size=len(data), byterange=(0, len(data) - 1)
        )
        assert b'aaa' in part.read(100)

    def test_iterchunks_chunk_larger_than_list(self):
        assert list(iterchunks([1, 2], 10)) == [[1, 2]]

    def test_agg_data_empty(self):
        blob, ranges = agg_data([])
        assert blob == b''
        assert ranges == []

    def test_setup_logger_none_is_noop(self):
        with patch('lithops.utils.logging.config.dictConfig') as cfg:
            setup_lithops_logger(None)
            setup_lithops_logger('none')
            setup_lithops_logger('NONE')
            cfg.assert_not_called()

    def test_setup_logger_debug_uses_console_handler(self):
        with patch('lithops.utils.logging.config.dictConfig') as cfg:
            setup_lithops_logger('debug')
        config = cfg.call_args[0][0]
        assert config['loggers']['lithops']['handlers'] == ['console_handler']
        assert config['handlers']['console_handler']['level'] == logging.DEBUG
        assert config['handlers']['console_handler']['class'] == (
            'lithops.utils.ShutdownSafeStreamHandler'
        )

    def test_shutdown_safe_handler_ignores_closed_stream(self, capsys):
        stream = io.StringIO()
        handler = ShutdownSafeStreamHandler(stream)
        test_logger = logging.getLogger('lithops.test_closed_stream')
        test_logger.handlers = [handler]
        test_logger.propagate = False
        test_logger.setLevel(logging.DEBUG)
        stream.close()
        test_logger.debug('after close')

        class ClosedWrite:
            closed = False

            def write(self, msg):
                raise ValueError('I/O operation on closed file.')

            def flush(self):
                return None

        handler.stream = ClosedWrite()
        test_logger.debug('after failed write')
        captured = capsys.readouterr()
        assert 'Logging error' not in captured.err
        assert 'Logging error' not in captured.out

    def test_setup_logger_filename_uses_file_handler(self, tmp_path):
        log_file = str(tmp_path / 'lithops.log')
        with patch('lithops.utils.logging.config.dictConfig') as cfg:
            setup_lithops_logger('info', filename=log_file)
        config = cfg.call_args[0][0]
        assert config['loggers']['lithops']['handlers'] == ['file_handler']
        assert config['handlers']['file_handler']['filename'] == log_file

    def test_run_command_check_call_by_default(self):
        with patch('lithops.utils.sp.check_call') as call:
            run_command('echo hello')
        call.assert_called_once()
        assert call.call_args[0][0] == ['echo', 'hello']

    def test_run_command_return_result_strips_quotes(self):
        with patch('lithops.utils.sp.check_output', return_value='  "ok"  '):
            assert run_command('echo x', return_result=True) == 'ok'

    def test_run_command_input_uses_check_output_bytes(self):
        with patch('lithops.utils.sp.check_output', return_value=b'') as out:
            run_command('cat', input='secret')
        assert out.call_args.kwargs['input'] == b'secret'

    def test_find_free_port_returns_int(self):
        first = find_free_port()
        second = find_free_port()
        assert isinstance(first, int) and isinstance(second, int)
        assert 0 < first < 65536
        assert 0 < second < 65536

    def test_futures_list_map_wait_get_result_and_pickle(self):
        class Item:
            def __init__(self):
                self._produce_output = True

        executor = MagicMock()
        mapped = [Item()]
        executor.map.return_value = mapped
        executor.wait.return_value = ([], [])
        executor.get_result.return_value = [1]

        fl = FuturesList([Item()])
        fl.executor = executor
        fl.config = {}
        result = fl.map(lambda x: x, sync=True)
        executor.wait.assert_called()
        executor.map.assert_called()
        assert result is fl
        assert list(fl) == mapped
        fl.wait()
        assert fl.get_result() == [1]

        fl2 = FuturesList([1, 2])
        executor = object()
        fl2.executor = executor
        dumped = pickle.dumps(fl2)
        # Pickling reports the list, it does not consume it: the executor of
        # the one being pickled has to survive
        assert fl2.executor is executor
        loaded = pickle.loads(dumped)
        assert list(loaded) == [1, 2]
        assert loaded.executor is None

    def test_wrapped_streaming_body_partition_middle_chunk_discards_partial_row(self):
        data = b'aaa\nbbb\nccc\n'
        part = WrappedStreamingBodyPartition(
            io.BytesIO(data[2:]), size=len(data[2:]), byterange=(2, len(data) - 1)
        )
        assert part.read(100) == b'bbb\nccc\n'

    def test_wrapped_streaming_body_partition_readline_discards_partial_row(self):
        class Stream:
            def __init__(self, payload):
                self._raw_stream = io.BytesIO(payload)

            def read(self, n=None):
                return self._raw_stream.read(-1 if n is None else n)

        data = b'aaa\nbbb\nccc\n'
        part = WrappedStreamingBodyPartition(
            Stream(data[2:]), size=len(data[2:]), byterange=(2, len(data) - 1)
        )
        assert part.readline() == b'bbb\n'

    def test_create_handler_zip_removes_partial_zip_on_write_error(self, tmp_path):
        from lithops.utils import create_handler_zip

        entry = tmp_path / 'entry.py'
        entry.write_text('print(1)\n')
        dest = tmp_path / 'handler.zip'

        def boom(self, *args, **kwargs):
            raise RuntimeError('disk full')

        with patch.object(zipfile.ZipFile, 'write', boom):
            with pytest.raises(Exception, match='Unable to create'):
                create_handler_zip(str(dest), [str(entry)])
        assert not dest.exists()

    def test_create_handler_zip_removes_partial_zip_on_keyboard_interrupt(
        self, tmp_path
    ):
        from lithops.utils import create_handler_zip

        entry = tmp_path / 'entry.py'
        entry.write_text('print(1)\n')
        dest = tmp_path / 'handler.zip'

        def boom(self, *args, **kwargs):
            raise KeyboardInterrupt()

        with patch.object(zipfile.ZipFile, 'write', boom):
            with pytest.raises(KeyboardInterrupt):
                create_handler_zip(str(dest), [str(entry)])
        assert not dest.exists()
