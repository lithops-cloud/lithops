#
# (C) Copyright IBM Corp. 2023
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

import copy
import os
import json
import threading
import time
import uuid
import lithops
import logging
import queue
import subprocess as sp
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List

from lithops.constants import (
    JOBS_DIR,
    TEMP_DIR,
    LITHOPS_TEMP_DIR,
    COMPUTE_CLI_MSG,
    CPU_COUNT,
    USER_TEMP_DIR,
    RN_LOG_FILE,
)
from lithops.utils import (
    BackendType,
    CountDownLatch,
    get_docker_path,
    is_lithops_worker,
    is_podman,
    is_unix_system,
    log_prefix,
)
from lithops.localhost.config import (
    LocalhostEnvironment,
    get_environment,
    runtime_info,
    runtime_key,
)
from lithops.localhost.utils import (
    copy_lithops_package,
    docker_exec_python_cmd,
    docker_pull_cmd,
    docker_rm_cmd,
    docker_run_cmd,
    kill_process,
    log_process_failure,
)

logger = logging.getLogger(__name__)

RUNNER_FILE = os.path.join(LITHOPS_TEMP_DIR, 'localhost-runner.py')
LITHOPS_LOCATION = os.path.dirname(os.path.abspath(lithops.__file__))
# The local temp dir is mounted on /tmp, so this is where a container sees the
# runner that was copied to RUNNER_FILE
DOCKER_RUNNER_FILE = f'/tmp/{USER_TEMP_DIR}/localhost-runner.py'
# How long the job manager waits before looking again for the latch of
# a job that is being invoked right now
MANAGER_IDLE_WAIT = 0.1


class LocalhostHandlerV2:
    """
    A LocalhostHandler object is used by invokers and other components to
    access the underlying localhost backend without exposing implementation
    details.
    """

    def __init__(self, config: Dict[str, Any]):
        logger.debug('Creating Localhost compute client')
        self.config = config
        self.runtime_name = self.config['runtime']
        self.environment = get_environment(self.runtime_name)

        self.env = None
        self.job_manager = None
        self.invocations_lock = threading.Lock()
        self.invocations_in_progress = 0

        logger.info(COMPUTE_CLI_MSG.format('Localhost compute v2'))

    @property
    def invocation_in_progress(self) -> bool:
        """True while at least one invoke() is still queueing its tasks"""
        return self.invocations_in_progress > 0

    @contextmanager
    def _invocation(self):
        """
        Marks an invocation as in flight, so that the job manager does not
        stop while its tasks are still being queued
        """
        with self.invocations_lock:
            self.invocations_in_progress += 1
        try:
            yield
        finally:
            with self.invocations_lock:
                self.invocations_in_progress -= 1

    def get_backend_type(self):
        """Returns the backend type, which is invoked with a whole job"""
        return BackendType.BATCH.value

    def init(self):
        """Creates and sets up the environment where the tasks will run"""
        if self.environment == LocalhostEnvironment.DEFAULT:
            self.env = DefaultEnvironment(self.config)
        else:
            self.env = ContainerEnvironment(self.config)
        self.env.setup()

    def start_manager(self):
        """
        Starts the thread that waits for the running jobs, and the consumers
        that execute their tasks, unless they are already running
        """
        def job_manager():
            logger.debug('Starting localhost job manager')

            while True:
                for job_key in list(self.env.jobs.keys()):
                    self.env.jobs[job_key].wait()
                # A new job may have been invoked while waiting for the
                # previous ones, so only stop once every latch is down
                if all(job.done for job in list(self.env.jobs.values())):
                    if self.invocation_in_progress:
                        # An invoke() is queueing its tasks right now, so
                        # wait for its latch to show up instead of spinning
                        time.sleep(MANAGER_IDLE_WAIT)
                        continue
                    break

            self.job_manager = None
            logger.debug("Localhost job manager finished")

        if not self.job_manager:
            self.job_manager = threading.Thread(target=job_manager)
            self.job_manager.start()
            self.env.start()

    def deploy_runtime(self, runtime_name, *args):
        """Returns the metadata of the runtime, which needs no deployment"""
        logger.info(f"Deploying runtime: {runtime_name}")
        return self.env.get_metadata()

    def invoke(self, job_payload: Dict[str, Any]) -> None:
        """Queues the tasks of a job and makes sure the consumers are up"""
        with self._invocation():
            executor_id = job_payload['executor_id']
            job_id = job_payload['job_id']
            logger.debug(
                f'{log_prefix(executor_id, job_id)} - Running '
                f'{len(job_payload["call_ids"])} activations in the localhost '
                f'worker'
            )
            self.env.run_job(job_payload)
            self.start_manager()

    def get_runtime_key(self, runtime_name, *args):
        """Returns the key the runtime metadata is cached under"""
        return runtime_key(runtime_name)

    def get_runtime_info(self):
        """Returns the runtime limits the executor reports to the user"""
        return runtime_info(self.config)

    def clean(self, **kwargs):
        """Nothing to clean up: the localhost backend deploys nothing"""
        pass

    def clear(self, job_keys=None, exception=None):
        """
        Drops the tasks of the given jobs that have not started yet, kills the
        running ones and releases their latches so that the job manager can
        finish. Jobs that were not named are left running
        """
        self.env.drop_pending_tasks(job_keys)
        self.env.stop(job_keys)

        for job_key in list(self.env.jobs.keys()):
            if job_keys is not None and job_key not in job_keys:
                continue
            while not self.env.jobs[job_key].done:
                self.env.jobs[job_key].unlock()


