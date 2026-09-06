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
Unit tests for lithops.multiprocessing.

The package talks to Redis for every shared object and to a Lithops
FunctionExecutor for every process, so both are replaced here: Redis by the
in-memory server in mp_fakeredis, and the executor by a fake that records
what was submitted. Nothing in this file needs a Redis server or a backend.
"""

import ctypes
import pickle
import queue
import sys
import threading
import time
import types

import cloudpickle
import pytest
from unittest.mock import MagicMock, patch

from lithops.multiprocessing import config as mp_config
from lithops.multiprocessing import util as mp_util
from lithops.tests.mp_fakeredis import FakeRedis


@pytest.fixture(autouse=True)
def mp_globals():
    """
    Gives back the module-wide state of lithops.multiprocessing.

    Its configuration, its Redis client and its Lithops configuration are all
    process-wide singletons, so a test that touches one of them decides the
    outcome of every test that runs afterwards
    """
    saved_config = dict(mp_config._config)
    saved_client = mp_util.REDIS_CLIENT
    saved_lithops_config = mp_util.LITHOPS_CONFIG
    yield
    mp_config._config.clear()
    mp_config._config.update(saved_config)
    mp_util.REDIS_CLIENT = saved_client
    mp_util.LITHOPS_CONFIG = saved_lithops_config


@pytest.fixture
def redis():
    """Installs the in-memory server as the client the whole package shares"""
    server = FakeRedis()
    mp_util.REDIS_CLIENT = server
    mp_util.LITHOPS_CONFIG = {'redis': {'host': 'localhost'}}
    return server


class FakeFuture:
    def __init__(self, value=None, error=False):
        self.executor_id = 'sess-0'
        self.job_id = 'A000'
        self.call_id = '00000'
        self.done = True
        self.error = error
        self.success = not error
        self.ready = True
        self.stats = {'worker_exec_time': 0.5}
        self._value = value

    def result(self, throw_except=True, internal_storage=None):
        return self._value


class FakeExecutor:
    """Stand-in for lithops.FunctionExecutor, recording what it was given"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.executor_id = 'sess-0'
        self.invoker = type('I', (), {'max_workers': 7})()
        self.futures = []
        self.call_async_calls = []
        self.map_calls = []
        self.wait_calls = []
        self.get_result_calls = []
        self.exited = False
        self.results = None
        self._result_index = 0
        self.wait_error = None

    def call_async(self, func, data, **kwargs):
        self.call_async_calls.append((func, data, kwargs))
        return FakeFuture(self._next_value())

    def map(self, func, iterdata, **kwargs):
        self.map_calls.append((func, list(iterdata), kwargs))
        return [FakeFuture(self._next_value()) for _ in iterdata]

    def _next_value(self):
        """Hands out `results` one call at a time, in order"""
        if not self.results:
            return None
        value = self.results[self._result_index % len(self.results)]
        self._result_index += 1
        return value

    def wait(self, fs=None, **kwargs):
        self.wait_calls.append((fs, kwargs))
        if self.wait_error is not None:
            raise self.wait_error
        return list(fs or []), []

    def get_result(self, fs=None, **kwargs):
        self.get_result_calls.append((fs, kwargs))
        if self.results is not None:
            return self.results
        return [None] * len(fs or [])

    def __exit__(self, exc_type, exc_value, traceback):
        self.exited = True


@pytest.fixture
def executor(monkeypatch):
    """Every FunctionExecutor the package builds becomes the same fake"""
    built = []

    def factory(**kwargs):
        made = FakeExecutor(**kwargs)
        built.append(made)
        return made

    monkeypatch.setattr('lithops.multiprocessing.pool.FunctionExecutor', factory)
    monkeypatch.setattr('lithops.multiprocessing.process.FunctionExecutor', factory)
    return built


class TestConfig:

    def test_defaults_are_readable(self):
        assert mp_config.get_parameter(mp_config.STREAM_STDOUT) is False
        assert mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME) == 3600
        assert mp_config.get_parameter(mp_config.PIPE_CONNECTION_TYPE) == 'redislist'

    def test_set_parameter_rejects_unknown_keys(self):
        with pytest.raises(KeyError):
            mp_config.set_parameter('NOT_A_PARAMETER', 1)

    def test_update_accepts_a_dict_and_keywords(self):
        mp_config.update({mp_config.STREAM_STDOUT: True}, REDIS_EXPIRY_TIME=60)
        assert mp_config.get_parameter(mp_config.STREAM_STDOUT) is True
        assert mp_config.get_parameter(mp_config.REDIS_EXPIRY_TIME) == 60

    def test_setting_a_parameter_leaves_the_defaults_alone(self):
        """
        Otherwise there is no pristine default left to fall back to, and the
        table in the documentation stops describing what a fresh process sees
        """
        mp_config.set_parameter(mp_config.REDIS_EXPIRY_TIME, 11)
        assert mp_config._DEFAULT_CONFIG[mp_config.REDIS_EXPIRY_TIME] == 3600


class TestUtil:

    def test_uuid_length(self):
        assert len(mp_util.get_uuid()) == 12
        assert len(mp_util.get_uuid(6)) == 6

    def test_redis_client_requires_a_redis_section(self, monkeypatch):
        monkeypatch.setattr(mp_util, 'REDIS_CLIENT', None)
        monkeypatch.setattr(mp_util, 'LITHOPS_CONFIG', {'lithops': {}})
        with pytest.raises(Exception, match='Redis section'):
            mp_util.get_redis_client()

    def test_redis_client_is_reused(self, redis):
        assert mp_util.get_redis_client() is redis

    def test_picklable_redis_survives_a_round_trip(self):
        client = mp_util.PicklableRedis(host='h', port=6379)
        restored = pickle.loads(pickle.dumps(client))
        assert restored._kwargs == {'host': 'h', 'port': 6379}

    def test_make_stateless_script_detaches_the_client(self, redis):
        script = redis.register_script('return 1')
        script.registered_client = redis
        assert mp_util.make_stateless_script(script).registered_client is None

    def test_log_streaming_is_off_by_default(self):
        assert mp_util.setup_log_streaming(FakeExecutor()) == (None, None)

    def test_export_execution_details_is_off_by_default(self):
        # Would raise if it tried to plot the fake futures
        mp_util.export_execution_details([FakeFuture()], FakeExecutor())


