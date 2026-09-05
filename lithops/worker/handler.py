#
# (C) Copyright IBM Corp. 2020
# (C) Copyright Cloudlab URV 2020
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
import ast
import zlib
import time
import json
import uuid
import base64
import pickle
import struct
import logging
import signal
import traceback
import multiprocessing as mp
from queue import Queue, Empty
from threading import Thread
from tblib import pickling_support
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional, Tuple, Union

from lithops.version import __version__
from lithops.config import extract_storage_config
from lithops.storage import InternalStorage
from lithops.worker.jobrunner import JobRunner
from lithops.worker.utils import (
    LogStream, custom_redirection, get_function_and_modules,
    get_function_data, SystemMonitor
)
from lithops.constants import JOBS_PREFIX, LITHOPS_TEMP_DIR, MODULES_DIR
from lithops.utils import (
    MONITORING_QUEUES_ENV,
    setup_lithops_logger,
    is_unix_system,
)
from lithops.monitoring import create_call_status

pickling_support.install()

logger = logging.getLogger(__name__)

# Python 3.14 defaults to forkserver on Linux, which requires pickling Process
# arguments. Lithops relies on fork semantics: both the JobRunner subprocess
# and the worker processes inherit the task from their parent.
_MP_CTX = mp.get_context('fork') if is_unix_system() else mp

# A task, as passed from the work queue to a worker: (job, call_id, data)
Task = Tuple[SimpleNamespace, str, Any]


class ShutdownSentinel:
    """Put an instance of this class on the queue to shut it down"""
    pass


class TaskJar:
    """
    Work queue for forked worker processes, backed by a single POSIX pipe.

    Workers inherit the job and its data through fork, so the pipe only
    carries a fixed size task index. Reading one is how a worker claims a
    task: the kernel hands every token to exactly one reader, which balances
    the load without a lock. Unlike multiprocessing.Queue and Manager this
    needs no POSIX shared memory, so it also works on FaaS sandboxes that do
    not provide /dev/shm.
    """
    TOKEN = struct.Struct('!i')
    # Writes up to PIPE_BUF are atomic, so a token is never split in two and
    # readers stay aligned. 512 is the smallest PIPE_BUF POSIX allows.
    MAX_ATOMIC_WRITE = 512

    def __init__(self, job: SimpleNamespace):
        self.job = job
        # A worker rebinds job.data to the task it is running, so keep an
        # independent reference to the full list of calls.
        self.calls = list(zip(job.call_ids, job.data))
        self.read_fd, self.write_fd = os.pipe()

    def close_reader(self) -> None:
        """
        Drops the parent's read end. Called once every worker is forked, so
        that dispatch() fails instead of blocking if all the workers die.
        """
        os.close(self.read_fd)

    def close_writer(self) -> None:
        """
        Drops a worker's inherited write end. Called by every worker, as
        otherwise the pipe never reaches EOF and no worker ever stops.
        """
        os.close(self.write_fd)

    def dispatch(self) -> None:
        """
        Offers every task to the workers, then closes the pipe so that they
        see EOF and stop. Called by the parent process.
        """
        tokens = b''.join(self.TOKEN.pack(i) for i in range(len(self.calls)))
        view = memoryview(tokens)
        try:
            while view:
                written = os.write(self.write_fd, view[:self.MAX_ATOMIC_WRITE])
                view = view[written:]
        except BrokenPipeError:
            logger.error('Worker processes exited before consuming all tasks')
        finally:
            self.close_writer()

    def get(self) -> Task:
        """
        Claims the next task, blocking until one is available. Raises Empty
        once the jar is exhausted.
        """
        token = b''
        while len(token) < self.TOKEN.size:
            chunk = os.read(self.read_fd, self.TOKEN.size - len(token))
            if not chunk:
                raise Empty
            token += chunk

        index, = self.TOKEN.unpack(token)
        call_id, data = self.calls[index]
        return self.job, call_id, data


def create_job(payload: Dict[str, Any]) -> SimpleNamespace:
    """
    Builds a job out of an invocation payload, downloading the function,
    the modules and the data it refers to
    """
    job = SimpleNamespace(**payload)
    storage_config = extract_storage_config(job.config)
    internal_storage = InternalStorage(storage_config)
    job.func = get_function_and_modules(job, internal_storage)
    job.data = get_function_data(job, internal_storage)
    return job