class ExecutionEnvironment:
    """Base environment class for shared methods."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.runtime_name = self.config['runtime']
        self.worker_processes = self.config.get('worker_processes', CPU_COUNT)
        self.work_queue = queue.Queue()
        self.is_unix_system = is_unix_system()
        self.task_processes = {}
        self.task_processes_lock = threading.Lock()
        self.stopped_jobs = set()
        self.consumer_threads = []
        self.jobs = {}

    def _copy_lithops_to_tmp(self):
        # A task invoked from inside a worker reuses the package that the
        # parent already copied, otherwise it would overwrite it while running
        if is_lithops_worker() and os.path.isfile(RUNNER_FILE):
            return
        copy_lithops_package(
            LITHOPS_LOCATION,
            os.path.join(LITHOPS_LOCATION, 'localhost', 'v2', 'runner.py'),
            RUNNER_FILE,
            LITHOPS_TEMP_DIR,
        )

    def _ensure_runner(self):
        if not os.path.isfile(RUNNER_FILE):
            self.setup()

    def _run_task_process(self, job_key_call_id: str, cmd: List[str]) -> None:
        """
        Runs one task in a subprocess and waits for it, reporting whatever it
        printed if it failed
        """
        logger.debug(f"Going to execute task process {job_key_call_id}")
        # Started and registered as one step, so that a stop() running right
        # now either kills this process or stops it from being started at all
        with self.task_processes_lock:
            if job_key_call_id.rsplit('-', 1)[0] in self.stopped_jobs:
                logger.debug(
                    f"Task process {job_key_call_id} not started, its job "
                    f"was stopped"
                )
                return
            process = sp.Popen(
                cmd,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
                start_new_session=True,
            )
            self.task_processes[job_key_call_id] = process

        stdout, stderr = process.communicate()

        if process.returncode != 0:
            log_process_failure(
                logger,
                f"Task process {job_key_call_id} failed with return "
                f"code {process.returncode}",
                stdout=stdout,
                stderr=stderr,
                log_file=RN_LOG_FILE,
            )
        self.task_processes.pop(job_key_call_id, None)
        logger.debug(f"Task process {job_key_call_id} finished")

    def run_job(self, job_payload: Dict[str, Any]) -> None:
        """
        Splits a job into one queued task per call, each one carrying only the
        data range of its own call
        """
        job_key = job_payload['job_key']
        self.jobs[job_key] = CountDownLatch(len(job_payload['call_ids']))
        os.makedirs(os.path.join(JOBS_DIR, job_key), exist_ok=True)

        dbr = job_payload['data_byte_ranges']
        with self.task_processes_lock:
            self.stopped_jobs.discard(job_payload['job_key'])
        for call_id in job_payload['call_ids']:
            task_payload = copy.deepcopy(job_payload)
            task_payload['call_ids'] = [call_id]
            task_payload['data_byte_ranges'] = [dbr[int(call_id)]]
            self.work_queue.put(json.dumps(task_payload))

    def _process_task(self, task_payload_str: str) -> None:
        """
        Dumps a queued task where the runner will read it, runs it and counts
        it down on its job latch
        """
        task_payload = json.loads(task_payload_str)
        job_key = task_payload['job_key']
        call_id = task_payload['call_ids'][0]

        task_filename = os.path.join(JOBS_DIR, job_key, call_id + '.task')
        with open(task_filename, 'w') as task_file:
            json.dump(task_payload, task_file, default=str)

        self.run_task(job_key, call_id)

        if os.path.exists(task_filename):
            os.remove(task_filename)

        self.jobs[job_key].unlock()

    def _queue_consumer(self) -> None:
        while True:
            task_payload_str = self.work_queue.get()
            if task_payload_str is None:
                break
            self._process_task(task_payload_str)

    def start(self):
        """Starts the consumer threads that run the queued tasks"""
        if self.consumer_threads:
            return

        logger.debug("Starting Localhost work queue consumer threads")
        for _ in range(self.worker_processes):
            thread = threading.Thread(target=self._queue_consumer, daemon=True)
            thread.start()
            self.consumer_threads.append(thread)

    def drop_pending_tasks(self, job_keys=None) -> None:
        """
        Takes the queued tasks of the given jobs out of the work queue, and
        puts back the ones belonging to jobs nobody asked to stop
        """
        kept = []
        while True:
            try:
                task_payload_str = self.work_queue.get(block=False)
            except queue.Empty:
                break
            # A sentinel left behind by an earlier stop() would kill the next
            # consumer that starts, so it never goes back into the queue
            if task_payload_str is None or job_keys is None:
                continue
            if json.loads(task_payload_str)['job_key'] not in job_keys:
                kept.append(task_payload_str)

        for task_payload_str in kept:
            self.work_queue.put(task_payload_str)

    def stop(self, job_keys=None):
        """
        Kills the task processes of the given jobs, and stops the environment
        unless jobs other than those are still to run
        """
        self._kill_task_processes(job_keys or list(self.jobs.keys()))

        if job_keys is not None and self._has_jobs_left(job_keys):
            logger.debug(
                "Localhost environment left running, it still has jobs to run"
            )
            return

        self._teardown()

    def _has_jobs_left(self, stopped_job_keys) -> bool:
        """Tells whether a job other than the stopped ones is still running"""
        return any(
            not latch.done
            for job_key, latch in list(self.jobs.items())
            if job_key not in stopped_job_keys
        )

    def _kill_task_processes(self, job_keys) -> None:
        """Kills the task processes of the given jobs"""
        with self.task_processes_lock:
            # Marked before the sweep, so that a task about to start is not
            # left running behind it
            self.stopped_jobs.update(job_keys)
            for job_key in job_keys:
                for job_key_call_id in list(self.task_processes.keys()):
                    if job_key_call_id.rsplit('-', 1)[0] != job_key:
                        continue
                    process = self.task_processes.pop(job_key_call_id, None)
                    if process is None:
                        continue
                    try:
                        kill_process(process, self.is_unix_system)
                    except Exception:
                        pass

    def _teardown(self) -> None:
        """Stops the consumer threads, leaving the environment idle"""
        if not self.consumer_threads:
            return

        logger.debug("Stopping Localhost work queue consumer threads")
        # One sentinel per running consumer, no more: one that nobody takes
        # stays in the queue and kills the next consumer that starts
        for _ in self.consumer_threads:
            self.work_queue.put(None)

        for thread in self.consumer_threads:
            thread.join()

        self.consumer_threads = []


class DefaultEnvironment(ExecutionEnvironment):
    """Default environment uses the current Python installation."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        logger.debug(f'Starting default environment for {self.runtime_name}')

    def setup(self):
        """Installs the Lithops package and the runner in the temp dir"""
        logger.debug('Setting up default environment')
        self._copy_lithops_to_tmp()

    def get_metadata(self):
        """Asks the local interpreter for the packages it has installed"""
        self._ensure_runner()

        logger.debug(f"Extracting metadata from: {self.runtime_name}")
        process = sp.run(
            [self.runtime_name, RUNNER_FILE, 'get_metadata'],
            check=True,
            stdout=sp.PIPE,
            universal_newlines=True,
            start_new_session=True,
        )
        return json.loads(process.stdout.strip())

    def start(self):
        """Starts the consumer threads, with the runner in place"""
        self._ensure_runner()
        super().start()

    def run_task(self, job_key: str, call_id: str) -> None:
        """Runs one task in a subprocess of the local interpreter"""
        task_filename = os.path.join(JOBS_DIR, job_key, call_id + '.task')
        self._run_task_process(
            f'{job_key}-{call_id}',
            [self.runtime_name, RUNNER_FILE, 'run_job', task_filename],
        )


