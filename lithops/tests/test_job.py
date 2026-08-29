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

import errno
import logging
import os
import pickle
from functools import partial
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lithops.constants import LOCALHOST, MAX_AGG_DATA_SIZE, SERVERLESS, STANDALONE
from lithops.job import create_map_job, create_reduce_job
from lithops.job.job import (
    FUNCTION_CACHE,
    MAX_DATA_IN_PAYLOAD,
    _FUNC_SERIALIZE_CACHE,
    _store_func_and_modules,
    invalidate_function_cache,
)
from lithops.job.partitioner import CHUNK_THRESHOLD, create_partitions
from lithops.job.serialize import SerializeIndependent, create_module_data
from lithops.storage.utils import (
    CloudObject,
    CloudObjectLocal,
    CloudObjectUrl,
    create_func_key,
    func_key_suffix,
)
from lithops.utils import BackendType, bytes_to_b64str


def _echo(x):
    return x


def _obj_fn(obj):
    return obj


def _reduce_fn(results):
    return results


class _Adder:
    def __call__(self, x):
        return x + 1


class _NoCall:
    pass


class _CapturingSerializer:
    last = None

    def __init__(self, preinstalls):
        self.preinstalls = preinstalls

    def __call__(self, objs, inc_modules, exc_modules):
        type(self).last = (inc_modules, exc_modules, objs)
        return ([b'func'] + [b'data'] * (len(objs) - 1), set())


def _job_config(
    mode=LOCALHOST,
    backend=None,
    backend_type=BackendType.FAAS.value,
    **lithops
):
    backend = backend or mode
    return {
        'lithops': {
            'mode': mode,
            'backend': backend,
            'chunksize': 1,
            'execution_timeout': 100,
            'backend_type': backend_type,
            **lithops,
        },
        backend: {
            'worker_processes': 2,
            'runtime_memory': 256,
        },
        STANDALONE: {
            'worker_processes': 2,
            'hard_dismantle_timeout': 50,
        },
    }


def _runtime_meta(**extra):
    meta = {'preinstalls': [['os', True]], 'runtime_timeout': 30}
    meta.update(extra)
    return meta


def _storage():
    internal = MagicMock()
    internal.backend = 'localhost'
    internal.storage = MagicMock()
    return internal


@pytest.fixture
def fresh_function_cache():
    saved = set(FUNCTION_CACHE)
    saved_serialize = {func: dict(entries) for func, entries in _FUNC_SERIALIZE_CACHE.items()}
    FUNCTION_CACHE.clear()
    _FUNC_SERIALIZE_CACHE.clear()
    yield FUNCTION_CACHE
    FUNCTION_CACHE.clear()
    FUNCTION_CACHE.update(saved)
    _FUNC_SERIALIZE_CACHE.clear()
    _FUNC_SERIALIZE_CACHE.update(saved_serialize)


@pytest.fixture
def capturing_serializer(monkeypatch):
    _CapturingSerializer.last = None
    monkeypatch.setattr(
        'lithops.job.job.SerializeIndependent', _CapturingSerializer
    )
    return _CapturingSerializer


def _make_map_job(
    *,
    func=_echo,
    iterdata=[1, 2],
    extra_env=None,
    include_modules=[],
    exclude_modules=None,
    execution_timeout=None,
    runtime_memory=None,
    chunksize=None,
    extra_args=None,
    config=None,
    internal_storage=None,
    executor_id='exec',
    job_id='j0',
    runtime_meta=None,
    **map_kwargs
):
    return create_map_job(
        config=config or _job_config(),
        internal_storage=internal_storage or _storage(),
        executor_id=executor_id,
        job_id=job_id,
        map_function=func,
        iterdata=iterdata,
        runtime_meta=runtime_meta or _runtime_meta(),
        runtime_memory=runtime_memory,
        extra_env=extra_env,
        include_modules=include_modules,
        exclude_modules=exclude_modules,
        execution_timeout=execution_timeout,
        chunksize=chunksize,
        extra_args=extra_args,
        **map_kwargs
    )