def _fill_queue(job: SimpleNamespace, worker_processes: int) -> Queue:
    """
    Loads every task of the job in a queue, followed by one sentinel per
    worker. Every task is known upfront, so nothing is queued afterwards
    """
    work_queue = Queue()

    for call_id, data in zip(job.call_ids, job.data):
        work_queue.put((job, call_id, data))

    for _ in range(worker_processes):
        work_queue.put(ShutdownSentinel())

    return work_queue


def _jar_worker(pid: int, jar: TaskJar) -> None:
    """
    Entry point of a forked worker process
    """
    jar.close_writer()
    task_consumer(pid, jar)


def _run_process_pool(job: SimpleNamespace, worker_processes: int) -> None:
    """
    Runs the tasks of the job in forked processes, each one claiming the next
    task from the jar as soon as it is free
    """
    jar = TaskJar(job)
    workers = []

    for pid in range(worker_processes):
        worker = _MP_CTX.Process(target=_jar_worker, args=(pid, jar))
        workers.append(worker)
        worker.start()

    jar.close_reader()
    jar.dispatch()

    for worker in workers:
        worker.join()


def _run_thread_pool(job: SimpleNamespace, worker_processes: int) -> None:
    """
    Runs the tasks of the job in threads. Used where there is no fork, so
    tasks share this interpreter instead of getting a process each
    """
    work_queue = _fill_queue(job, worker_processes)
    workers = []

    for pid in range(worker_processes):
        worker = Thread(target=task_consumer, args=(pid, work_queue))
        workers.append(worker)
        worker.start()

    for worker in workers:
        worker.join()


def function_handler(payload: Dict[str, Any]) -> None:
    """
    Default function entry point called from Serverless backends
    """
    job = create_job(payload)
    setup_lithops_logger(job.log_level)

    worker_processes = min(job.worker_processes, len(job.call_ids))
    logger.info(
        f'Tasks received: {len(job.call_ids)} - '
        f'Worker processes: {worker_processes}'
    )

    if worker_processes == 1:
        task_consumer(0, _fill_queue(job, worker_processes))
    elif is_unix_system():
        _run_process_pool(job, worker_processes)
    else:
        _run_thread_pool(job, worker_processes)

    module_path = os.path.join(MODULES_DIR, job.job_key)
    if module_path in sys.path:
        sys.path.remove(module_path)

    os.environ.pop('__LITHOPS_TOTAL_EXECUTORS', None)


def task_consumer(
    pid: int,
    work_queue: Union[Queue, TaskJar],
    initializer: Optional[Callable] = None,
    callback: Optional[Callable] = None
) -> None:
    """
    Runs tasks until the work queue is exhausted.

    Takes either a threading Queue, terminated by a ShutdownSentinel, or a
    TaskJar, which raises Empty once its pipe reaches EOF.
    """
    logger.info(f'Worker {pid} started')
    tasks_done = 0

    while True:
        try:
            event = work_queue.get()
        except (Empty, BrokenPipeError):
            break

        if isinstance(event, ShutdownSentinel):
            break

        task, call_id, data = event
        task.call_id = call_id
        task.data = data

        try:
            if initializer:
                initializer(pid, task)

            prepare_and_run_task(task)

            if callback:
                callback(pid, task)
        except Exception as e:
            # Do not lose this worker for the tasks that are still pending
            logger.error(f'Worker {pid} failed to run task {call_id}: {e}')

        tasks_done += 1

    logger.info(f'Worker {pid} finished, {tasks_done} tasks executed')


def prepare_and_run_task(task: SimpleNamespace) -> None:
    """
    Sets up the environment and the working directory of a single task, and
    runs it with its output redirected to the task log
    """
    task.start_tstamp = time.time()

    if '__LITHOPS_ACTIVATION_ID' not in os.environ:
        act_id = str(uuid.uuid4()).replace('-', '')[:12]
        os.environ['__LITHOPS_ACTIVATION_ID'] = act_id

    os.environ['LITHOPS_WORKER'] = 'True'
    os.environ['PYTHONUNBUFFERED'] = 'True'
    os.environ.update(task.extra_env)

    storage_backend = task.config['lithops']['storage']
    bucket = task.config[storage_backend]['storage_bucket']
    task.task_dir = os.path.join(
        LITHOPS_TEMP_DIR, bucket, JOBS_PREFIX, task.job_key, task.call_id
    )
    task.log_file = os.path.join(task.task_dir, 'execution.log')
    task.stats_file = os.path.join(task.task_dir, 'job_stats.txt')
    os.makedirs(task.task_dir, exist_ok=True)

    with open(task.log_file, 'a') as log_stream:
        task.log_stream = LogStream(log_stream)
        with custom_redirection(task.log_stream):
            run_task(task)

    for key in task.extra_env:
        os.environ.pop(key, None)


