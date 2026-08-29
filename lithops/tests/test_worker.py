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
import os
import pickle
import sys
import threading
from queue import Empty, Queue
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

import lithops.worker.handler as handler_module
from lithops.constants import JOBS_PREFIX, MODULES_DIR
from lithops.storage.utils import CloudObject, CloudObjectLocal, CloudObjectUrl
from lithops.utils import bytes_to_b64str, is_unix_system
from lithops.worker import function_handler, function_invoker
from lithops.worker.handler import (
    ShutdownSentinel,
    TaskJar,
    create_job,
    prepare_and_run_task,
    task_consumer,
    run_task,
)
from lithops.worker.jobrunner import JobRunner, JobStats, _prepare_args
from lithops.worker.status import (
    CallStatus,
    RabbitmqCallStatus,
    StorageCallStatus,
    create_call_status,
)
from lithops.worker.utils import (
    LogStream,
    SystemMonitor,
    custom_redirection,
    free_disk_space,
    get_function_and_modules,
    get_function_data,
    get_memory_usage,
    get_runtime_metadata,
    memory_monitor_worker,
    peak_memory,
    psutil_found,
)


def _job_config(monitoring='storage', **lithops):
    return {
        'lithops': {
            'storage': 'localhost',
            'backend': 'localhost',
            'monitoring': monitoring,
            **lithops,
        },
        'localhost': {'storage_bucket': 'bucket'},
        'rabbitmq': {'amqp_url': 'amqp://guest:guest@localhost:5672'},
    }


def _echo(x):
    return x


def _add(x):
    return x + 1


def _big(x):
    return 'y' * 9000


def _none(x):
    return None


def _boom(x):
    raise ValueError('nope')


def _obj_fn(obj):
    return 1


def _reduce_fn(results):
    return results


def _with_id_and_storage(x, id, storage):
    return x


class _Adder:
    def __call__(self, x):
        return x


def _return_futures_list(x):
    from lithops.utils import FuturesList
    return FuturesList()


def _record_task(task):
    """Leave a file behind, as a forked worker cannot share state in memory"""
    name = f'{task.call_id}-{task.data.decode()}'
    with open(os.path.join(task.out_dir, name), 'w') as fid:
        fid.write(str(os.getpid()))


def _task(**kwargs):
    values = dict(
        extra_env={},
        config=_job_config(),
        job_key='ek-j0',
        call_id='00000',
        log_level='ERROR',
        runtime_name='rt',
        runtime_memory=None,
        execution_timeout=10,
        start_tstamp=1.0,
        host_submit_tstamp=0.5,
        job_id='j0',
        executor_id='ek',
        chunksize=1,
        func=pickle.dumps(_echo),
        data=pickle.dumps({'x': 1}),
        stats_file='stats.txt',
    )
    values.update(kwargs)
    return SimpleNamespace(**values)


class TestPackageExports:

    def test_exports(self):
        import lithops.worker as worker
        assert worker.function_handler is function_handler
        assert worker.function_invoker is function_invoker
        assert worker.__all__ == ['function_handler', 'function_invoker']


class TestCreateJob:

    def test_loads_func_and_data(self):
        payload = {'config': _job_config(), 'job_key': 'jk'}
        with patch(
            'lithops.worker.handler.extract_storage_config', return_value={}
        ):
            with patch('lithops.worker.handler.InternalStorage') as store:
                with patch(
                    'lithops.worker.handler.get_function_and_modules',
                    return_value=b'f',
                ) as gf:
                    with patch(
                        'lithops.worker.handler.get_function_data',
                        return_value=[b'd'],
                    ) as gd:
                        job = create_job(payload)
        assert job.func == b'f'
        assert job.data == [b'd']
        gf.assert_called_once()
        gd.assert_called_once()
        store.assert_called_once()


class TestTaskConsumer:

    def test_runs_tasks_then_stops_on_sentinel(self):
        q = Queue()
        task = _task()
        q.put((task, '00001', b'data'))
        q.put(ShutdownSentinel())
        init = MagicMock()
        cb = MagicMock()
        with patch('lithops.worker.handler.prepare_and_run_task') as run:
            task_consumer(3, q, initializer=init, callback=cb)
        run.assert_called_once_with(task)
        assert task.call_id == '00001'
        assert task.data == b'data'
        init.assert_called_once_with(3, task)
        cb.assert_called_once_with(3, task)

    def test_none_initializer_and_callback_are_skipped(self):
        q = Queue()
        q.put(ShutdownSentinel())
        task_consumer(0, q)

    def test_empty_and_broken_pipe_stop_the_loop(self):
        q = MagicMock()
        q.get.side_effect = Empty()
        task_consumer(0, q)
        q.get.side_effect = BrokenPipeError()
        task_consumer(0, q)

    def test_a_failed_task_does_not_stop_the_worker(self):
        q = Queue()
        q.put((_task(), '00001', b'a'))
        q.put((_task(), '00002', b'b'))
        q.put(ShutdownSentinel())
        with patch(
            'lithops.worker.handler.prepare_and_run_task',
            side_effect=[OSError('no space left'), None],
        ) as run:
            with patch.object(handler_module.logger, 'error') as log_error:
                task_consumer(0, q)
        assert run.call_count == 2
        assert 'failed to run task 00001' in log_error.call_args[0][0]