class ContainerEnvironment(ExecutionEnvironment):
    """Container environment uses a container runtime image."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        logger.debug(f'Starting container environment for {self.runtime_name}')
        self.use_gpu = self.config.get('use_gpu', False)
        self.docker_path = get_docker_path()
        self.is_podman = is_podman(self.docker_path)
        self.container_name = "lithops_" + str(uuid.uuid4()).replace('-', '')[:12]
        self.container_process = None
        self.uid = os.getuid() if self.is_unix_system else None
        self.gid = os.getgid() if self.is_unix_system else None

    def _container_run_cmd(self, name, *, use_gpu=False, **kwargs) -> List[str]:
        return docker_run_cmd(
            self.docker_path,
            self.runtime_name,
            name=name,
            tmp_path=Path(TEMP_DIR).as_posix(),
            uid=self.uid,
            gid=self.gid,
            is_podman=self.is_podman,
            use_gpu=use_gpu,
            **kwargs,
        )

    def setup(self):
        """Installs the runner in the temp dir and pulls the image if asked"""
        logger.debug('Setting up container environment')
        self._copy_lithops_to_tmp()
        if self.config.get('pull_runtime', False):
            logger.debug(f'Pulling runtime {self.runtime_name}')
            sp.run(
                docker_pull_cmd(self.docker_path, self.runtime_name),
                check=True,
                stdout=sp.PIPE,
                universal_newlines=True,
            )

    def get_metadata(self):
        """Asks the runtime image for the packages it has installed"""
        self._ensure_runner()

        logger.debug(f"Extracting metadata from: {self.runtime_name}")
        process = sp.run(
            self._container_run_cmd(
                'lithops_metadata',
                container_args=[DOCKER_RUNNER_FILE, 'get_metadata'],
            ),
            check=True,
            stdout=sp.PIPE,
            universal_newlines=True,
            start_new_session=True,
        )
        return json.loads(process.stdout.strip())

    def start(self):
        """
        Starts the container that will run every task of this executor, and
        the consumer threads that feed it through docker exec
        """
        self._ensure_runner()

        self.container_process = sp.Popen(
            self._container_run_cmd(
                self.container_name,
                extra_run_args=['-it', '--detach'],
                entrypoint='/bin/bash',
                use_gpu=self.use_gpu,
            ),
            stdout=sp.DEVNULL,
            start_new_session=True,
        )
        self.container_process.communicate()
        super().start()

    def run_task(self, job_key: str, call_id: str) -> None:
        """Runs one task inside the already running container"""
        docker_task_filename = (
            f'/tmp/{USER_TEMP_DIR}/jobs/{job_key}/{call_id}.task'
        )
        self._run_task_process(
            f'{job_key}-{call_id}',
            docker_exec_python_cmd(
                self.docker_path,
                self.container_name,
                DOCKER_RUNNER_FILE,
                'run_job',
                docker_task_filename,
            ),
        )

    def _teardown(self) -> None:
        """Removes the container along with the consumer threads"""
        sp.Popen(
            docker_rm_cmd(self.docker_path, self.container_name),
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
        )
        super()._teardown()