# Windows has no SIGKILL, and no process there is reported as killed by one
_SIGKILL = getattr(signal, 'SIGKILL', None)

#: Apple's own opt-out of the fork() safety check of its frameworks, which
#: aborts a child forked from a process where one of them was being set up
FORK_SAFETY_ENV = 'OBJC_DISABLE_INITIALIZE_FORK_SAFETY'


def _allow_fork_after_a_client_exists() -> None:
    """
    Lets the worker fork the JobRunner off while a monitoring client is open.

    A worker keeps its client for the whole process, so from the second call
    on there is one alive when the next JobRunner is forked. On macOS that is
    what the fork() safety check of the Apple frameworks can abort the child
    over, and this is the workaround Apple documents for it — the same one
    the error message of a dead JobRunner points at. Set before the first
    fork, and never over a value the user chose
    """
    if sys.platform != 'darwin' or FORK_SAFETY_ENV in os.environ:
        return
    os.environ[FORK_SAFETY_ENV] = 'YES'


def _jobrunner_death_reason(exitcode: Optional[int]) -> str:
    """
    Explains why the JobRunner left without reporting its result. A
    negative exit code is the number of the signal that killed it
    """
    if exitcode is None:
        return (
            'The function ended without reporting its result, and left no '
            'exit code to say why: either it ran in a thread, which has '
            'none, or the process is somehow still running'
        )
    if exitcode >= 0:
        return (
            f'The function process exited with code {exitcode} before '
            'reporting its result'
        )

    killed_by = -exitcode
    try:
        name = signal.Signals(killed_by).name
    except ValueError:
        name = f'signal {killed_by}'

    if killed_by == _SIGKILL:
        return (
            'The function process was killed with SIGKILL, which is what '
            'the out-of-memory killer does: the function most likely '
            'exceeded the memory available to it'
        )
    if killed_by == signal.SIGABRT and sys.platform == 'darwin':
        return (
            'The function process was aborted with SIGABRT. On macOS this '
            'is usually the fork() safety check of the Apple frameworks: '
            'something the parent process had already used, such as a '
            'network client, cannot be used again in a forked child. '
            'Setting OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES in the '
            'environment works around it'
        )
    return f'The function process was killed with {name}'


def _add_resource_usage(call_status, sys_monitor: SystemMonitor) -> None:
    """
    Reports the CPU, network and memory that the task consumed
    """
    cpu_info = sys_monitor.get_cpu_info()
    call_status.add('worker_func_cpu_usage', cpu_info['usage'])
    call_status.add('worker_func_cpu_system_time', round(cpu_info['system'], 8))
    call_status.add('worker_func_cpu_user_time', round(cpu_info['user'], 8))

    net_io = sys_monitor.get_network_io()
    call_status.add('worker_func_sent_net_io', net_io['sent'])
    call_status.add('worker_func_recv_net_io', net_io['recv'])

    mem_info = sys_monitor.get_memory_info()
    call_status.add('worker_func_rss', mem_info['rss'])
    call_status.add('worker_func_vms', mem_info['vms'])
    call_status.add('worker_func_uss', mem_info['uss'])


def _add_task_stats(call_status, stats_file: str) -> None:
    """
    Reports the stats the JobRunner wrote, if it got as far as writing them
    """
    if not os.path.exists(stats_file):
        return

    with open(stats_file, 'r') as fid:
        for line in fid.readlines():
            key, value = line.strip().split(" ", 1)
            try:
                call_status.add(key, float(value))
            except ValueError:
                call_status.add(key, value)
            if key in ['exception', 'exc_pickle_fail']:
                call_status.add(key, ast.literal_eval(value))


def _add_exception(call_status) -> None:
    """
    Prints the traceback to the task log and reports it back to the client.
    Only valid while handling an exception
    """
    print('----------------------- EXCEPTION !-----------------------')
    traceback.print_exc(file=sys.stdout)
    print('----------------------------------------------------------')
    call_status.add('exception', True)

    pickled_exc = pickle.dumps(sys.exc_info())
    pickle.loads(pickled_exc)  # fail here if the client could not unpickle it
    call_status.add('exc_info', str(pickled_exc))