class TestTaskJar:

    def _jar(self, n_calls):
        job = _task(
            call_ids=[f'{i:05}' for i in range(n_calls)],
            data=[f'd{i}'.encode() for i in range(n_calls)],
        )
        return TaskJar(job)

    def test_dispatch_hands_out_every_call_in_order(self):
        jar = self._jar(3)
        jar.dispatch()
        assert [jar.get()[1:] for _ in range(3)] == [
            ('00000', b'd0'), ('00001', b'd1'), ('00002', b'd2')
        ]
        with pytest.raises(Empty):
            jar.get()
        jar.close_reader()

    def test_get_returns_the_job_and_survives_data_rebinding(self):
        jar = self._jar(2)
        jar.dispatch()
        task, call_id, data = jar.get()
        assert task is jar.job
        # task_consumer rebinds job.data to the running task
        task.data = data
        assert jar.get()[1:] == ('00001', b'd1')
        jar.close_reader()

    def test_dispatch_survives_workers_that_died(self):
        jar = self._jar(2)
        jar.close_reader()
        with patch.object(handler_module.logger, 'error') as log_error:
            jar.dispatch()
        assert 'exited before consuming all tasks' in log_error.call_args[0][0]

    def test_tokens_are_never_split_by_a_partial_write(self):
        # More calls than a pipe buffer holds, so os.write returns short
        jar = self._jar(40000)
        writer = threading.Thread(target=jar.dispatch)
        writer.start()
        try:
            claimed = [jar.get()[1] for _ in range(40000)]
        finally:
            writer.join()
        assert claimed == [f'{i:05}' for i in range(40000)]
        jar.close_reader()


class TestFunctionHandler:

    def test_single_worker_uses_threading_queue(self):
        job = _task(worker_processes=4, call_ids=['00000'], data=[b'd'])
        with patch('lithops.worker.handler.create_job', return_value=job):
            with patch('lithops.worker.handler.setup_lithops_logger'):
                with patch(
                    'lithops.worker.handler.task_consumer'
                ) as consumer:
                    function_handler({})
        consumer.assert_called_once()
        assert consumer.call_args[0][0] == 0

    def test_multi_worker_starts_processes_and_joins(self):
        job = _task(
            worker_processes=2, call_ids=['00000', '00001'], data=[b'a', b'b']
        )
        proc = MagicMock()
        ctx = MagicMock()
        ctx.Process.return_value = proc
        with patch('lithops.worker.handler.create_job', return_value=job):
            with patch('lithops.worker.handler.setup_lithops_logger'):
                with patch('lithops.worker.handler._MP_CTX', ctx):
                    function_handler({})
        ctx.Manager.assert_not_called()
        assert ctx.Process.call_count == 2
        assert proc.start.call_count == 2
        assert proc.join.call_count == 2

    def test_multi_worker_runs_every_task_once(self):
        n_tasks = 6
        job = _task(
            worker_processes=3,
            call_ids=[f'{i:05}' for i in range(n_tasks)],
            data=[f'd{i}'.encode() for i in range(n_tasks)],
        )
        seen = []
        with patch('lithops.worker.handler.create_job', return_value=job):
            with patch('lithops.worker.handler.setup_lithops_logger'):
                with patch(
                    'lithops.worker.handler.prepare_and_run_task',
                    side_effect=lambda task: seen.append(
                        (task.call_id, task.data)
                    ),
                ):
                    with patch(
                        'lithops.worker.handler._run_process_pool',
                        new=handler_module._run_thread_pool,
                    ):
                        function_handler({})
        assert sorted(seen) == [
            (f'{i:05}', f'd{i}'.encode()) for i in range(n_tasks)
        ]

    @pytest.mark.skipif(
        not is_unix_system(), reason='the process pool needs fork'
    )
    # pytest itself is multi-threaded, which fork warns about since 3.12
    @pytest.mark.filterwarnings('ignore:.*fork.*:DeprecationWarning')
    def test_process_pool_runs_every_task_in_a_child(self, tmp_path):
        n_tasks = 8
        job = _task(
            worker_processes=4,
            call_ids=[f'{i:05}' for i in range(n_tasks)],
            data=[f'd{i}'.encode() for i in range(n_tasks)],
            out_dir=str(tmp_path),
        )
        with patch(
            'lithops.worker.handler.prepare_and_run_task', new=_record_task
        ):
            handler_module._run_process_pool(job, job.worker_processes)

        done = sorted(p.name for p in tmp_path.iterdir())
        assert done == [f'{i:05}-d{i}' for i in range(n_tasks)]
        pids = {p.read_text() for p in tmp_path.iterdir()}
        assert str(os.getpid()) not in pids

    def test_removes_module_path_and_total_executors(self):
        job = _task(worker_processes=1, call_ids=['00000'], data=[b'd'])
        module_path = os.path.join(MODULES_DIR, job.job_key)
        sys.path.append(module_path)
        os.environ['__LITHOPS_TOTAL_EXECUTORS'] = '2'
        try:
            with patch('lithops.worker.handler.create_job', return_value=job):
                with patch('lithops.worker.handler.setup_lithops_logger'):
                    with patch('lithops.worker.handler.task_consumer'):
                        function_handler({})
            assert module_path not in sys.path
            assert '__LITHOPS_TOTAL_EXECUTORS' not in os.environ
        finally:
            if module_path in sys.path:
                sys.path.remove(module_path)
            os.environ.pop('__LITHOPS_TOTAL_EXECUTORS', None)