@pytest.mark.usefixtures('capturing_serializer', 'fresh_function_cache')
class TestCreateMapJob:

    def test_basic_job_fields(self):
        storage = _storage()
        job = _make_map_job(internal_storage=storage)
        assert job.executor_id == 'exec'
        assert job.job_id == 'j0'
        assert job.job_key == 'exec-j0'
        assert job.function_name == '_echo'
        assert job.total_calls == 2
        assert job.chunksize == 1
        assert job.worker_processes == 2
        assert job.runtime_memory is None
        assert job.runtime_timeout is None
        assert job.data_key is None
        assert job.data_byte_ranges is None
        assert job.data_byte_strs == [b'data', b'data']
        storage.put_func.assert_called_once()
        storage.put_data.assert_not_called()
        assert job.func_key in FUNCTION_CACHE

    def test_callable_class_function_name(self):
        job = _make_map_job(func=_Adder())
        assert job.function_name == '_Adder'

    def test_bound_method_function_name(self):
        job = _make_map_job(func=_Adder().__call__)
        assert job.function_name == '__call__'

    def test_extra_env_bools_converted_on_copy(self):
        extra = {'FLAG': True, 'N': 1}
        job = _make_map_job(extra_env=extra)
        assert extra['FLAG'] is True
        assert job.extra_env['FLAG'] == 'True'
        assert job.extra_env['N'] == 1

    def test_none_extra_env_becomes_empty(self):
        job = _make_map_job()
        assert job.extra_env == {}

    def test_zero_timeout_and_chunksize_are_kept(self):
        job = _make_map_job(execution_timeout=0, chunksize=0)
        assert job.execution_timeout == 0
        assert job.chunksize == 0

    def test_chunksize_overrides_config_default(self):
        job = _make_map_job(chunksize=7)
        assert job.chunksize == 7

    def test_serverless_clamps_timeout(self):
        cfg = _job_config(mode=SERVERLESS, backend='ibm_cf')
        job = _make_map_job(config=cfg, execution_timeout=100)
        assert job.runtime_memory == 256
        assert job.runtime_timeout == 30
        assert job.execution_timeout == 25

    def test_serverless_keeps_timeout_below_runtime(self):
        cfg = _job_config(mode=SERVERLESS, backend='ibm_cf')
        job = _make_map_job(config=cfg, execution_timeout=10, runtime_memory=512)
        assert job.runtime_memory == 512
        assert job.execution_timeout == 10

    def test_standalone_clamps_timeout(self):
        cfg = _job_config(mode=STANDALONE, backend='aws_ec2')
        job = _make_map_job(config=cfg)
        assert job.runtime_memory is None
        assert job.execution_timeout == 40

    def test_unknown_mode_is_not_standalone_substring(self):
        cfg = _job_config(mode='a', backend='aws_ec2')
        job = _make_map_job(config=cfg)
        assert job.runtime_memory is None
        assert job.runtime_timeout is None
        assert job.execution_timeout == 100

    def test_function_cache_skips_second_upload(self):
        storage = _storage()
        _make_map_job(internal_storage=storage)
        _make_map_job(internal_storage=storage)
        storage.put_func.assert_called_once()

    def test_function_cache_reuploads_after_invalidate(self):
        storage = _storage()
        job = _make_map_job(internal_storage=storage)
        storage.put_func.assert_called_once()
        invalidate_function_cache(job.executor_id)
        _make_map_job(internal_storage=storage)
        assert storage.put_func.call_count == 2

    def test_batch_backend_always_uploads_data(self):
        storage = _storage()
        cfg = _job_config(backend_type=BackendType.BATCH.value)
        job = _make_map_job(config=cfg, internal_storage=storage)
        storage.put_data.assert_called_once()
        assert job.data_key is not None
        assert job.data_byte_ranges is not None
        assert not hasattr(job, 'data_byte_strs')

    def test_data_limit_raises(self):
        cfg = _job_config(data_limit=1e-9)
        with pytest.raises(Exception, match='exceeded maximum size'):
            _make_map_job(config=cfg)

    def test_data_limit_zero_skips_check(self):
        job = _make_map_job(config=_job_config(data_limit=0))
        assert job.total_calls == 2

    def test_missing_data_limit_uses_constant(self, monkeypatch):
        monkeypatch.setattr('lithops.job.job.MAX_AGG_DATA_SIZE', 1e-12)
        cfg = _job_config()
        assert 'data_limit' not in cfg['lithops']
        with pytest.raises(Exception, match='exceeded maximum size'):
            _make_map_job(config=cfg)
        assert MAX_AGG_DATA_SIZE == 4

    def test_include_modules_none_string(self):
        _make_map_job(config=_job_config(include_modules='none'))
        inc, exc, _ = _CapturingSerializer.last
        assert inc is None
        assert exc == set()

    def test_include_modules_invalid_string_raises(self):
        cfg = _job_config(include_modules='all')
        with pytest.raises(ValueError, match='must be a list'):
            _make_map_job(config=cfg)

    def test_include_modules_cfg_none_and_arg_none(self):
        _make_map_job(
            config=_job_config(include_modules='NONE'),
            include_modules=None,
        )
        inc, _, _ = _CapturingSerializer.last
        assert inc is None

    def test_include_modules_empty_cfg_and_empty_arg_is_empty_set(self):
        _make_map_job(include_modules=[])
        inc, _, _ = _CapturingSerializer.last
        assert inc == set()

    def test_include_modules_arg_none_overrides_empty_cfg(self):
        _make_map_job(include_modules=None)
        inc, _, _ = _CapturingSerializer.last
        assert inc is None

    def test_include_and_exclude_union(self):
        cfg = _job_config(include_modules=['a'], exclude_modules=['x'])
        _make_map_job(config=cfg, include_modules=['b'], exclude_modules=['y'])
        inc, exc, _ = _CapturingSerializer.last
        assert inc == {'a', 'b'}
        assert exc == {'x', 'y'}

    def test_object_processing_sets_parts(self):
        with patch(
            'lithops.job.job.create_partitions',
            return_value=([{'obj': 'x'}], [2, 3]),
        ) as cp:
            job = _make_map_job(func=_obj_fn, iterdata=['http://example.com/a'])
        assert job.parts_per_object == [2, 3]
        assert cp.called
        assert 'host_job_create_partitions_time' in job.metadata

    def test_empty_parts_per_object_not_attached(self):
        with patch(
            'lithops.job.job.create_partitions',
            return_value=([{'obj': 'x'}], []),
        ):
            job = _make_map_job(func=_obj_fn, iterdata=['http://example.com/a'])
        assert not hasattr(job, 'parts_per_object')

    def test_empty_object_iterdata_creates_empty_job(self):
        job = _make_map_job(func=_obj_fn, iterdata=[])
        assert job.total_calls == 0
        assert not hasattr(job, 'parts_per_object')

    def test_runtime_include_function(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.job.job.CUSTOM_RUNTIME_DIR', str(tmp_path))
        cfg = _job_config()
        cfg[LOCALHOST]['runtime_include_function'] = True
        storage = _storage()
        job = _make_map_job(config=cfg, internal_storage=storage)
        storage.put_func.assert_not_called()
        assert job.func_key == func_key_suffix
        assert job.ext_runtime_uuid
        assert os.path.isdir(job.local_tmp_dir)
        func_path = os.path.join(job.local_tmp_dir, job.func_key)
        assert os.path.isfile(func_path)
        with open(func_path, 'rb') as f:
            assert pickle.load(f) == {'func': b'func'}

    def test_metadata_timings_present(self):
        job = _make_map_job()
        meta = job.metadata
        assert 'host_job_create_tstamp' in meta
        assert 'host_job_serialize_time' in meta
        assert 'func_data_size_bytes' in meta
        assert 'func_module_size_bytes' in meta
        assert 'host_func_upload_time' in meta
        assert 'host_data_upload_time' in meta
        assert 'host_job_created_time' in meta


@pytest.mark.usefixtures('capturing_serializer', 'fresh_function_cache')
class TestCreateReduceJob:

    def test_single_iterdata_without_parts(self):
        job = create_reduce_job(
            config=_job_config(),
            internal_storage=_storage(),
            executor_id='exec',
            reduce_job_id='r0',
            reduce_function=_reduce_fn,
            map_job=SimpleNamespace(),
            map_futures=list(range(6)),
            runtime_meta=_runtime_meta(),
            runtime_memory=None,
            obj_reduce_by_key=False,
            extra_env=None,
            include_modules=[],
            exclude_modules=None,
        )
        assert job.job_id == 'r0'
        assert job.total_calls == 1
        assert job.extra_env['__LITHOPS_REDUCE_JOB'] == 'True'
        _, _, objs = _CapturingSerializer.last
        assert objs[1]['results'] == list(range(6))

    def test_reduce_by_key_slices_futures(self):
        job = create_reduce_job(
            config=_job_config(),
            internal_storage=_storage(),
            executor_id='exec',
            reduce_job_id='r0',
            reduce_function=_reduce_fn,
            map_job=SimpleNamespace(parts_per_object=[2, 3, 1]),
            map_futures=['a', 'b', 'c', 'd', 'e', 'f'],
            runtime_meta=_runtime_meta(),
            runtime_memory=None,
            obj_reduce_by_key=True,
            extra_env={'K': False},
            include_modules=[],
            exclude_modules=None,
        )
        assert job.total_calls == 3
        assert job.extra_env['K'] == 'False'
        assert job.extra_env['__LITHOPS_REDUCE_JOB'] == 'True'
        _, _, objs = _CapturingSerializer.last
        assert [o['results'] for o in objs[1:]] == [
            ['a', 'b'], ['c', 'd', 'e'], ['f']
        ]

    def test_parts_without_reduce_by_key_stays_one_call(self):
        job = create_reduce_job(
            config=_job_config(),
            internal_storage=_storage(),
            executor_id='exec',
            reduce_job_id='r0',
            reduce_function=_reduce_fn,
            map_job=SimpleNamespace(parts_per_object=[2, 2]),
            map_futures=list(range(4)),
            runtime_meta=_runtime_meta(),
            runtime_memory=None,
            obj_reduce_by_key=False,
            extra_env=None,
            include_modules=[],
            exclude_modules=None,
        )
        assert job.total_calls == 1


class TestLargePayloadAndCache:

    def test_large_payload_uploads_data(self, monkeypatch, fresh_function_cache):
        class _Big:
            def __init__(self, preinstalls):
                pass

            def __call__(self, objs, inc, exc):
                payload = b'x' * (MAX_DATA_IN_PAYLOAD + 1)
                return ([b'f'] + [payload] * (len(objs) - 1), set())

        monkeypatch.setattr('lithops.job.job.SerializeIndependent', _Big)
        storage = _storage()
        job = create_map_job(
            config=_job_config(),
            internal_storage=storage,
            executor_id='exec',
            job_id='j0',
            map_function=_echo,
            iterdata=[1],
            runtime_meta=_runtime_meta(),
            runtime_memory=None,
            extra_env=None,
            include_modules=[],
            exclude_modules=None,
            execution_timeout=None,
        )
        storage.put_data.assert_called_once()
        assert job.data_key is not None


class TestFuncSerializeCache:

    def test_second_map_skips_cloudpickle_of_same_function(
        self, monkeypatch, fresh_function_cache
    ):
        dumped = []
        import cloudpickle
        real_dumps = cloudpickle.dumps

        def tracking_dumps(obj):
            dumped.append(obj)
            return real_dumps(obj)

        monkeypatch.setattr(
            'lithops.job.serialize.cloudpickle.dumps', tracking_dumps
        )
        storage = _storage()
        _make_map_job(
            internal_storage=storage, func=_echo, iterdata=[1, 2]
        )
        assert dumped.count(_echo) == 1
        data_dumps = [obj for obj in dumped if obj is not _echo]
        assert len(data_dumps) == 2

        _make_map_job(
            internal_storage=storage, func=_echo, iterdata=[3, 4]
        )
        assert dumped.count(_echo) == 1
        data_dumps = [obj for obj in dumped if obj is not _echo]
        assert len(data_dumps) == 4


class TestInvalidateFunctionCache:

    def test_drops_only_matching_executor(self, fresh_function_cache):
        keep = create_func_key('other-1', 'aaa')
        drop = create_func_key('exec-0', 'bbb')
        similar = create_func_key('exec-0-extra', 'ccc')
        FUNCTION_CACHE.update({keep, drop, similar})
        invalidate_function_cache('exec-0')
        assert keep in FUNCTION_CACHE
        assert drop not in FUNCTION_CACHE
        assert similar in FUNCTION_CACHE


class TestStoreFuncAndModules:

    def test_writes_func_pickle(self, tmp_path):
        _store_func_and_modules(str(tmp_path), 'func.pickle', b'abc', None)
        with open(tmp_path / 'func.pickle', 'rb') as f:
            assert pickle.load(f) == {'func': b'abc'}

    def test_writes_modules_and_strips_leading_slash(self, tmp_path):
        payload = bytes_to_b64str(b'hello')
        _store_func_and_modules(
            str(tmp_path),
            'func.pickle',
            b'f',
            {'/pkg/mod.py': payload, '/pkg/other.py': payload},
        )
        assert (tmp_path / 'modules' / 'pkg' / 'mod.py').read_bytes() == b'hello'
        assert (tmp_path / 'modules' / 'pkg' / 'other.py').read_bytes() == b'hello'

    def test_writes_nested_posix_module_keys_to_native_paths(self, tmp_path):
        payload = bytes_to_b64str(b'nested')
        _store_func_and_modules(
            str(tmp_path),
            'func.pickle',
            b'f',
            {'pkg/sub/mod.py': payload},
        )
        written = tmp_path / 'modules' / 'pkg' / 'sub' / 'mod.py'
        assert written.read_bytes() == b'nested'

    def test_makedirs_errno_17_is_ignored(self, tmp_path):
        payload = bytes_to_b64str(b'x')
        _store_func_and_modules(
            str(tmp_path),
            'func.pickle',
            b'f',
            {'pkg/a.py': payload, 'pkg/b.py': payload},
        )
        assert (tmp_path / 'modules' / 'pkg' / 'a.py').read_bytes() == b'x'
        assert (tmp_path / 'modules' / 'pkg' / 'b.py').read_bytes() == b'x'

    def test_makedirs_uses_exist_ok(self, tmp_path, monkeypatch):
        real = os.makedirs

        def _makedirs(path, exist_ok=False):
            if not exist_ok:
                raise OSError(errno.EACCES, 'denied')
            return real(path, exist_ok=exist_ok)

        monkeypatch.setattr(os, 'makedirs', _makedirs)
        _store_func_and_modules(
            str(tmp_path),
            'func.pickle',
            b'f',
            {'a.py': bytes_to_b64str(b'x')},
        )
        assert (tmp_path / 'modules' / 'a.py').read_bytes() == b'x'


class TestSerializeIndependent:

    def test_init_does_not_mutate_preinstalls(self):
        pre = [['os', True]]
        ser = SerializeIndependent(pre)
        assert pre == [['os', True]]
        assert ser.preinstalled_modules == [['os', True], ['lithops', True]]
        SerializeIndependent(pre)
        assert pre == [['os', True]]

    def test_module_paths_does_not_dump(self, monkeypatch):
        dumped = []
        import cloudpickle
        real_dumps = cloudpickle.dumps

        def tracking_dumps(obj):
            dumped.append(obj)
            return real_dumps(obj)

        monkeypatch.setattr(
            'lithops.job.serialize.cloudpickle.dumps', tracking_dumps
        )
        ser = SerializeIndependent([['os', True]])
        paths = ser.module_paths([_echo], None, set())
        assert paths == set()
        assert dumped == []
        strs = ser.dumps([_echo, 1])
        assert dumped == [_echo, 1]
        assert pickle.loads(strs[1]) == 1

    def test_include_modules_none_skips_manager(self):
        ser = SerializeIndependent([['os', True]])
        strs, paths = ser([_echo, 1], None, [])
        assert len(strs) == 2
        assert paths == set()
        assert pickle.loads(strs[1]) == 1

    def test_explicit_include_skips_missing_file(self):
        ser = SerializeIndependent([['os', True]])
        _, paths = ser([_echo], ['no-such-module.py'], [])
        assert paths == set()

    def test_explicit_include_existing_py_file(self, tmp_path):
        mod = tmp_path / 'custom.py'
        mod.write_text('x = 1\n')
        ser = SerializeIndependent([['os', True]])
        _, paths = ser([_echo], [str(mod)], [])
        assert os.path.abspath(str(mod)) in paths

    def test_explicit_include_skips_preinstalled(self):
        ser = SerializeIndependent([['json', True]])
        _, paths = ser([_echo], ['json.decoder'], [])
        assert paths == set()

    def test_explicit_include_importable_module(self):
        ser = SerializeIndependent([['os', True]])
        _, paths = ser([_echo], ['json'], [])
        assert paths
        assert any('json' in p for p in paths)

    def test_explicit_include_missing_module(self):
        ser = SerializeIndependent([['os', True]])
        _, paths = ser([_echo], ['definitely_not_a_module_xyz'], [])
        assert paths == set()

    def test_class_without_call_raises(self):
        ser = SerializeIndependent([['os', True]])
        with pytest.raises(ValueError, match='__call__'):
            ser._module_inspect(_NoCall())

    def test_callable_class_inspect(self):
        ser = SerializeIndependent([['os', True]])
        mods = ser._module_inspect(_Adder())
        assert _echo.__module__.split('.')[0] in mods

    def test_partial_inspects_func(self):
        ser = SerializeIndependent([['os', True]])
        mods = ser._module_inspect(partial(_echo, 1))
        assert _echo.__module__.split('.')[0] in mods

    def test_dict_iterdata_with_function(self):
        ser = SerializeIndependent([['os', True]])
        mods = ser._module_inspect({'fn': _echo, 'n': 1})
        assert _echo.__module__.split('.')[0] in mods

    def test_cython_function_name_inspects_globals(self):
        class cython_function_or_method:
            __globals__ = {'__file__': '/tmp/foo.pyx'}

        ser = SerializeIndependent([['os', True]])
        mods = ser._module_inspect(cython_function_or_method())
        assert mods == {'/tmp/foo'}

    def test_empty_include_inspects_function(self):
        ser = SerializeIndependent([['os', True]])
        strs, paths = ser([_echo], [], ['lithops'])
        assert len(strs) == 1
        assert isinstance(paths, set)

    def test_so_origin_added_unless_excluded(self):
        ser = SerializeIndependent([['os', True]])
        spec = SimpleNamespace(origin='/opt/ext.so')
        with patch('importlib.util.find_spec', return_value=spec):
            with patch(
                'lithops.job.serialize.ModuleDependencyAnalyzer'
            ) as mda:
                mda.return_value.get_and_clear_paths.return_value = set()
                _, paths = ser([_echo], [], [])
        assert '/opt/ext.so' in paths

        with patch('importlib.util.find_spec', return_value=spec):
            with patch(
                'lithops.job.serialize.ModuleDependencyAnalyzer'
            ) as mda:
                mda.return_value.get_and_clear_paths.return_value = set()
                _, excluded = ser([_echo], [], ['ext.so'])
        assert '/opt/ext.so' not in excluded

    def test_find_spec_exception_is_swallowed(self):
        ser = SerializeIndependent([['os', True]])
        with patch('importlib.util.find_spec', side_effect=ValueError('x')):
            with patch(
                'lithops.job.serialize.ModuleDependencyAnalyzer'
            ) as mda:
                mda.return_value.get_and_clear_paths.return_value = {'/m'}
                _, paths = ser([_echo], [], [])
        assert '/m' in paths


class TestCreateModuleData:

    def test_empty_paths(self):
        assert create_module_data(set()) == {}
        assert create_module_data([]) == {}

    def test_file_path(self, tmp_path):
        f = tmp_path / 'mod.py'
        f.write_bytes(b'abc')
        data = create_module_data([str(f)])
        assert list(data) == [f.name]
        assert data[f.name] == bytes_to_b64str(b'abc')

    def test_directory_collects_nested_py(self, tmp_path):
        pkg = tmp_path / 'pkg'
        pkg.mkdir()
        (pkg / 'a.py').write_bytes(b'a')
        nested = pkg / 'sub'
        nested.mkdir()
        (nested / 'b.py').write_bytes(b'b')
        (nested / 'skip.txt').write_bytes(b'no')
        data = create_module_data([str(pkg)])
        posix_keys = set(data)
        assert posix_keys == {'pkg/a.py', 'pkg/sub/b.py'}
        assert all('\\' not in k for k in posix_keys)


def _head(headers):
    return MagicMock(headers=headers)


class _LogCatcher(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _catch_partitioner_logs():
    logger = logging.getLogger('lithops.job.partitioner')
    handler = _LogCatcher()
    logger.addHandler(handler)
    prev = logger.level
    logger.setLevel(logging.DEBUG)
    return logger, handler, prev


class TestCreatePartitions:

    def test_empty_iterdata_returns_empty_partitions(self):
        assert create_partitions({}, _storage(), [], None, None, '\n') == (
            [],
            [],
        )

    def test_http_takes_precedence_over_paths(self, tmp_path):
        f = tmp_path / 'f.txt'
        f.write_bytes(b'hello world!!')
        headers = {'content-length': '13', 'accept-ranges': 'bytes'}
        with patch(
            'lithops.job.partitioner.requests.head', return_value=_head(headers)
        ):
            parts, ppo = create_partitions(
                {},
                _storage(),
                [{'obj': 'http://example.com/a'}, {'obj': str(f)}],
                None,
                None,
                None,
            )
        assert all(isinstance(p['obj'], CloudObjectUrl) for p in parts)
        assert ppo == [1]

    def test_https_is_treated_as_url(self):
        headers = {'content-length': '10', 'accept-ranges': 'bytes'}
        with patch(
            'lithops.job.partitioner.requests.head', return_value=_head(headers)
        ):
            parts, ppo = create_partitions(
                {},
                _storage(),
                [{'obj': 'https://example.com/a'}],
                None,
                None,
                None,
            )
        assert isinstance(parts[0]['obj'], CloudObjectUrl)
        assert ppo == [1]

    def test_url_without_content_length_sets_size_one(self):
        with patch(
            'lithops.job.partitioner.requests.head',
            return_value=_head({'accept-ranges': 'bytes'}),
        ):
            parts, ppo = create_partitions(
                {},
                _storage(),
                [{'obj': 'http://example.com/a'}],
                None,
                None,
                '\n',
            )
        assert len(parts) == 1
        assert ppo == [1]
        assert parts[0]['obj'].chunk_size == 1

    def test_url_without_accept_ranges_uses_full_object(self):
        with patch(
            'lithops.job.partitioner.requests.head',
            return_value=_head({'content-length': '100'}),
        ):
            parts, ppo = create_partitions(
                {},
                _storage(),
                [{'obj': 'http://example.com/a'}],
                10,
                None,
                None,
            )
        assert len(parts) == 1
        assert parts[0]['obj'].data_byte_range is None
        assert parts[0]['obj'].chunk_size == 100
        assert ppo == [1]

    def test_url_chunk_size_without_newline(self):
        headers = {'content-length': '10000', 'accept-ranges': 'bytes'}
        with patch(
            'lithops.job.partitioner.requests.head', return_value=_head(headers)
        ):
            parts, ppo = create_partitions(
                {},
                _storage(),
                [{'obj': 'http://example.com/a'}],
                4000,
                None,
                None,
            )
        assert ppo == [3]
        assert parts[0]['obj'].data_byte_range == (0, 3999)
        assert parts[1]['obj'].data_byte_range == (4000, 7999)
        assert parts[2]['obj'].data_byte_range == (8000, 11999)
        assert parts[0]['obj'].part == 1
        assert parts[0]['obj'].total_parts == 3
        assert parts[0]['obj'].newline is None

    def test_url_chunk_number(self):
        headers = {'content-length': '100', 'accept-ranges': 'bytes'}
        with patch(
            'lithops.job.partitioner.requests.head', return_value=_head(headers)
        ):
            parts, ppo = create_partitions(
                {},
                _storage(),
                [{'obj': 'http://example.com/a'}],
                None,
                2,
                None,
            )
        assert ppo == [2]
        assert len(parts) == 2

    def test_url_newline_uses_chunk_threshold(self):
        headers = {'content-length': '10000', 'accept-ranges': 'bytes'}
        with patch(
            'lithops.job.partitioner.requests.head', return_value=_head(headers)
        ):
            parts, _ = create_partitions(
                {},
                _storage(),
                [{'obj': 'http://example.com/a'}],
                4000,
                None,
                '\n',
            )
        assert parts[0]['obj'].data_byte_range == (0, 4000 + CHUNK_THRESHOLD)

    def test_swapped_chunk_logs(self):
        headers = {'content-length': '10', 'accept-ranges': 'bytes'}
        logger, handler, prev = _catch_partitioner_logs()
        try:
            with patch(
                'lithops.job.partitioner.requests.head',
                return_value=_head(headers),
            ):
                create_partitions(
                    {},
                    _storage(),
                    [{'obj': 'http://example.com/a'}],
                    None,
                    2,
                    None,
                )
            assert 'Chunk number set to 2' in handler.messages

            handler.messages.clear()
            with patch(
                'lithops.job.partitioner.requests.head',
                return_value=_head(headers),
            ):
                create_partitions(
                    {},
                    _storage(),
                    [{'obj': 'http://example.com/a'}],
                    10,
                    None,
                    None,
                )
            assert 'Chunk size set to 10' in handler.messages

            handler.messages.clear()
            with patch(
                'lithops.job.partitioner.requests.head',
                return_value=_head(headers),
            ):
                create_partitions(
                    {},
                    _storage(),
                    [{'obj': 'http://example.com/a'}],
                    None,
                    None,
                    None,
                )
            assert 'Chunk size and chunk number not set' in handler.messages
            assert 'Chunk size and chunk number not set ' not in handler.messages
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prev)

    def test_paths_file_and_directory(self, tmp_path):
        d = tmp_path / 'd'
        d.mkdir()
        f1 = d / 'a.txt'
        f1.write_bytes(b'hello world!!')
        nested = d / 'sub'
        nested.mkdir()
        f2 = tmp_path / 'b.txt'
        f2.write_bytes(b'hello world!!')
        parts, ppo = create_partitions(
            {},
            _storage(),
            [{'obj': str(d), 'k': 1}, {'obj': str(f2)}, {'obj': str(f2)}],
            None,
            None,
            None,
        )
        paths = {p['obj'].path for p in parts}
        assert str(f1) in paths
        assert str(f2) in paths
        assert str(nested) not in paths
        assert all(isinstance(p['obj'], CloudObjectLocal) for p in parts)
        for p in parts:
            if p['obj'].path == str(f1):
                assert p['k'] == 1
            else:
                assert 'k' not in p
        assert ppo == [1, 1]

    def test_path_one_byte_file_has_one_partition(self, tmp_path):
        f = tmp_path / 'tiny.txt'
        f.write_bytes(b'x')
        parts, ppo = create_partitions(
            {}, _storage(), [{'obj': str(f)}], None, None, None
        )
        assert len(parts) == 1
        assert ppo == [1]
        assert parts[0]['obj'].chunk_size == 1

    def test_object_storage_head_and_params(self):
        internal = _storage()
        internal.storage.head_object.return_value = {'content-length': '100'}
        parts, ppo = create_partitions(
            {},
            internal,
            [{'obj': 'localhost://bucket/dir/file.txt', 'n': 7}],
            None,
            None,
            None,
        )
        internal.storage.head_object.assert_called_once()
        object_key = internal.storage.head_object.call_args[0][1]
        assert object_key == 'dir/file.txt'
        assert '\\' not in object_key
        assert parts[0]['obj'].key == 'dir/file.txt'
        assert len(parts) == 1
        assert isinstance(parts[0]['obj'], CloudObject)
        assert parts[0]['n'] == 7
        assert parts[0]['obj'].backend == 'localhost'
        assert parts[0]['obj'].bucket == 'bucket'
        assert ppo == [1]

    def test_object_storage_cloudobject_type_is_converted(self):
        internal = _storage()
        internal.storage.head_object.return_value = {'content-length': '20'}
        co = CloudObject('localhost', 'bucket', 'k')
        parts, _ = create_partitions(
            {}, internal, [{'obj': co}], None, None, None
        )
        assert parts[0]['obj'].key.endswith('k')

    def test_object_storage_missing_scheme_uses_backend(self):
        internal = _storage()
        internal.storage.list_objects.return_value = [
            {'Key': 'a', 'Size': 20}
        ]
        parts, _ = create_partitions(
            {}, internal, [{'obj': 'bucket'}], None, None, None
        )
        internal.storage.list_objects.assert_called_once_with('bucket')
        assert parts[0]['obj'].backend == 'localhost'

    def test_object_storage_prefix_listing(self):
        internal = _storage()
        internal.storage.list_objects.return_value = [
            {'Key': 'dir/a', 'Size': 20}
        ]
        create_partitions(
            {},
            internal,
            [{'obj': 'localhost://bucket/dir/'}],
            None,
            None,
            None,
        )
        internal.storage.list_objects.assert_called_once()

    def test_object_storage_discard_prefix_folder(self):
        internal = _storage()
        internal.storage.list_objects.return_value = [
            {'Key': 'dir/', 'Size': 0}
        ]
        # A listing of nothing but folder markers holds no data at all
        with pytest.raises(Exception, match='No objects found'):
            create_partitions(
                {}, internal, [{'obj': 'localhost://bucket'}], None, None, None
            )

    def test_object_storage_folder_marker_does_not_hide_objects(self):
        internal = _storage()
        internal.storage.list_objects.return_value = [
            {'Key': 'dir/', 'Size': 0},
            {'Key': 'dir/data.csv', 'Size': 100},
        ]
        parts, ppo = create_partitions(
            {}, internal, [{'obj': 'localhost://bucket'}], None, None, None
        )
        assert len(parts) == 1
        assert ppo == [1]

    def test_object_storage_no_objects_raises(self):
        internal = _storage()
        internal.storage.list_objects.return_value = []
        with pytest.raises(Exception, match='No objects found'):
            create_partitions(
                {}, internal, [{'obj': 'localhost://bucket'}], None, None, None
            )

    def test_object_storage_multiple_backends_raises(self):
        internal = _storage()
        with pytest.raises(Exception, match='multiple storage backends'):
            create_partitions(
                {},
                internal,
                [
                    {'obj': 'localhost://b/k'},
                    {'obj': 'aws_s3://b/k'},
                ],
                None,
                None,
                None,
            )

    def test_object_storage_other_backend_uses_storage_class(self):
        internal = _storage()
        fake = MagicMock()
        fake.head_object.return_value = {'content-length': '20'}
        with patch('lithops.job.partitioner.Storage', return_value=fake) as st:
            parts, _ = create_partitions(
                {'lithops': {}},
                internal,
                [{'obj': 'aws_s3://b/k'}],
                None,
                None,
                None,
            )
        st.assert_called_once_with(config={'lithops': {}}, backend='aws_s3')
        assert parts[0]['obj'].backend == 'aws_s3'

    def test_object_storage_unset_log_has_no_trailing_space(self):
        internal = _storage()
        internal.storage.head_object.return_value = {'content-length': '20'}
        logger, handler, prev = _catch_partitioner_logs()
        try:
            create_partitions(
                {},
                internal,
                [{'obj': 'localhost://bucket/file'}],
                None,
                None,
                None,
            )
            assert 'Chunk size and chunk number not set' in handler.messages
            assert 'Chunk size and chunk number not set ' not in handler.messages
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prev)

    def test_object_storage_glob_in_obj_name(self):
        internal = _storage()
        fake = MagicMock()
        fake.list_objects.return_value = [{'Key': 'dir/foo1', 'Size': 20}]
        with patch('lithops.job.partitioner.Storage', return_value=fake):
            parts, _ = create_partitions(
                {},
                internal,
                [{'obj': 'aws_s3://bucket/dir/foo*'}],
                None,
                None,
                None,
            )
        args = fake.list_objects.call_args[0]
        assert args[0] == 'bucket'
        assert args[1] == 'dir/foo/'
        assert args[2] == 'dir/foo*'
        assert '\\' not in args[2]
        assert len(parts) == 1

    def test_object_storage_glob_in_prefix(self):
        internal = _storage()
        fake = MagicMock()
        fake.list_objects.return_value = [{'Key': 'pre/a', 'Size': 20}]
        with patch('lithops.job.partitioner.Storage', return_value=fake):
            create_partitions(
                {},
                internal,
                [{'obj': 'aws_s3://bucket/pre*/file'}],
                None,
                None,
                None,
            )
        args = fake.list_objects.call_args[0]
        assert args[0] == 'bucket'
        assert args[1] == 'pre/'
        assert args[2] == 'pre*/file'
        assert '\\' not in args[2]

    def test_object_storage_chunk_number_on_zero_size(self):
        internal = _storage()
        internal.storage.head_object.return_value = {'content-length': '0'}
        parts, ppo = create_partitions(
            {},
            internal,
            [{'obj': 'localhost://bucket/file'}],
            None,
            3,
            None,
        )
        assert parts == []
        assert ppo == [0]


class TestJobExports:

    def test_package_exports(self):
        import lithops.job as jobmod
        assert jobmod.create_map_job is create_map_job
        assert jobmod.create_reduce_job is create_reduce_job
        assert jobmod.__all__ == ['create_map_job', 'create_reduce_job']