def _add_logs(call_status, task: SimpleNamespace) -> None:
    """
    Reports the task log, compressed, so that the client can replay it
    """
    task.log_stream.flush()
    if not os.path.isfile(task.log_file):
        return

    with open(task.log_file, 'rb') as log_file:
        compressed = zlib.compress(log_file.read())
        call_status.add('logs', base64.b64encode(compressed).decode())


def run_task(task: SimpleNamespace) -> None:
    """
    Runs a single task, with the user function isolated in a JobRunner
    subprocess, and reports its status and its resource usage
    """
    setup_lithops_logger(task.log_level)

    backend = os.environ.get('__LITHOPS_BACKEND', '')
    logger.info(f"Lithops v{__version__} - Starting {backend} execution")
    logger.info(f"Execution ID: {task.job_key}/{task.call_id}")

    injected_env = {
        'LITHOPS_CONFIG': json.dumps(task.config),
        '__LITHOPS_SESSION_ID': '-'.join([task.job_key, task.call_id]),
        # An executor created by the user function reports to these queues as
        # well as to its own, which is how a nested job reaches the client
        MONITORING_QUEUES_ENV: json.dumps(
            getattr(task, 'monitoring_queues', None) or []
        ),
    }
    os.environ.update(task.extra_env)
    os.environ.update(injected_env)
    _allow_fork_after_a_client_exists()

    storage_config = extract_storage_config(task.config)
    internal_storage = InternalStorage(storage_config)
    call_status = create_call_status(task, internal_storage)

    if task.runtime_memory:
        logger.debug(
            f'Runtime: {task.runtime_name} - Memory: {task.runtime_memory}MB - '
            f'Timeout: {task.execution_timeout} seconds'
        )
    else:
        logger.debug(
            f'Runtime: {task.runtime_name} - '
            f'Timeout: {task.execution_timeout} seconds'
        )

    job_interrupted = False

    try:
        handler_conn, jobrunner_conn = _MP_CTX.Pipe()
        jobrunner = JobRunner(task, jobrunner_conn, internal_storage)
        logger.debug('Starting JobRunner process')
        jrp = (
            _MP_CTX.Process(target=jobrunner.run)
            if is_unix_system()
            else Thread(target=jobrunner.run)
        )

        process_id = (
            os.getpid() if is_unix_system() else mp.current_process().pid
        )
        sys_monitor = SystemMonitor(process_id)
        sys_monitor.start()

        jrp.start()

        # Reported once the process is running, which is also when the call
        # has really started. Sending it here rather than before the fork
        # keeps the one-off cost of opening the monitoring client off the
        # critical path: the first call of a worker pays for a connection
        # (some 13 ms for AMQP, then kept for the whole process) while the
        # function is already running, instead of delaying its start
        call_status.send_init_event()
        jrp.join(task.execution_timeout)

        sys_monitor.stop()
        logger.debug('JobRunner process finished')

        _add_resource_usage(call_status, sys_monitor)

        if jrp.is_alive():
            try:
                jrp.terminate()
            except Exception:
                # Where there is no fork the JobRunner is a thread, which
                # cannot be terminated. It is left behind on purpose
                pass
            raise TimeoutError(
                f'Function exceeded maximum time of {task.execution_timeout} '
                f'seconds and was killed'
            )

        if not handler_conn.poll():
            # The JobRunner sends exactly one message when it finishes, so
            # no message means it died before getting there. Its exit code
            # says why, and guessing at an out-of-memory kill regardless
            # sends whoever reads the error looking in the wrong place
            # A Thread stands in for the Process where there is no fork,
            # and it has no exit code to report
            exitcode = getattr(jrp, 'exitcode', None)
            reason = _jobrunner_death_reason(exitcode)
            logger.error(
                'No completion message received from the JobRunner '
                f'process, which exited with code {exitcode}: {reason}'
            )
            if _SIGKILL is not None and exitcode == -_SIGKILL:
                raise MemoryError(reason)
            raise RuntimeError(reason)

        _add_task_stats(call_status, task.stats_file)

    except KeyboardInterrupt:
        job_interrupted = True
        logger.debug("Job interrupted")

    except Exception:
        _add_exception(call_status)

    finally:
        for key in injected_env:
            os.environ.pop(key, None)

        # An interrupted job is not reported: the client is gone anyway
        if not job_interrupted:
            call_status.add('worker_end_tstamp', time.time())
            _add_logs(call_status, task)
            call_status.send_finish_event()

        logger.info("Finished")