class TestPrepareAndRunTask:

    def test_sets_env_creates_dir_and_clears_extra_env(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            'lithops.worker.handler.LITHOPS_TEMP_DIR', str(tmp_path)
        )
        os.environ.pop('__LITHOPS_ACTIVATION_ID', None)
        extra = {'FOO': 'bar'}
        task = _task(extra_env=extra, job_key='jk', call_id='c1')
        with patch('lithops.worker.handler.run_task') as run:
            prepare_and_run_task(task)
        run.assert_called_once_with(task)
        assert os.environ['LITHOPS_WORKER'] == 'True'
        assert os.environ['PYTHONUNBUFFERED'] == 'True'
        assert 'FOO' not in os.environ
        assert os.path.isdir(task.task_dir)
        assert task.task_dir == os.path.join(
            str(tmp_path), 'bucket', JOBS_PREFIX, 'jk', 'c1'
        )
        assert task.log_file == os.path.join(task.task_dir, 'execution.log')
        assert task.stats_file == os.path.join(task.task_dir, 'job_stats.txt')
        assert len(os.environ['__LITHOPS_ACTIVATION_ID']) == 12

    def test_keeps_existing_activation_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'lithops.worker.handler.LITHOPS_TEMP_DIR', str(tmp_path)
        )
        os.environ['__LITHOPS_ACTIVATION_ID'] = 'alreadythere1'
        task = _task(extra_env={})
        with patch('lithops.worker.handler.run_task'):
            prepare_and_run_task(task)
        assert os.environ['__LITHOPS_ACTIVATION_ID'] == 'alreadythere1'


class TestRunTask:

    def _patch_run(self, task, jrp, handler_conn, stats_text=None):
        if stats_text is not None:
            with open(task.stats_file, 'w') as f:
                f.write(stats_text)
        status = MagicMock()
        cpu = {'usage': [1], 'system': 0.1, 'user': 0.2}
        net = {'sent': 3, 'recv': 4}
        mem = {'rss': 5, 'vms': 6, 'uss': 7}
        monitor = MagicMock()
        monitor.get_cpu_info.return_value = cpu
        monitor.get_network_io.return_value = net
        monitor.get_memory_info.return_value = mem
        ctx = MagicMock()
        ctx.Pipe.return_value = (handler_conn, MagicMock())
        ctx.Process.return_value = jrp
        with patch('lithops.worker.handler.setup_lithops_logger'):
            with patch(
                'lithops.worker.handler.extract_storage_config', return_value={}
            ):
                with patch('lithops.worker.handler.InternalStorage'):
                    with patch(
                        'lithops.worker.handler.create_call_status',
                        return_value=status,
                    ):
                        with patch('lithops.worker.handler._MP_CTX', ctx):
                            with patch('lithops.worker.handler.JobRunner'):
                                with patch(
                                    'lithops.worker.handler.SystemMonitor',
                                    return_value=monitor,
                                ):
                                    with patch(
                                        'lithops.worker.handler.is_unix_system',
                                        return_value=True,
                                    ):
                                        run_task(task)
        return status

    def test_success_reads_stats_and_sends_events(self, tmp_path):
        task = _task()
        task.log_stream = MagicMock()
        task.log_file = str(tmp_path / 'execution.log')
        task.stats_file = str(tmp_path / 'job_stats.txt')
        (tmp_path / 'execution.log').write_bytes(b'log')
        jrp = MagicMock()
        jrp.is_alive.return_value = False
        conn = MagicMock()
        conn.poll.return_value = True
        status = self._patch_run(
            task, jrp, conn, 'worker_func_exec_time 1.5\nexception True\n'
        )
        status.send_init_event.assert_called_once()
        status.send_finish_event.assert_called_once()
        added = {c.args[0]: c.args[1] for c in status.add.call_args_list}
        assert added['worker_func_exec_time'] == 1.5
        assert added['exception'] is True
        assert 'logs' in added
        assert 'worker_end_tstamp' in added
        task.log_stream.flush.assert_called()

    def test_timeout_raises_handler_timeout_error(self, tmp_path):
        task = _task(execution_timeout=7)
        task.log_stream = MagicMock()
        task.log_file = str(tmp_path / 'execution.log')
        task.stats_file = str(tmp_path / 'missing.txt')
        jrp = MagicMock()
        jrp.is_alive.return_value = True
        conn = MagicMock()
        status = self._patch_run(task, jrp, conn)
        jrp.terminate.assert_called_once()
        added = {c.args[0]: c.args[1] for c in status.add.call_args_list}
        assert added['exception'] is True
        assert 'exc_info' in added

    def test_no_completion_message_is_memory_error(self, tmp_path):
        task = _task()
        task.log_stream = MagicMock()
        task.log_file = str(tmp_path / 'execution.log')
        task.stats_file = str(tmp_path / 'missing.txt')
        jrp = MagicMock()
        jrp.is_alive.return_value = False
        conn = MagicMock()
        conn.poll.return_value = False
        status = self._patch_run(task, jrp, conn)
        added = {c.args[0]: c.args[1] for c in status.add.call_args_list}
        assert added['exception'] is True

    def test_keyboard_interrupt_skips_finish_event(self, tmp_path):
        task = _task()
        task.log_stream = MagicMock()
        task.log_file = str(tmp_path / 'execution.log')
        task.stats_file = str(tmp_path / 'missing.txt')
        status = MagicMock()
        status.send_init_event.side_effect = KeyboardInterrupt()
        with patch('lithops.worker.handler.setup_lithops_logger'):
            with patch(
                'lithops.worker.handler.extract_storage_config', return_value={}
            ):
                with patch('lithops.worker.handler.InternalStorage'):
                    with patch(
                        'lithops.worker.handler.create_call_status',
                        return_value=status,
                    ):
                        run_task(task)
        status.send_finish_event.assert_not_called()

    def test_runtime_memory_log_branch(self, tmp_path):
        task = _task(runtime_memory=256)
        task.log_stream = MagicMock()
        task.log_file = str(tmp_path / 'execution.log')
        task.stats_file = str(tmp_path / 'missing.txt')
        jrp = MagicMock()
        jrp.is_alive.return_value = False
        conn = MagicMock()
        conn.poll.return_value = True
        self._patch_run(task, jrp, conn)

    def test_does_not_mutate_extra_env_with_session_id(self, tmp_path):
        extra = {}
        task = _task(extra_env=extra)
        task.log_stream = MagicMock()
        task.log_file = str(tmp_path / 'execution.log')
        task.stats_file = str(tmp_path / 'missing.txt')
        jrp = MagicMock()
        jrp.is_alive.return_value = False
        conn = MagicMock()
        conn.poll.return_value = True
        self._patch_run(task, jrp, conn)
        assert extra == {}
        assert '__LITHOPS_SESSION_ID' not in extra
        assert 'LITHOPS_CONFIG' not in extra