class TestRemoteReference:

    def test_managed_reference_does_not_count(self, redis):
        ref = mp_util.RemoteReference('key-1', managed=True, client=redis)
        assert ref.managed is True
        assert ref.incref() is None
        assert ref.decref() is None

    def test_unmanaged_reference_counts_up_and_down(self, redis):
        ref = mp_util.RemoteReference('key-1', client=redis)
        assert ref.incref() == 1
        assert ref.incref() == 2
        assert ref.decref() == 1

    def test_the_counter_key_is_collected_with_the_referenced_ones(self, redis):
        ref = mp_util.RemoteReference(['key-1', 'key-2'], client=redis)
        redis.set('key-1', 'a')
        redis.set('key-2', 'b')
        ref.collect()
        assert redis.keys('key-*') == []

    def test_a_string_reference_is_taken_as_one_key(self, redis):
        ref = mp_util.RemoteReference('key-1', client=redis)
        assert ref._referenced == ['key-1', 'ref-key-1']

    def test_a_reference_must_be_a_key_or_a_list_of_keys(self, redis):
        with pytest.raises(TypeError, match='referenced must be'):
            mp_util.RemoteReference(42, client=redis)


class TestContext:

    def test_the_default_context_exposes_the_process_and_pool(self):
        from lithops.multiprocessing import process, pool
        from lithops.multiprocessing.context import _default_context
        assert _default_context.Process is process.CloudProcess
        assert _default_context.Pool is pool.Pool

    def test_get_context_accepts_the_standard_methods(self):
        from lithops.multiprocessing.context import get_context, _default_context
        for method in ('spawn', 'fork', 'forkserver', 'cloud'):
            assert get_context(method) is _default_context

    def test_get_context_rejects_an_unknown_method(self):
        from lithops.multiprocessing.context import get_context
        with pytest.raises(ValueError, match='cannot find context'):
            get_context('threads')

    def test_start_method_is_always_cloud(self):
        from lithops.multiprocessing.context import (
            get_start_method, get_all_start_methods
        )
        assert get_start_method() == 'cloud'
        assert 'cloud' in get_all_start_methods()

    def test_cpu_count_multiplies_workers_by_processes(self, monkeypatch):
        from lithops.multiprocessing.context import cpu_count
        monkeypatch.setattr(
            'lithops.config.default_config',
            lambda *a, **kw: {
                'lithops': {'backend': 'aws_lambda'},
                'aws_lambda': {'max_workers': 100, 'worker_processes': 2},
            },
        )
        assert cpu_count() == 200

    def test_cpu_count_uses_the_configured_lithops_parameters(self, monkeypatch):
        """
        Otherwise a Pool sized from cpu_count() is sized against whatever the
        machine happens to have configured, not against what the caller set
        """
        from lithops.multiprocessing.context import cpu_count
        seen = {}

        def fake_default_config(config_data=None, **kwargs):
            seen['config_data'] = config_data
            return {
                'lithops': {'backend': 'localhost'},
                'localhost': {'max_workers': 4, 'worker_processes': 1},
            }

        monkeypatch.setattr('lithops.config.default_config', fake_default_config)
        mp_config.set_parameter(
            mp_config.LITHOPS_CONFIG, {'lithops': {'backend': 'localhost'}}
        )
        cpu_count()
        assert seen['config_data'] == {'lithops': {'backend': 'localhost'}}