class TestGetFunctionAndModules:

    def test_loads_from_storage_without_modules(self):
        job = SimpleNamespace(
            config=_job_config(),
            func_key='func.pickle',
            job_key='jk',
        )
        payload = pickle.dumps({'func': b'FN', 'module_data': {}})
        storage = MagicMock()
        storage.get_func.return_value = payload
        assert get_function_and_modules(job, storage) == b'FN'
        storage.get_func.assert_called_once_with('func.pickle')

    def test_writes_modules_and_strips_slash(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.worker.utils.MODULES_DIR', str(tmp_path))
        job = SimpleNamespace(
            config=_job_config(),
            func_key='func.pickle',
            job_key='jk',
        )
        payload = pickle.dumps({
            'func': b'FN',
            'module_data': {
                '/pkg/a.py': bytes_to_b64str(b'aaa'),
                '/pkg/b.py': bytes_to_b64str(b'bbb'),
            },
        })
        storage = MagicMock()
        storage.get_func.return_value = payload
        path = os.path.join(str(tmp_path), 'jk')
        try:
            assert get_function_and_modules(job, storage) == b'FN'
            assert (tmp_path / 'jk' / 'pkg' / 'a.py').read_bytes() == b'aaa'
            assert (tmp_path / 'jk' / 'pkg' / 'b.py').read_bytes() == b'bbb'
            assert path in sys.path
        finally:
            if path in sys.path:
                sys.path.remove(path)

    def test_runtime_include_function_reads_local_file(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr('lithops.worker.utils.SA_INSTALL_DIR', str(tmp_path))
        func_file = tmp_path / 'func.pickle'
        func_file.write_bytes(pickle.dumps({'func': b'LOCAL'}))
        cfg = _job_config()
        cfg['localhost']['runtime_include_function'] = True
        job = SimpleNamespace(
            config=cfg, func_key='func.pickle', job_key='jk'
        )
        assert get_function_and_modules(job, MagicMock()) == b'LOCAL'

    def test_runtime_include_function_uses_posix_install_dir(self):
        payload = pickle.dumps({'func': b'LOCAL'})
        cfg = _job_config()
        cfg['localhost']['runtime_include_function'] = True
        job = SimpleNamespace(
            config=cfg, func_key='abc.func.pickle', job_key='jk'
        )
        with patch(
            'lithops.worker.utils.SA_INSTALL_DIR', '/opt/lithops'
        ), patch('builtins.open', mock_open(read_data=payload)) as opened:
            assert get_function_and_modules(job, MagicMock()) == b'LOCAL'
        assert opened.call_args[0][0] == '/opt/lithops/abc.func.pickle'
        assert '\\' not in opened.call_args[0][0]

    def test_makedirs_uses_exist_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr('lithops.worker.utils.MODULES_DIR', str(tmp_path))
        job = SimpleNamespace(
            config=_job_config(), func_key='f', job_key='jk'
        )
        payload = pickle.dumps({
            'func': b'FN',
            'module_data': {'a.py': bytes_to_b64str(b'x')},
        })
        storage = MagicMock()
        storage.get_func.return_value = payload
        real = os.makedirs

        def _makedirs(path, exist_ok=False):
            if not exist_ok:
                raise OSError(13, 'denied')
            return real(path, exist_ok=exist_ok)

        monkeypatch.setattr(os, 'makedirs', _makedirs)
        path = os.path.join(str(tmp_path), 'jk')
        try:
            assert get_function_and_modules(job, storage) == b'FN'
            assert (tmp_path / 'jk' / 'a.py').read_bytes() == b'x'
        finally:
            if path in sys.path:
                sys.path.remove(path)


class TestGetFunctionData:

    def test_byte_ranges_slice_aggregated_object(self):
        job = SimpleNamespace(
            data_key='data.pickle',
            data_byte_ranges=[(0, 2), (3, 5)],
        )
        storage = MagicMock()
        storage.get_data.return_value = b'abcdef'
        data = get_function_data(job, storage)
        assert data == [b'abc', b'def']
        extra = storage.get_data.call_args.kwargs['extra_get_args']
        assert extra['Range'] == 'bytes=0-5'

    def test_none_byte_ranges_returns_whole_object(self):
        job = SimpleNamespace(data_key='data.pickle', data_byte_ranges=None)
        storage = MagicMock()
        storage.get_data.return_value = b'all'
        assert get_function_data(job, storage) == [b'all']
        extra = storage.get_data.call_args.kwargs['extra_get_args']
        assert extra == {}

    def test_empty_byte_ranges_list_returns_whole_object(self):
        job = SimpleNamespace(data_key='data.pickle', data_byte_ranges=[])
        storage = MagicMock()
        storage.get_data.return_value = b'all'
        assert get_function_data(job, storage) == [b'all']
        extra = storage.get_data.call_args.kwargs['extra_get_args']
        assert extra == {}

    def test_payload_data_uses_literal_eval(self):
        job = SimpleNamespace(data_key=None, data_byte_strs=["b'abc'", "'x'"])
        assert get_function_data(job, MagicMock()) == [b'abc', 'x']

    def test_payload_data_bytes_pass_through(self):
        job = SimpleNamespace(data_key=None, data_byte_strs=[b'\x80abc'])
        assert get_function_data(job, MagicMock()) == [b'\x80abc']

    def test_payload_data_does_not_eval_expressions(self):
        job = SimpleNamespace(data_key=None, data_byte_strs=["1+1"])
        with pytest.raises((ValueError, SyntaxError)):
            get_function_data(job, MagicMock())


class TestWorkerUtils:

    def test_custom_redirection_restores_streams(self):
        buf = io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        with custom_redirection(buf):
            print('hello', end='')
            assert sys.stdout is buf
        assert sys.stdout is old_out
        assert sys.stderr is old_err
        assert buf.getvalue() == 'hello'

    def test_log_stream_write_flush_and_valueerror(self):
        stream = MagicMock()
        ls = LogStream(stream)
        ls.write('hi')
        stream.write.assert_called_with('hi')
        stream.flush.side_effect = ValueError()
        ls.flush()
        stream.write.side_effect = ValueError()
        ls.write('ignored')
        assert ls.fileno() == sys.stdout.fileno()

    def test_system_monitor_without_psutil(self, monkeypatch):
        monkeypatch.setattr('lithops.worker.utils.psutil_found', False)
        mon = SystemMonitor()
        mon.start()
        mon.stop()
        assert mon.get_cpu_info() == {"usage": [], "system": 0, "user": 0}
        assert mon.get_network_io() == {"sent": 0, "recv": 0}
        assert mon.get_memory_info() == {"rss": 0, "vms": 0, "uss": 0}

    def test_system_monitor_with_psutil(self):
        if not psutil_found:
            pytest.skip('psutil not installed')
        mon = SystemMonitor()
        mon.start()
        mon.stop()
        cpu = mon.get_cpu_info()
        assert 'usage' in cpu and 'system' in cpu and 'user' in cpu
        net = mon.get_network_io()
        assert 'sent' in net and 'recv' in net
        mem = mon.get_memory_info()
        assert mem['rss'] >= 0

    def test_get_runtime_metadata(self):
        meta = get_runtime_metadata()
        assert 'preinstalls' in meta
        assert all(len(entry) == 2 for entry in meta['preinstalls'])
        assert meta['python_version'] == (
            str(sys.version_info[0]) + "." + str(sys.version_info[1])
        )
        assert 'lithops_version' in meta

    def test_peak_memory_and_disk(self, tmp_path):
        mem = peak_memory()
        assert mem is None or mem >= 0
        assert free_disk_space(str(tmp_path)) > 0

    def test_get_memory_usage_non_root_returns_none(self):
        if os.geteuid() != 0:
            assert get_memory_usage() is None

    def test_memory_monitor_sends_peak_on_poll(self):
        conn = MagicMock()
        conn.poll.return_value = True
        with patch(
            'lithops.worker.utils.get_memory_usage', return_value=10
        ):
            memory_monitor_worker(conn, delay=0)
        conn.send.assert_called_once()

    def test_memory_monitor_breaks_when_usage_is_none(self):
        conn = MagicMock()
        conn.poll.side_effect = [False, True]
        with patch(
            'lithops.worker.utils.get_memory_usage', return_value=None
        ):
            memory_monitor_worker(conn, delay=0)
        conn.send.assert_called_once_with(0)


class TestCallStatus:

    def test_create_call_status_storage_and_rabbitmq(self):
        job = _task()
        st = create_call_status(job, MagicMock())
        assert isinstance(st, StorageCallStatus)
        job.config['lithops']['monitoring'] = 'rabbitmq'
        rb = create_call_status(job, MagicMock())
        assert isinstance(rb, RabbitmqCallStatus)

    def test_warm_container_flag(self, monkeypatch):
        monkeypatch.delenv('WARM_CONTAINER', raising=False)
        job = _task()
        first = CallStatus(job, MagicMock())
        assert first.status['worker_cold_start'] is True
        assert os.environ['WARM_CONTAINER'] == 'True'
        second = CallStatus(job, MagicMock())
        assert second.status['worker_cold_start'] is False

    def test_warm_container_invalid_value_is_cold_start(self, monkeypatch):
        monkeypatch.setenv('WARM_CONTAINER', 'maybe')
        status = CallStatus(_task(), MagicMock())
        assert status.status['worker_cold_start'] is True
        assert os.environ['WARM_CONTAINER'] == 'True'

    def test_storage_init_and_end_events(self):
        import json
        storage = MagicMock()
        status = StorageCallStatus(_task(), storage)
        status.send_init_event()
        assert storage.put_data.call_args[0][1] == ''
        status.add('foo', 1)
        status.send_finish_event()
        body = storage.put_data.call_args[0][1]
        payload = json.loads(body)
        assert payload['type'] == '__end__'
        assert payload['foo'] == 1

    def test_rabbitmq_end_also_writes_storage(self):
        job = _task()
        job.executor_id = 'a-b-c-d'
        # One publish per queue in the chain the client sent
        job.monitoring_queues = ['lithops-a-b', 'lithops-a-b-c-d']
        job.config = _job_config(monitoring='rabbitmq')
        storage = MagicMock()
        channel = MagicMock()
        conn = MagicMock()
        conn.channel.return_value = channel
        status = RabbitmqCallStatus(job, storage)
        status.status['type'] = '__end__'
        status.status['activation_id'] = 'act'
        with patch(
            'lithops.worker.status.pika.BlockingConnection', return_value=conn
        ):
            status._send()
        assert channel.basic_publish.call_count == 2
        assert storage.put_data.called

    def test_rabbitmq_publishes_to_the_queues_it_was_given(self):
        job = _task()
        job.executor_id = 'sess-0-M000-00000-0'
        job.monitoring_queues = [
            'lithops-sess-0', 'lithops-sess-0-M000-00000-0'
        ]
        job.config = _job_config(monitoring='rabbitmq')
        status = RabbitmqCallStatus(job, MagicMock())
        assert status._queue_names() == job.monitoring_queues

    def test_rabbitmq_falls_back_to_its_own_queue(self):
        # A payload with no chain can only reach this executor's own queue
        job = _task()
        job.executor_id = 'sess-0-M000-00000-0'
        job.config = _job_config(monitoring='rabbitmq')
        status = RabbitmqCallStatus(job, MagicMock())
        assert status._queue_names() == ['lithops-sess-0-M000-00000-0']

    def test_rabbitmq_gives_up_after_five_failures(self):
        job = _task()
        job.executor_id = 'a-b'
        job.config = _job_config(monitoring='rabbitmq')
        storage = MagicMock()
        status = RabbitmqCallStatus(job, storage)
        status.status['type'] = '__init__'
        with patch(
            'lithops.worker.status.pika.BlockingConnection',
            side_effect=Exception('down'),
        ):
            test_thread = threading.current_thread()
            sleeps = []

            def sleep(_seconds):
                if threading.current_thread() is test_thread:
                    sleeps.append(_seconds)

            with patch('lithops.worker.status.time.sleep', side_effect=sleep):
                status._send()
        assert len(sleeps) == 5
        storage.put_data.assert_not_called()


class TestJobStatsAndPrepareArgs:

    def test_job_stats_write(self, tmp_path):
        path = tmp_path / 'stats.txt'
        stats = JobStats(str(path))
        stats.write('k', 1.5)
        stats.write('s', 'x')
        stats.__del__()
        assert path.read_text() == 'k 1.5\ns x\n'

    def test_prepare_args_kwargs_only(self):
        def f(a, b=1):
            return a + b
        args, kwargs = _prepare_args(f, {'a': 2, 'b': 3})
        assert args == ()
        assert kwargs == {'a': 2, 'b': 3}
        assert f(*args, **kwargs) == 5

    def test_prepare_args_varargs_empty_list_is_kept(self):
        def f(*args, **kwargs):
            return args, kwargs
        args, kwargs = _prepare_args(f, {'args': [], 'kwargs': {}, 'x': 1})
        assert args == []
        assert kwargs == {'x': 1}

    def test_prepare_args_custom_var_names(self):
        def f(*xs, **kw):
            return xs, kw
        args, kwargs = _prepare_args(
            f, {'xs': (1, 2), 'kw': {'a': 3}, 'b': 4}
        )
        assert args == (1, 2)
        assert kwargs == {'a': 3, 'b': 4}


class TestJobRunner:

    @pytest.fixture(autouse=True)
    def _session_id(self, monkeypatch, tmp_path):
        monkeypatch.setenv('__LITHOPS_SESSION_ID', 'sid-1')
        self.stats = str(tmp_path / 'stats.txt')

    def _runner(self, func, data, **job_kwargs):
        job = _task(
            func=pickle.dumps(func),
            data=pickle.dumps(data),
            stats_file=self.stats,
            config=_job_config(telemetry=False),
            **job_kwargs
        )
        conn = MagicMock()
        storage = MagicMock()
        storage.backend = 'localhost'
        storage.storage = MagicMock()
        return JobRunner(job, conn, storage)

    def test_run_small_result_stored_in_stats(self):
        jr = self._runner(_add, {'x': 1})
        jr.run()
        jr.jobrunner_conn.send.assert_called_with('Finished')
        text = open(self.stats).read()
        assert 'func_result_size' in text
        assert 'result' in text
        jr.internal_storage.put_data.assert_not_called()

    def test_run_large_result_uploaded(self):
        jr = self._runner(_big, {'x': 1})
        jr.run()
        jr.internal_storage.put_data.assert_called_once()
        text = open(self.stats).read()
        assert 'worker_result_upload_time' in text

    def test_run_none_result_skips_upload(self):
        jr = self._runner(_none, {'x': 1})
        jr.run()
        jr.internal_storage.put_data.assert_not_called()

    def test_run_exception_records_exc_info(self):
        jr = self._runner(_boom, {'x': 1})
        jr.run()
        text = open(self.stats).read()
        assert 'exception True' in text
        assert 'exc_info' in text
        jr.jobrunner_conn.send.assert_called_with('Finished')

    def test_fill_optional_args_id_and_storage(self):
        jr = self._runner(_echo, {'x': 1}, call_id='00007')
        data = {'x': 1}
        jr._fill_optional_args(_with_id_and_storage, data)
        assert data['id'] == 7
        assert data['storage'] is jr.internal_storage.storage

    def test_fill_optional_args_missing_ibm_cos_and_rabbitmq(self):
        def f(ibm_cos):
            pass

        def g(rabbitmq):
            pass
        jr = self._runner(_echo, {'x': 1})
        jr.lithops_config.pop('rabbitmq', None)
        with pytest.raises(Exception, match='ibm_cos'):
            jr._fill_optional_args(f, {})
        with pytest.raises(Exception, match='rabbitmq'):
            jr._fill_optional_args(g, {})

    def test_fill_optional_args_ibm_cos_same_backend(self):
        def f(ibm_cos):
            pass
        jr = self._runner(_echo, {'x': 1})
        jr.lithops_config['ibm_cos'] = {}
        jr.internal_storage.backend = 'ibm_cos'
        jr.internal_storage.get_client.return_value = 'client'
        data = {}
        jr._fill_optional_args(f, data)
        assert data['ibm_cos'] == 'client'

    def test_fill_optional_args_ibm_cos_other_backend(self):
        def f(ibm_cos):
            pass
        jr = self._runner(_echo, {'x': 1})
        jr.lithops_config['ibm_cos'] = {}
        data = {}
        with patch('lithops.worker.jobrunner.Storage') as st:
            st.return_value.get_client.return_value = 'other'
            jr._fill_optional_args(f, data)
        assert data['ibm_cos'] == 'other'

    def test_fill_optional_args_future_chaining(self):
        jr = self._runner(_echo, {'x': 1})
        future = MagicMock()
        future.result.return_value = 9
        data = {'future': future}
        jr._fill_optional_args(_echo, data)
        assert data['x'] == 9
        assert 'future' not in data

    def test_wait_futures_replaces_first_value(self):
        jr = self._runner(_echo, {'x': 1})
        done = MagicMock(done=True, futures=False)
        done.result.return_value = 5
        skip = MagicMock(done=True, futures=True)
        data = {'results': [done, skip]}
        with patch('lithops.worker.jobrunner.wait'):
            jr._wait_futures(data)
        assert data['results'] == [5]

    def test_load_object_from_path(self, tmp_path):
        path = tmp_path / 'obj.bin'
        path.write_bytes(b'abcdefghij')
        obj = CloudObjectLocal(str(path))
        obj.data_byte_range = (2, 6)
        obj.chunk_size = 5
        obj.newline = None
        obj.part = 1
        obj.total_parts = 1
        jr = self._runner(_obj_fn, {'obj': obj})
        jr._load_object({'obj': obj})
        assert obj.data_stream.read() == b'cdefg'
        assert obj.data_byte_range == (2, 6)

    def test_load_object_without_range_sets_full_chunk(self, tmp_path):
        path = tmp_path / 'obj.bin'
        path.write_bytes(b'abc')
        obj = CloudObjectLocal(str(path))
        obj.data_byte_range = None
        obj.chunk_size = 10
        obj.part = 1
        obj.total_parts = 1
        jr = self._runner(_obj_fn, {'obj': obj})
        jr._load_object({'obj': obj})
        assert obj.data_byte_range == (0, 9)
        assert obj.data_stream.read() == b'abc'

    def test_load_object_url_and_storage(self):
        obj = CloudObjectUrl('http://example.com/a')
        obj.data_byte_range = (0, 10)
        obj.chunk_size = 5
        obj.newline = '\n'
        obj.part = 1
        obj.total_parts = 2
        raw = io.BytesIO(b'hello')
        resp = MagicMock(raw=raw)
        jr = self._runner(_obj_fn, {'obj': obj})
        with patch(
            'lithops.worker.jobrunner.requests.get', return_value=resp
        ):
            jr._load_object({'obj': obj})
        assert obj.data_byte_range == (0, 4)

    def test_load_object_cloudobject_other_backend(self):
        obj = CloudObject('aws_s3', 'b', 'k')
        obj.data_byte_range = None
        obj.chunk_size = 3
        obj.part = 1
        obj.total_parts = 1
        jr = self._runner(_obj_fn, {'obj': obj})
        with patch('lithops.worker.jobrunner.Storage') as st:
            st.return_value.get_object.return_value = io.BytesIO(b'xyz')
            jr._load_object({'obj': obj})
        st.assert_called_once()

    def test_new_futures_list_skips_result_upload(self):
        jr = self._runner(_return_futures_list, {'x': 1})
        jr.run()
        text = open(self.stats).read()
        assert 'new_futures' in text
        jr.internal_storage.put_data.assert_not_called()

    def test_reduce_job_waits_for_futures(self, monkeypatch):
        monkeypatch.setenv('__LITHOPS_REDUCE_JOB', 'True')
        jr = self._runner(_reduce_fn, {'results': []})
        with patch.object(jr, '_wait_futures') as wait_f:
            jr.run()
        wait_f.assert_called_once()

    def test_object_processing_loads_object(self, tmp_path):
        path = tmp_path / 'o.bin'
        path.write_bytes(b'abcd')
        obj = CloudObjectLocal(str(path))
        obj.data_byte_range = None
        obj.chunk_size = 4
        obj.part = 1
        obj.total_parts = 1
        jr = self._runner(_obj_fn, {'obj': obj})
        with patch.object(jr, '_load_object') as load:
            jr.run()
        load.assert_called_once()

    def test_prepost_hooks(self, monkeypatch):
        calls = []

        def pre():
            calls.append('pre')

        def post():
            calls.append('post')

        monkeypatch.setenv('PRE_RUN', 'pre')
        monkeypatch.setenv('POST_RUN', 'post')
        jr = self._runner(_echo, {'x': 1})
        with patch(
            'lithops.worker.jobrunner.locate', side_effect=[pre, post]
        ):
            jr.run()
        assert calls == ['pre', 'post']

    def test_callable_class_function_name(self):
        jr = self._runner(_Adder(), {'x': 1})
        jr.run()
        text = open(self.stats).read()
        assert 'func_result_size' in text


class TestFunctionInvoker:

    def test_function_invoker_wires_handlers(self, monkeypatch):
        monkeypatch.delenv('LITHOPS_WORKER', raising=False)
        payload = {
            'config': _job_config(
                monitoring='storage', backend='aws_lambda'
            ),
            'job': {
                'job_key': 'jk',
                'executor_id': 'ex',
                'job_id': 'j0',
                'chunksize': 1,
            },
        }
        payload['config']['aws_lambda'] = {}
        invoker = MagicMock()
        with patch(
            'lithops.worker.invoker.extract_storage_config', return_value={}
        ):
            with patch('lithops.worker.invoker.InternalStorage'):
                with patch(
                    'lithops.worker.invoker.extract_serverless_config',
                    return_value={},
                ):
                    with patch('lithops.worker.invoker.ServerlessHandler'):
                        with patch('lithops.worker.invoker.JobMonitor'):
                            with patch(
                                'lithops.worker.invoker.FaaSRemoteInvoker',
                                return_value=invoker,
                            ):
                                function_invoker(payload)
        invoker.run_job.assert_called_once()
        assert os.environ['LITHOPS_WORKER'] == 'True'
        assert payload['config']['aws_lambda']['invoke_pool_threads'] == 128

    def test_remote_invoker_run_job_drains_then_stops_waiting(self):
        from lithops.worker.invoker import FaaSRemoteInvoker
        inv = FaaSRemoteInvoker.__new__(FaaSRemoteInvoker)
        inv.job_monitor = MagicMock()
        inv.pending_calls_q = MagicMock()
        inv.pending_calls_q.qsize.side_effect = [2, 0]
        inv.stop = MagicMock()
        inv._run_job = MagicMock(return_value=['f'])
        job = SimpleNamespace(job_id='j0', chunksize=1)
        test_thread = threading.current_thread()
        sleeps = []

        def sleep(_seconds):
            if threading.current_thread() is test_thread:
                sleeps.append(_seconds)

        with patch('lithops.worker.invoker.time.sleep', side_effect=sleep):
            inv.run_job(job)
        inv.job_monitor.start.assert_called_once()
        inv.job_monitor.stop.assert_called_once()
        # Waits for the invocations in flight instead of sleeping on a guess
        inv.stop.assert_called_once_with(wait=True)
        assert sleeps == [1]