class TestPool:

    def test_processes_becomes_max_workers(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=3)
        assert pool._processes == 3
        assert executor[0].kwargs['max_workers'] == 3

    def test_without_processes_the_backend_decides(self, executor):
        from lithops.multiprocessing import Pool
        assert Pool()._processes == 7
        assert 'max_workers' not in executor[0].kwargs

    def test_the_lithops_config_reaches_the_executor(self, executor):
        from lithops.multiprocessing import Pool
        mp_config.set_parameter(
            mp_config.LITHOPS_CONFIG, {'backend': 'localhost'}
        )
        Pool()
        assert executor[0].kwargs['backend'] == 'localhost'

    def test_zero_processes_is_rejected(self, executor):
        from lithops.multiprocessing import Pool
        with pytest.raises(ValueError, match='at least 1'):
            Pool(processes=0)

    def test_a_non_callable_initializer_is_rejected(self, executor):
        from lithops.multiprocessing import Pool
        with pytest.raises(TypeError, match='must be a callable'):
            Pool(initializer='nope')

    def test_apply_async_submits_one_call(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        pool.apply_async(pow, (2, 8))
        _, data, _ = executor[0].call_async_calls[0]
        assert data['op'] == 'apply'
        assert data['data'] == {'args': (2, 8), 'kwargs': {}}
        assert data['func'] is pow

    def test_apply_returns_the_value_not_a_list(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        executor[0].results = [256]
        assert pool.apply(pow, (2, 8)) == 256

    def test_map_submits_one_lithops_map(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        executor[0].results = [1, 4, 9]
        assert pool.map(abs, [1, 2, 3]) == [1, 4, 9]
        func, iterdata, kwargs = executor[0].map_calls[0]
        assert iterdata == [(1,), (2,), (3,)]
        assert kwargs['extra_args'][0] is abs
        assert kwargs['extra_args'][-1] == 'map'

    def test_starmap_marks_the_operation(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        executor[0].results = [3]
        assert pool.starmap(pow, [(1, 2)]) == [3]
        assert executor[0].map_calls[0][2]['extra_args'][-1] == 'starmap'

    def test_map_accepts_a_generator(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        executor[0].results = [1, 2]
        pool.map(abs, (x for x in (1, 2)))
        assert executor[0].map_calls[0][1] == [(1,), (2,)]

    def test_map_chunksize_reaches_lithops(self, executor):
        """
        Lithops takes a chunksize of its own, meaning the same thing: how
        many items one worker takes. Accepting it and dropping it leaves the
        caller thinking they tuned something
        """
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        executor[0].results = [1, 2, 3, 4]
        pool.map(abs, [1, 2, 3, 4], chunksize=2)
        assert executor[0].map_calls[0][2].get('chunksize') == 2

    def test_map_without_chunksize_leaves_it_to_the_lithops_config(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        executor[0].results = [1]
        pool.map(abs, [1])
        assert executor[0].map_calls[0][2].get('chunksize') is None

    def test_env_vars_are_forwarded(self, executor):
        from lithops.multiprocessing import Pool
        mp_config.set_parameter(mp_config.ENV_VARS, {'A': '1'})
        pool = Pool(processes=1)
        pool.apply_async(abs, (1,))
        assert executor[0].call_async_calls[0][2]['extra_env'] == {'A': '1'}

    def test_a_closed_pool_takes_no_more_work(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        pool.close()
        with pytest.raises(ValueError, match='not running'):
            pool.apply_async(abs, (1,))
        with pytest.raises(ValueError, match='not running'):
            pool.map_async(abs, [1])

    def test_a_pool_cannot_be_pickled(self, executor):
        from lithops.multiprocessing import Pool
        with pytest.raises(NotImplementedError, match='cannot be passed'):
            pickle.dumps(Pool(processes=1))

    def test_join_requires_close_or_terminate(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        with pytest.raises(ValueError, match='still running'):
            pool.join()
        pool.close()
        pool.join()

    def test_the_context_manager_terminates(self, executor):
        from lithops.multiprocessing import Pool, pool as pool_module
        with Pool(processes=1) as pool:
            pass
        assert pool._state == pool_module.TERMINATE

    def test_a_pool_gives_its_executor_back(self, executor):
        """Otherwise its job monitor and invoker threads outlive the pool"""
        from lithops.multiprocessing import Pool
        with Pool(processes=1):
            pass
        assert executor[0].exited


class TestApplyResult:

    def _result(self, executor_fake, futures=None):
        from lithops.multiprocessing.pool import ApplyResult
        return ApplyResult(executor_fake, futures or [FakeFuture()], None, None)

    def _map_result(self, executor_fake, futures):
        from lithops.multiprocessing.pool import MapResult
        return MapResult(executor_fake, futures, None, None)

    def test_ready_and_successful(self, executor):
        result = self._result(FakeExecutor())
        assert result.ready() is True
        assert result.successful() is True

    def test_successful_before_ready_raises(self, executor):
        pending = FakeFuture()
        pending.done = pending.ready = pending.success = False
        result = self._result(FakeExecutor(), [pending])
        with pytest.raises(ValueError, match='not ready'):
            result.successful()

    def test_ready_once_the_call_reported_back(self, executor):
        """
        A future whose status has arrived but whose result nobody downloaded
        yet is finished as far as the caller is concerned
        """
        fake = FakeExecutor()
        finished = FakeFuture()
        finished.done = False
        finished.success = True
        result = self._result(fake, [finished])
        assert result.ready() is True

    def test_successful_is_false_when_a_call_failed(self, executor):
        result = self._result(FakeExecutor(), [FakeFuture(error=True)])
        assert result.successful() is False

    def test_get_calls_back_with_the_value(self, executor):
        from lithops.multiprocessing.pool import ApplyResult
        seen = []
        result = ApplyResult(FakeExecutor(), [FakeFuture(5)], seen.append, None)
        assert result.get() == 5
        assert seen == [5]

    def test_map_result_keeps_the_whole_list(self, executor):
        result = self._map_result(
            FakeExecutor(), [FakeFuture(n) for n in (1, 2, 3)]
        )
        assert result.get() == [1, 2, 3]

    def test_a_single_call_returning_a_list_is_not_unwrapped(self, executor):
        """
        What the executor's get_result() cannot tell apart: one result that
        happens to be a list, and a list of results
        """
        result = self._result(FakeExecutor(), [FakeFuture([1, 2, 3])])
        assert result.get() == [1, 2, 3]

    def test_the_shape_of_a_result_does_not_depend_on_later_calls(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        executor[0].results = [42]
        applied = pool.apply_async(abs, (-42,))
        pool.map_async(abs, [1, 2])
        assert applied.get() == 42

    def test_wait_forwards_the_timeout(self, executor):
        result = self._result(FakeExecutor())
        result.wait(timeout=5)
        assert result._executor.wait_calls[0][1]['timeout'] == 5

    def test_a_timeout_raises_the_multiprocessing_error(self, executor):
        """
        Lithops reports a timeout as the builtin, which is an OSError and so
        not what `except multiprocessing.TimeoutError` catches
        """
        from lithops.multiprocessing import TimeoutError as MpTimeoutError
        fake = FakeExecutor()
        fake.wait_error = TimeoutError('too slow')
        result = self._result(fake, [FakeFuture(1)])
        with pytest.raises(MpTimeoutError):
            result.get(timeout=0.01)

    def test_a_wait_that_timed_out_does_not_poison_get(self, executor):
        """
        wait() reports nothing in the standard library; the result is still
        there to be fetched once it arrives
        """
        fake = FakeExecutor()
        fake.wait_error = TimeoutError('too slow')
        result = self._result(fake, [FakeFuture(7)])
        result.wait(timeout=0.01)
        fake.wait_error = None
        assert result.get() == 7


class TestIMapIterator:

    def test_iterates_over_the_results(self):
        from lithops.multiprocessing.pool import IMapIterator
        it = IMapIterator([1, 2])
        assert [next(it), it.next()] == [1, 2]
        with pytest.raises(StopIteration):
            next(it)

    def test_imap_yields_the_same_results_as_map(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        executor[0].results = [1, 2, 3]
        assert list(pool.imap(abs, [1, 2, 3])) == [1, 2, 3]

    def test_imap_unordered_yields_every_result(self, executor):
        from lithops.multiprocessing import Pool
        pool = Pool(processes=1)
        executor[0].results = [1, 2, 3]
        assert sorted(pool.imap_unordered(abs, [1, 2, 3])) == [1, 2, 3]


def _double(x):
    return x * 2


def _boom(x):
    raise ValueError('boom')


class TestCloudProcessWrapper:

    def test_apply_calls_with_args_and_kwargs(self):
        from lithops.multiprocessing.process import cloud_process_wrapper
        assert cloud_process_wrapper(
            {'args': (2,), 'kwargs': {}}, _double, op='apply'
        ) == 4

    def test_map_passes_the_single_item(self):
        from lithops.multiprocessing.process import cloud_process_wrapper
        assert cloud_process_wrapper(3, _double, op='map') == 6

    def test_starmap_unpacks_the_item(self):
        from lithops.multiprocessing.process import cloud_process_wrapper
        assert cloud_process_wrapper((2, 8), pow, op='starmap') == 256

    def test_an_unknown_operation_raises(self):
        from lithops.multiprocessing.process import cloud_process_wrapper
        with pytest.raises(Exception, match='nonsense'):
            cloud_process_wrapper(1, _double, op='nonsense')

    def test_the_function_exception_reaches_the_caller(self):
        from lithops.multiprocessing.process import cloud_process_wrapper
        with pytest.raises(ValueError, match='boom'):
            cloud_process_wrapper(1, _boom, op='map')

    def test_the_initializer_runs_before_the_function(self):
        from lithops.multiprocessing.process import cloud_process_wrapper
        calls = []
        cloud_process_wrapper(
            1, _double, initializer=calls.append, initargs=('init',), op='map'
        )
        assert calls == ['init']

    def test_the_worker_name_is_the_one_that_was_given(self):
        """
        current_process().name reads it back out of the environment, so a
        hardcoded one makes every process report the same name
        """
        import os
        from lithops.multiprocessing.process import cloud_process_wrapper
        cloud_process_wrapper(1, _double, name='CloudProcess-7', op='map')
        assert os.environ['LITHOPS_MP_WORKER_NAME'] == 'CloudProcess-7'


class TestCloudProcess:

    def test_start_submits_the_target(self, executor, redis):
        from lithops.multiprocessing import Process
        proc = Process(target=_double, args=(4,))
        proc.start()
        _, data, _ = executor[0].call_async_calls[0]
        assert data['func'] is _double
        assert data['data'] == {'args': (4,), 'kwargs': {}}
        assert proc.pid == 'sess-0/A000/00000'

    def test_a_process_cannot_be_started_twice(self, executor, redis):
        from lithops.multiprocessing import Process
        proc = Process(target=_double, args=(1,))
        proc.start()
        with pytest.raises(AssertionError, match='twice'):
            proc.start()

    def test_run_calls_the_target_in_process(self, executor, redis):
        from lithops.multiprocessing import Process
        seen = []
        Process(target=seen.append, args=('x',)).run()
        assert seen == ['x']

    def test_the_name_defaults_and_can_be_set(self, executor, redis):
        from lithops.multiprocessing import Process
        proc = Process(target=_double, name='worker-1')
        assert proc.name == 'worker-1'
        proc.name = 'worker-2'
        assert proc.name == 'worker-2'
        with pytest.raises(AssertionError, match='must be a string'):
            proc.name = 7

    def test_an_unnamed_process_gets_a_generated_name(self, executor, redis):
        from lithops.multiprocessing import Process
        assert Process(target=_double).name.startswith('CloudProcess-')

    def test_the_daemon_flag_round_trips(self, executor, redis):
        from lithops.multiprocessing import Process
        proc = Process(target=_double, daemon=True)
        assert proc.daemon is True
        assert Process(target=_double).daemon is False

    def test_grouping_is_rejected(self, executor, redis):
        from lithops.multiprocessing import Process
        with pytest.raises(AssertionError, match='grouping'):
            Process(group='g', target=_double)

    def test_join_before_start_is_rejected(self, executor, redis):
        from lithops.multiprocessing import Process
        with pytest.raises(AssertionError, match='started process'):
            Process(target=_double).join()

    def test_join_waits_for_the_call(self, executor, redis):
        from lithops.multiprocessing import Process
        proc = Process(target=_double, args=(1,))
        proc.start()
        proc.join()
        assert executor[0].wait_calls

    def test_join_forwards_the_timeout(self, executor, redis):
        from lithops.multiprocessing import Process
        proc = Process(target=_double, args=(1,))
        proc.start()
        proc.join(timeout=5)
        assert executor[0].wait_calls[0][1].get('timeout') == 5

    def test_the_unsupported_api_says_so(self, executor, redis):
        from lithops.multiprocessing import Process
        proc = Process(target=_double)
        for call in (proc.terminate, proc.kill, proc.is_alive):
            with pytest.raises(NotImplementedError):
                call()
        with pytest.raises(NotImplementedError):
            proc.exitcode

    def test_close_gives_the_executor_back(self, executor, redis):
        from lithops.multiprocessing import Process
        proc = Process(target=_double, args=(1,))
        proc.start()
        proc.close()
        assert executor[0].exited

    def test_creating_a_process_does_not_need_redis(self, executor, monkeypatch):
        """
        A process talks to Lithops, not to Redis. Reaching for a client at
        construction makes Redis a requirement of the plain Process API
        """
        def no_redis(*args, **kwargs):
            raise AssertionError('should not build a Redis client')

        monkeypatch.setattr(mp_util, 'get_redis_client', no_redis)
        from lithops.multiprocessing import Process
        Process(target=_double, args=(1,))


class TestQueue:

    def _queue(self, maxsize=0):
        from lithops.multiprocessing import Queue
        return Queue(maxsize)

    def test_put_and_get_round_trip(self, redis):
        queue = self._queue()
        queue.put({'a': 1})
        assert queue.get() == {'a': 1}

    def test_qsize_and_empty(self, redis):
        queue = self._queue()
        assert queue.empty() is True
        queue.put(1)
        assert queue.qsize() == 1
        assert queue.empty() is False

    def test_full_reports_whether_the_queue_is_full(self, redis):
        queue = self._queue(maxsize=1)
        assert queue.full() is False
        queue.put(1)
        assert queue.full() is True

    def test_an_unbounded_queue_is_never_full(self, redis):
        queue = self._queue()
        queue.put(1)
        assert queue.full() is False

    def test_put_nowait_on_a_full_queue_raises(self, redis):
        """Dropping the item on the floor loses data with no way to tell"""
        from queue import Full
        queue = self._queue(maxsize=1)
        queue.put(1)
        with pytest.raises(Full):
            queue.put_nowait(2)
        assert queue.qsize() == 1

    def test_get_nowait_on_an_empty_queue_raises(self, redis):
        from queue import Empty
        with pytest.raises(Empty):
            self._queue().get_nowait()

    def test_get_with_a_timeout_raises_when_nothing_arrives(self, redis):
        from queue import Empty
        queue = self._queue()
        started = time.monotonic()
        with pytest.raises(Empty):
            queue.get(timeout=0.2)
        assert time.monotonic() - started < 2

    def test_put_on_a_closed_queue_raises(self, redis):
        queue = self._queue()
        queue.close()
        with pytest.raises(ValueError, match='closed'):
            queue.put(1)

    def test_a_queue_survives_being_pickled(self, redis):
        """It travels to the worker inside the job payload"""
        queue = self._queue(maxsize=3)
        restored = pickle.loads(pickle.dumps(queue))
        restored.put('from the worker')
        assert queue.get() == 'from the worker'
        assert restored._maxsize == 3


class TestSimpleQueue:

    def test_put_and_get_round_trip(self, redis):
        from lithops.multiprocessing import SimpleQueue
        queue = SimpleQueue()
        queue.put('x')
        assert queue.get() == 'x'
        assert queue.full() is False

    def test_get_nowait_does_not_block_on_an_empty_queue(self, redis):
        from queue import Empty
        from lithops.multiprocessing import SimpleQueue
        with pytest.raises(Empty):
            SimpleQueue().get_nowait()

    def test_put_on_a_closed_queue_raises(self, redis):
        from lithops.multiprocessing import SimpleQueue
        queue = SimpleQueue()
        queue.close()
        with pytest.raises(AssertionError):
            queue.put('x')


class TestJoinableQueue:

    def test_task_done_counts_down(self, redis):
        from lithops.multiprocessing import JoinableQueue
        queue = JoinableQueue()
        queue.put(1)
        assert queue._unfinished_tasks.get_value() == 1
        queue.task_done()
        assert queue._unfinished_tasks.get_value() == 0

    def test_too_many_task_done_raises(self, redis):
        from lithops.multiprocessing import JoinableQueue
        queue = JoinableQueue()
        with pytest.raises(ValueError, match='too many times'):
            queue.task_done()

    def test_join_returns_when_nothing_is_outstanding(self, redis):
        from lithops.multiprocessing import JoinableQueue
        queue = JoinableQueue()
        queue.put(1)
        queue.get()
        queue.task_done()
        queue.join()

    def test_maxsize_is_honoured(self, redis):
        from lithops.multiprocessing.context import _default_context
        queue = _default_context.JoinableQueue(2)
        assert queue._maxsize == 2


class TestConnection:

    def test_handle_pairs_are_two_ends_of_one_id(self):
        from lithops.multiprocessing import connection
        a, b = connection.get_handle_pair(connection.REDIS_LIST_CONN)
        assert connection.get_subhandle(a) == b
        assert connection.get_subhandle(b) == a

    def test_an_unknown_connection_type_is_rejected(self):
        from lithops.multiprocessing import connection
        with pytest.raises(Exception, match='Unknown connection type'):
            connection.get_handle_pair('carrier-pigeon')

    def test_a_bad_handle_prefix_is_rejected(self):
        from lithops.multiprocessing import connection
        with pytest.raises(ValueError, match='bad handle prefix'):
            connection.get_subhandle('nonsense-1234')

    def test_a_pipe_carries_objects_both_ways(self, redis):
        from lithops.multiprocessing import Pipe
        left, right = Pipe()
        left.send({'a': 1})
        assert right.recv() == {'a': 1}
        right.send('back')
        assert left.recv() == 'back'

    def test_a_simplex_pipe_is_one_way(self, redis):
        from lithops.multiprocessing import Pipe
        reader, writer = Pipe(duplex=False)
        assert reader.readable and not reader.writable
        assert writer.writable and not writer.readable
        with pytest.raises(OSError, match='read-only'):
            reader.send('x')
        with pytest.raises(OSError, match='write-only'):
            writer.recv()

    def test_send_bytes_honours_offset_and_size(self, redis):
        from lithops.multiprocessing import Pipe
        left, right = Pipe()
        left.send_bytes(b'0123456789', offset=2, size=3)
        assert right.recv_bytes() == b'234'

    def test_send_bytes_validates_its_range(self, redis):
        from lithops.multiprocessing import Pipe
        left, _ = Pipe()
        with pytest.raises(ValueError, match='offset is negative'):
            left.send_bytes(b'abc', offset=-1)
        with pytest.raises(ValueError, match='buffer length < offset'):
            left.send_bytes(b'abc', offset=9)
        with pytest.raises(ValueError, match='size is negative'):
            left.send_bytes(b'abc', size=-1)

    def test_poll_reports_whether_anything_is_waiting(self, redis):
        from lithops.multiprocessing import Pipe
        left, right = Pipe()
        assert right.poll() is False
        left.send('x')
        assert right.poll() is True

    def test_a_closed_connection_refuses_to_work(self, redis):
        from lithops.multiprocessing import Pipe
        left, _ = Pipe()
        left.close()
        assert left.closed is True
        with pytest.raises(OSError, match='handle is closed'):
            left.send('x')

    def test_a_connection_survives_being_pickled(self, redis):
        from lithops.multiprocessing import Pipe
        left, right = Pipe()
        restored = pickle.loads(pickle.dumps(right))
        left.send('through the pipe')
        assert restored.recv() == 'through the pipe'

    def test_closing_one_end_leaves_the_shared_client_usable(self, redis):
        """
        The Redis client is a process-wide singleton, so closing it with one
        connection takes every other shared object down with it
        """
        from lithops.multiprocessing import Pipe
        left, right = Pipe()
        left.close()
        assert redis.closed is False
        other_left, other_right = Pipe()
        other_left.send('still working')
        assert other_right.recv() == 'still working'


class TestSemLock:

    def test_acquire_and_release(self, redis):
        from lithops.multiprocessing import Lock
        lock = Lock()
        assert lock.get_value() == 1
        assert lock.acquire() is True
        assert lock.get_value() == 0
        lock.release()
        assert lock.get_value() == 1

    def test_a_non_blocking_acquire_fails_when_taken(self, redis):
        from lithops.multiprocessing import Lock
        lock = Lock()
        lock.acquire()
        assert lock.acquire(block=False) is False

    def test_the_context_manager_acquires_and_releases(self, redis):
        from lithops.multiprocessing import Lock
        lock = Lock()
        with lock:
            assert lock.get_value() == 0
        assert lock.get_value() == 1

    def test_a_bounded_semaphore_rejects_a_release_it_cannot_hold(self, redis):
        """
        A release that would take it past its bound raises, as the standard
        library documents, instead of being swallowed. Not compared against
        multiprocessing here: its check reads the semaphore value through
        sem_getvalue(), which macOS does not implement, so a BoundedSemaphore
        larger than 1 never raises there
        """
        from lithops.multiprocessing import BoundedSemaphore
        sem = BoundedSemaphore(2)
        with pytest.raises(ValueError, match='released too many times'):
            sem.release()
        assert sem.get_value() == 2

    def test_a_bounded_semaphore_allows_a_release_it_acquired(self, redis):
        from lithops.multiprocessing import BoundedSemaphore
        sem = BoundedSemaphore(2)
        sem.acquire()
        assert sem.get_value() == 1
        sem.release()
        assert sem.get_value() == 2

    def test_a_semaphore_counts_up_past_its_initial_value(self, redis):
        from lithops.multiprocessing import Semaphore
        sem = Semaphore(1)
        sem.release()
        assert sem.get_value() == 2

    def test_a_semaphore_can_start_empty(self, redis):
        from lithops.multiprocessing import Semaphore
        assert Semaphore(0).get_value() == 0

    def test_an_rlock_can_be_taken_again_by_its_owner(self, redis):
        from lithops.multiprocessing import RLock
        lock = RLock()
        assert lock.acquire() is True
        assert lock.acquire() is True

    def test_a_lock_survives_being_pickled(self, redis):
        from lithops.multiprocessing import Lock
        lock = Lock()
        restored = pickle.loads(pickle.dumps(lock))
        assert restored.acquire(block=False) is True
        assert lock.get_value() == 0
        restored.release()
        assert lock.get_value() == 1

    def test_the_repr_shows_the_value(self, redis):
        from lithops.multiprocessing import Lock
        assert 'value=1' in repr(Lock())


class TestCondition:

    def test_wait_returns_once_notified(self, redis):
        from lithops.multiprocessing import Condition
        cond = Condition()
        with cond:
            threading.Timer(0.1, lambda: _notify(cond)).start()
            cond.wait(timeout=5)

    def test_notify_all_wakes_every_waiter(self, redis):
        from lithops.multiprocessing import Condition
        cond = Condition()
        cond.acquire()
        handles = [
            redis.rpush(cond._notify_handle, 'w-1'),
            redis.rpush(cond._notify_handle, 'w-2'),
        ]
        assert handles[-1] == 2
        cond.notify_all()
        assert redis.llen(cond._notify_handle) == 0
        assert redis.llen('w-1') == 1
        assert redis.llen('w-2') == 1

    def test_wait_for_returns_at_once_when_already_true(self, redis):
        from lithops.multiprocessing import Condition
        cond = Condition()
        with cond:
            assert cond.wait_for(lambda: 'ready') == 'ready'

    def test_a_condition_can_wrap_a_given_lock(self, redis):
        from lithops.multiprocessing import Condition, Lock
        lock = Lock()
        cond = Condition(lock)
        with cond:
            assert lock.get_value() == 0

    def test_a_condition_survives_being_pickled(self, redis):
        from lithops.multiprocessing import Condition
        cond = Condition()
        restored = pickle.loads(pickle.dumps(cond))
        assert restored._notify_handle == cond._notify_handle


def _notify(cond):
    with cond:
        cond.notify()


class TestEvent:

    def test_an_event_starts_clear(self, redis):
        from lithops.multiprocessing import Event
        assert Event().is_set() is False

    def test_set_and_clear(self, redis):
        from lithops.multiprocessing import Event
        event = Event()
        event.set()
        assert event.is_set() is True
        event.clear()
        assert event.is_set() is False

    def test_wait_reports_the_flag(self, redis):
        """`if event.wait(timeout)` is how the standard library is used"""
        from lithops.multiprocessing import Event
        event = Event()
        event.set()
        assert event.wait(timeout=1) is True

    def test_wait_reports_a_timeout(self, redis):
        from lithops.multiprocessing import Event
        assert Event().wait(timeout=0.2) is False


class TestSharedCTypes:

    def test_raw_value_round_trips(self, redis):
        from lithops.multiprocessing import RawValue
        value = RawValue('i', 7)
        assert value.value == 7
        value.value = 9
        assert value.value == 9

    def test_raw_value_keeps_a_falsy_initial_value(self, redis):
        from lithops.multiprocessing import RawValue
        value = RawValue('d', 0.0).value
        assert value == 0.0 and isinstance(value, float)

    def test_a_missing_attribute_still_raises(self, redis):
        from lithops.multiprocessing import RawValue
        with pytest.raises(AttributeError):
            RawValue('i', 1).nonexistent

    def test_value_round_trips_and_locks(self, redis):
        from lithops.multiprocessing import Value
        value = Value('i', 3)
        assert value.value == 3
        with value:
            assert value.get_lock().get_value() == 0
        assert value.get_obj() == 3

    def test_value_uses_the_lock_it_was_given(self, redis):
        from lithops.multiprocessing import Value, Lock
        lock = Lock()
        value = Value('i', 1, lock=lock)
        assert value.get_lock() is lock

    def test_raw_array_from_a_list(self, redis):
        from lithops.multiprocessing import RawArray
        array = RawArray('i', [1, 2, 3])
        assert len(array) == 3
        assert array[1] == 2
        assert array[:] == [1, 2, 3]
        assert list(array) == [1, 2, 3]

    def test_raw_array_from_a_size(self, redis):
        from lithops.multiprocessing import RawArray
        assert RawArray('i', 3)[:] == [0, 0, 0]

    def test_raw_array_assignment(self, redis):
        from lithops.multiprocessing import RawArray
        array = RawArray('i', [1, 2, 3])
        array[0] = 9
        assert array[0] == 9
        array[1:3] = [7, 8]
        assert array[:] == [9, 7, 8]

    def test_raw_array_rejects_a_bad_initializer(self, redis):
        from lithops.multiprocessing import RawArray
        with pytest.raises(ValueError, match='Invalid size or initializer'):
            RawArray('i', 'nope')

    def test_a_char_raw_array_is_not_supported(self, redis):
        from lithops.multiprocessing import RawArray
        with pytest.raises(NotImplementedError):
            RawArray('c', 3)

    def test_array_round_trips(self, redis):
        from lithops.multiprocessing import Array
        array = Array('i', [1, 2, 3])
        assert array.get_obj() == [1, 2, 3]

    def test_a_char_array_reads_back_as_bytes(self, redis):
        from lithops.multiprocessing import Array
        array = Array('c', b'abc')
        assert array.value == b'abc'
        assert array[0:2] == b'ab'

    def test_the_typecode_table_covers_the_standard_codes(self):
        from lithops.multiprocessing import sharedctypes
        assert sharedctypes.typecode_to_type['i'] is ctypes.c_int
        assert sharedctypes.typecode_to_type['d'] is ctypes.c_double


class TestPackageSurface:

    def test_every_exported_name_exists(self):
        import lithops.multiprocessing as mp
        missing = [name for name in mp.__all__ if not hasattr(mp, name)]
        assert missing == []

    def test_the_whole_standard_library_surface_is_covered(self):
        """
        A drop-in has to answer every name multiprocessing exports, or an
        import of a ported module fails before any of it runs
        """
        import multiprocessing as std
        import lithops.multiprocessing as mp
        assert [name for name in std.__all__ if not hasattr(mp, name)] == []
        assert set(std.__all__) <= set(mp.__all__)

    def test_the_exception_types_are_the_standard_hierarchy(self):
        import lithops.multiprocessing as mp
        assert issubclass(mp.ProcessError, Exception)
        for error in (mp.BufferTooShort, mp.TimeoutError, mp.AuthenticationError):
            assert issubclass(error, mp.ProcessError)
        # Not the builtin, which is an OSError, as in the standard library
        assert not issubclass(mp.TimeoutError, OSError)

    def test_the_helpers_a_ported_script_calls_are_no_ops(self):
        import lithops.multiprocessing as mp
        assert mp.freeze_support() is None
        assert mp.allow_connection_pickling() is None
        assert mp.set_executable('/usr/bin/python3') is None
        assert mp.set_forkserver_preload(['os']) is None

    def test_get_logger_returns_the_package_logger(self):
        import logging
        import lithops.multiprocessing as mp
        from lithops.multiprocessing import context

        assert mp.get_logger() is logging.getLogger('lithops.multiprocessing')
        assert isinstance(context, types.ModuleType)
        saved_flag = context._log_to_stderr
        streamed = mp.get_logger()
        saved_handlers = list(streamed.handlers)
        try:
            context._log_to_stderr = False
            streamed.handlers.clear()
            assert mp.log_to_stderr(logging.WARNING) is streamed
            assert streamed.level == logging.WARNING
            # Twice must not print every line twice
            mp.log_to_stderr()
            assert len(streamed.handlers) == 1
        finally:
            context._log_to_stderr = saved_flag
            streamed.handlers[:] = saved_handlers
            streamed.setLevel(logging.NOTSET)

    def test_the_context_submodule_is_not_shadowed(self):
        """
        `multiprocessing.context` is the module, so ported code reaching for
        `mp.context.<name>` has to find one here too
        """
        import lithops.multiprocessing as mp
        assert isinstance(mp.context, types.ModuleType)
        assert mp.context.CloudContext is mp.DefaultContext

    def test_buffer_too_short_is_the_one_this_package_exports(self):
        """
        Raising the standard library's would slip past
        `except lithops.multiprocessing.BufferTooShort`
        """
        from lithops.multiprocessing import connection
        import lithops.multiprocessing as mp
        assert connection.BufferTooShort is mp.BufferTooShort

    def test_thread_pool_is_available_under_its_standard_name(self):
        from lithops.multiprocessing.pool import Pool, ThreadPool
        assert issubclass(ThreadPool, Pool)

    def test_the_unimplemented_process_helpers_say_so(self):
        import lithops.multiprocessing as mp
        for call in (mp.active_children, mp.parent_process):
            with pytest.raises(NotImplementedError):
                call()

    def test_the_cloudpickle_round_trip_of_a_shared_object(self, redis):
        """cloudpickle is what carries these into the job payload"""
        from lithops.multiprocessing import Lock
        lock = Lock()
        assert cloudpickle.loads(cloudpickle.dumps(lock))._name == lock._name


class TestConnectionPolling:
    """
    Nothing in a Redis handle or a local buffer can be blocked on, so these
    polls are timed waits. They used to step in a flat 0.1s, which made a
    message that was already there cost a tenth of a second
    """

    def _connection(self, buff):
        from lithops.multiprocessing.connection import _NanomsgConnection

        conn = _NanomsgConnection.__new__(_NanomsgConnection)
        conn._buff = buff
        return conn

    def test_poll_zero_looks_at_the_buffer(self):
        """
        poll(0) is what Queue.empty() and get(block=False) call. It used to
        compare the clock against a deadline it had just set and fall
        straight through without ever looking, so empty() said True whatever
        the queue held and get(block=False) raised Empty on a queue with
        data in it
        """
        buff = queue.Queue()
        buff.put(b'a message that is definitely there')
        assert self._connection(buff)._poll(0.0) is True
        assert self._connection(queue.Queue())._poll(0.0) is False

    def test_poll_returns_as_soon_as_a_message_lands(self):
        buff = queue.Queue()
        timer = threading.Timer(0.01, lambda: buff.put(b'x'))
        timer.start()
        try:
            started = time.monotonic()
            assert self._connection(buff)._poll(5.0) is True
            assert time.monotonic() - started < 0.09
        finally:
            timer.cancel()

    def test_poll_does_not_overshoot_its_timeout(self):
        started = time.monotonic()
        assert self._connection(queue.Queue())._poll(0.05) is False
        # The flat 0.1s step used to sleep past the deadline it was given
        assert 0.05 <= time.monotonic() - started < 0.12

    def test_poll_until_always_checks_once(self):
        from lithops.multiprocessing.connection import _poll_until

        checks = []
        assert _poll_until(lambda: checks.append(1) or False, 0.0) is False
        assert len(checks) == 1
        assert _poll_until(lambda: 'ready', 0.0) == 'ready'

    def test_poll_until_backs_off_to_the_cap(self):
        from lithops.multiprocessing import connection as conn_mod

        waits = []
        with patch.object(conn_mod.time, 'sleep', side_effect=waits.append):
            conn_mod._poll_until(lambda: False if len(waits) < 12 else True, None)
        assert waits[0] == conn_mod.POLL_MIN_SLEEP
        assert waits == sorted(waits)
        assert max(waits) == conn_mod.POLL_MAX_SLEEP

    def test_wait_returns_the_ready_handles(self):
        from lithops.multiprocessing import connection as conn_mod

        client = MagicMock()
        client.llen.side_effect = lambda h: 1 if h.endswith('b') else 0
        handles = [
            (client, conn_mod.REDIS_LIST_CONN + '-a'),
            (client, conn_mod.REDIS_LIST_CONN + '-b'),
        ]
        assert conn_mod.wait(handles, timeout=0.0) == [handles[1]]

    def test_wait_returns_an_empty_list_when_nothing_is_ready(self):
        from lithops.multiprocessing import connection as conn_mod

        client = MagicMock()
        client.llen.return_value = 0
        handles = [(client, conn_mod.REDIS_LIST_CONN + '-a')]
        assert conn_mod.wait(handles, timeout=0.0) == []


class TestAddressLookup:
    """
    A connection waits for its peer to publish its address. Sleeping a fixed
    second before looking again made a peer that was 20 ms late cost a full
    second of setup
    """

    def test_the_address_is_picked_up_as_soon_as_it_appears(self):
        from lithops.multiprocessing import connection as conn_mod

        client = MagicMock()
        client.get.side_effect = [None, None, b'tcp://127.0.0.1:5555']
        started = time.monotonic()
        addr = conn_mod._poll_until(
            lambda: client.get('h'),
            conn_mod.ADDRESS_LOOKUP_TIMEOUT,
            max_sleep=conn_mod.ADDRESS_LOOKUP_MAX_SLEEP,
        )
        assert addr == b'tcp://127.0.0.1:5555'
        assert time.monotonic() - started < 0.5

    def test_it_gives_up_after_the_timeout(self):
        from lithops.multiprocessing import connection as conn_mod

        client = MagicMock()
        client.get.return_value = None
        assert conn_mod._poll_until(lambda: client.get('h'), 0.05) is None
        assert client.get.call_count >= 1


class TestSemLockContract:
    """
    These follow multiprocessing.Lock/Semaphore, which callers write against
    """

    def test_acquire_takes_a_timeout(self, redis):
        """
        The standard library's signature is acquire(block, timeout). Not
        taking one turned every timed acquire into a TypeError
        """
        from lithops.multiprocessing import Lock

        lock = Lock()
        assert lock.acquire() is True
        try:
            assert lock.acquire(True, 0.1) is False
        finally:
            lock.release()

    def test_a_timeout_that_has_passed_is_a_single_attempt(self, redis):
        """
        BLPOP reads a zero timeout as "block for ever", so it cannot be
        handed one straight through
        """
        from lithops.multiprocessing import Lock

        lock = Lock()
        lock.acquire()
        try:
            assert lock.acquire(True, 0) is False
            assert lock.acquire(True, -1) is False
        finally:
            lock.release()

    def test_a_failed_acquire_does_not_claim_ownership(self, redis):
        """
        owned used to be set whatever the acquire returned, which left an
        RLock whose first acquire had failed reporting success on the next
        one: mutual exclusion handed out without the lock behind it
        """
        from lithops.multiprocessing import Lock, RLock

        lock = Lock()
        lock.acquire()
        try:
            assert lock.acquire(False) is False
            assert lock.owned is True   # this holder does own it
        finally:
            lock.release()

        rlock = RLock()
        rlock._client.delete(rlock._name)      # nothing left to take
        assert rlock.acquire(False) is False
        assert rlock.owned is False
        assert rlock.acquire(False) is False   # and still cannot claim it

    def test_rlock_counts_its_recursion(self, redis):
        """
        Only the first acquire takes the token and only the last release
        gives it back. Giving one back per release returned a token the
        re-entrant acquire never took
        """
        from lithops.multiprocessing import RLock

        rlock = RLock()
        assert rlock.acquire() is True
        assert rlock.acquire() is True
        rlock.release()
        assert rlock.owned is True             # still held after one release
        rlock.release()
        assert rlock.owned is False
        assert rlock.acquire(False) is True    # the token really came back
        rlock.release()

    def test_releasing_an_rlock_that_is_not_held_raises(self, redis):
        from lithops.multiprocessing import RLock

        with pytest.raises(AssertionError, match='not owned'):
            RLock().release()

    def test_a_bounded_semaphore_rejects_an_extra_release(self, redis):
        """
        A bounded semaphore that silently swallows an over-release is not
        bounded at all
        """
        from lithops.multiprocessing import BoundedSemaphore

        sem = BoundedSemaphore(1)
        sem.acquire()
        sem.release()
        with pytest.raises(ValueError, match='released too many times'):
            sem.release()

    def test_an_unbounded_semaphore_still_allows_extra_releases(self, redis):
        from lithops.multiprocessing import Semaphore

        sem = Semaphore(1)
        sem.release()
        sem.release()
        assert sem.get_value() == 3

    def test_releasing_a_lock_that_was_never_held_raises(self, redis):
        from lithops.multiprocessing import Lock

        with pytest.raises(ValueError, match='released too many times'):
            Lock().release()


class TestBlpopTimeoutFallback:
    """
    BLPOP takes a fractional timeout only from Redis 6.0 on. The fallback
    that rounds up for an older server must not be reached by anything else:
    it is process wide, so one wrong trip leaves every later wait rounded to
    the whole second
    """

    @staticmethod
    def _client(error=None):
        calls = []

        class FakeClient:
            def blpop(self, keys, timeout=0):
                calls.append(timeout)
                if error is not None and len(calls) == 1:
                    raise error
                return (keys[0], b'')

        return FakeClient(), calls

    @pytest.fixture(autouse=True)
    def _reset_flag(self):
        """The flag is module state, so a test must not leak it to the next"""
        sync = sys.modules['lithops.multiprocessing.synchronize']
        before = sync._BLPOP_TAKES_FLOAT
        sync._BLPOP_TAKES_FLOAT = True
        yield sync
        sync._BLPOP_TAKES_FLOAT = before

    def test_a_whole_second_timeout_never_goes_near_the_fallback(self, _reset_flag):
        client, calls = self._client()
        _reset_flag._blpop(client, 'k', 2)
        assert calls == [2]

    def test_a_fractional_timeout_is_passed_through(self, _reset_flag):
        client, calls = self._client()
        _reset_flag._blpop(client, 'k', 0.25)
        assert calls == [0.25]

    def test_an_old_server_rounds_the_wait_up(self, _reset_flag):
        import redis as redis_pkg

        error = redis_pkg.exceptions.ResponseError(
            'timeout is not an integer or out of range'
        )
        client, calls = self._client(error)
        _reset_flag._blpop(client, 'k', 0.25)
        # Rounded up, never down: 0 would mean "block for ever"
        assert calls == [0.25, 1]
        assert _reset_flag._BLPOP_TAKES_FLOAT is False

    def test_a_socket_timeout_is_not_mistaken_for_an_old_server(self, _reset_flag):
        """
        A read that timed out also says "timeout". Swallowing one would hide
        it and round every later wait up to the second for the whole process
        """
        import redis as redis_pkg

        error = redis_pkg.exceptions.TimeoutError('Timeout reading from socket')
        client, calls = self._client(error)

        with pytest.raises(redis_pkg.exceptions.TimeoutError):
            _reset_flag._blpop(client, 'k', 0.25)

        assert calls == [0.25]
        assert _reset_flag._BLPOP_TAKES_FLOAT is True

    def test_another_server_error_is_not_swallowed(self, _reset_flag):
        import redis as redis_pkg

        error = redis_pkg.exceptions.ResponseError('WRONGTYPE')
        client, calls = self._client(error)

        with pytest.raises(redis_pkg.exceptions.ResponseError, match='WRONGTYPE'):
            _reset_flag._blpop(client, 'k', 0.25)

        assert _reset_flag._BLPOP_TAKES_FLOAT is True

    def test_no_timeout_blocks_for_ever(self, _reset_flag):
        client, calls = self._client()
        _reset_flag._blpop(client, 'k', None)
        # int(None) would raise, and BLPOP reads zero as "block for ever"
        assert calls == [0]

    def test_a_condition_wait_uses_the_same_fallback(self, redis, _reset_flag):
        """
        Condition.wait(0.5) used to hand the fraction straight to BLPOP, so
        it failed on a server where a timed acquire worked
        """
        from lithops.multiprocessing import Condition

        seen = []
        real = _reset_flag._blpop

        def spy(client, name, timeout):
            seen.append(timeout)
            return real(client, name, timeout)

        cond = Condition()
        with patch.object(_reset_flag, '_blpop', spy):
            with cond:
                assert cond.wait(0.2) is False
        assert seen == [0.2]


class TestConditionContract:

    def test_wait_says_whether_it_was_notified(self, redis):
        """
        The standard library returns False on a timeout and True on a
        notify, and callers branch on it. Returning None made every wait
        look like a timeout
        """
        from lithops.multiprocessing import Condition

        cond = Condition()
        with cond:
            assert cond.wait(0.1) is False

        notified = []

        def waiter():
            with cond:
                notified.append(cond.wait(5))

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.3)
        with cond:
            cond.notify_all()
        thread.join(10)
        assert notified == [True]

    def test_wait_with_a_timeout_that_has_passed_does_not_block(self, redis):
        from lithops.multiprocessing import Condition

        cond = Condition()
        with cond:
            started = time.monotonic()
            assert cond.wait(0) is False
            assert time.monotonic() - started < 1


class TestWaitAlarm:
    """
    lithops.wait() arms a SIGALRM, and signal.alarm() only takes whole
    seconds
    """

    def test_a_fractional_timeout_is_rounded_up(self):
        lw = sys.modules['lithops.wait']

        armed = []
        with patch.object(lw.signal, 'alarm', side_effect=armed.append), \
                patch.object(lw.signal, 'signal'):
            lw._set_wait_alarm(0.2)
            lw._set_wait_alarm(2.7)
        # int() would give 0 and 2: the first cancels the alarm outright,
        # and the second cuts the wait short of what was asked for
        assert armed == [1, 3]

    def test_a_timeout_that_has_passed_raises_at_once(self):
        lw = sys.modules['lithops.wait']

        with pytest.raises(TimeoutError, match='Timeout of 0 seconds'):
            lw._set_wait_alarm(0)

    def test_pool_get_with_a_fractional_timeout_raises_timeout_error(self):
        """
        Pool.AsyncResult.get(0.2) reached signal.alarm() through wait() and
        came back as TypeError instead of the multiprocessing TimeoutError
        """
        lw = sys.modules['lithops.wait']

        with patch.object(lw.signal, 'alarm') as alarm, \
                patch.object(lw.signal, 'signal'):
            lw._set_wait_alarm(0.2)
        alarm.assert_called_once_with(1)
