#
# (C) Copyright Cloudlab URV 2021
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
import json
import queue
import lithops
import logging
import threading
import subprocess as sp
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List

from lithops.constants import (
    TEMP_DIR,
    USER_TEMP_DIR,
    LITHOPS_TEMP_DIR,
    COMPUTE_CLI_MSG,
    JOBS_PREFIX,
    RN_LOG_FILE,
)
from lithops.utils import (
    BackendType,
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
    docker_pull_cmd,
    docker_rm_cmd,
    docker_run_cmd,
    kill_process,
    log_process_failure,
)

logger = logging.getLogger(__name__)

RUNNER_FILE = os.path.join(LITHOPS_TEMP_DIR, 'localhost-runner-v1.py')
LITHOPS_LOCATION = os.path.dirname(os.path.abspath(lithops.__file__))
# The local temp dir is mounted on /tmp, so this is where a container sees
# the runner that was copied to RUNNER_FILE. The name carries the version:
# v1 and v2 install a different runner, and a job of one started with the
# other's runner fails without saying why
DOCKER_RUNNER_FILE = f'/tmp/{USER_TEMP_DIR}/localhost-runner-v1.py'


class LocalhostHandlerV1:
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
        self.job_queue = queue.Queue()
        self.job_manager = None
        self.invocations_lock = threading.Lock()
        self.invocations_in_progress = 0

        logger.info(COMPUTE_CLI_MSG.format('Localhost compute v1'))

    def get_backend_type(self):
        """Returns the backend type, which is invoked with a whole job"""
        return BackendType.BATCH.value

    def init(self):
        """Creates and sets up the environment where the jobs will run"""
        if self.environment == LocalhostEnvironment.DEFAULT:
            self.env = DefaultEnvironment(self.config)
        else:
            self.env = ContainerEnvironment(self.config)
        self.env.setup()

    @property
    def invocation_in_progress(self) -> bool:
        """True while at least one invoke() is still queueing its job"""
        return self.invocations_in_progress > 0

    @contextmanager
    def _invocation(self):
        """
        Marks an invocation as in flight, so that the job manager does not
        stop while its job is still being queued
        """
        with self.invocations_lock:
            self.invocations_in_progress += 1
        try:
            yield
        finally:
            with self.invocations_lock:
                self.invocations_in_progress -= 1

    def _has_pending_work(self) -> bool:
        return self.invocation_in_progress or not self.job_queue.empty()

    def _run_queued_job(
        self, job_payload: Dict[str, Any], job_filename: str
    ) -> None:
        """
        Runs one job in the localhost worker and waits until it finishes, so
        that queued jobs run one after another
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        logger.debug(
            f'{log_prefix(executor_id, job_id)} - Running '
            f'{len(job_payload["call_ids"])} activations in the localhost worker'
        )

        process = self.env.run_job(job_payload['job_key'], job_filename)
        if process is None:
            logger.debug(
                f'{log_prefix(executor_id, job_id)} - Job was stopped '
                'before starting'
            )
            return
        stdout, stderr = process.communicate()

        if process.returncode > 0:
            log_process_failure(
                logger,
                f'{log_prefix(executor_id, job_id)} - Job process failed '
                f'with return code {process.returncode}',
                stdout=stdout,
                stderr=stderr,
                log_file=RN_LOG_FILE,
            )
        elif process.returncode < 0:
            logger.debug(
                f'{log_prefix(executor_id, job_id)} - Job process exited '
                f'with signal {-process.returncode}'
            )
        logger.debug(f'{log_prefix(executor_id, job_id)} - Execution finished')

    def start_manager(self):
        """
        Starts the thread that drains the job queue, unless it already runs
        """
        def job_manager():
            logger.debug('Starting localhost job manager')

            while True:
                job_payload, job_filename = self.job_queue.get()
                is_sentinel = job_payload is None and job_filename is None
                if not is_sentinel:
                    self._run_queued_job(job_payload, job_filename)

                # An invocation in flight is about to queue its job, so the
                # manager only stops once there is nothing left to run
                if not self._has_pending_work():
                    break

            self.job_manager = None
            logger.debug("Localhost job manager finished")

        if not self.job_manager:
            self.job_manager = threading.Thread(target=job_manager)
            self.job_manager.start()

    def deploy_runtime(self, runtime_name, *args):
        """Returns the metadata of the runtime, which needs no deployment"""
        logger.info(f"Deploying runtime: {runtime_name}")
        return self.env.get_metadata()

    def invoke(self, job_payload: Dict[str, Any]) -> None:
        """Queues a job and makes sure that the job manager is running"""
        with self._invocation():
            executor_id = job_payload['executor_id']
            job_id = job_payload['job_id']
            logger.debug(
                f'{log_prefix(executor_id, job_id)} - '
                'Putting job into localhost queue'
            )
            job_filename = self.env.prepare_job_file(job_payload)
            self.job_queue.put((job_payload, job_filename))
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
        Drops the given jobs if they have not started yet. Running ones
        are killed when the job ended in an exception, or when no job is
        named and the whole executor is going away; after a successful
        wait on a named job they are left to finish so their runner log
        stays in the file
        """
        self._drop_queued_jobs(job_keys)
        # See LocalhostHandlerV2.clear(): a named job that ended cleanly
        # keeps its runner log, an exception or a shutdown stops the job
        if exception is not None or job_keys is None:
            self.env.stop(job_keys)

        if self.job_manager:
            self.job_queue.put((None, None))

    def _drop_queued_jobs(self, job_keys=None) -> None:
        """
        Takes the given jobs out of the queue, putting back the ones that
        belong to jobs nobody asked to stop
        """
        kept = []
        while True:
            try:
                queued_job = self.job_queue.get(block=False)
            except queue.Empty:
                break
            job_payload, _ = queued_job
            # A sentinel only tells the manager to look at its work again,
            # and clear() queues a fresh one right after this
            if job_payload is None or job_keys is None:
                continue
            if job_payload['job_key'] not in job_keys:
                kept.append(queued_job)

        for queued_job in kept:
            self.job_queue.put(queued_job)


class ExecutionEnvironment:
    """Base environment class for shared methods."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.runtime_name = self.config['runtime']
        self.is_unix_system = is_unix_system()
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.stopped_jobs = set()

    def _copy_lithops_to_tmp(self):
        # A job invoked from inside a worker reuses the package that the
        # parent already copied, otherwise it would overwrite it while running
        if is_lithops_worker() and os.path.isfile(RUNNER_FILE):
            return
        copy_lithops_package(
            LITHOPS_LOCATION,
            os.path.join(LITHOPS_LOCATION, 'localhost', 'v1', 'runner.py'),
            RUNNER_FILE,
            LITHOPS_TEMP_DIR,
        )

    def _ensure_runner(self):
        if not os.path.isfile(RUNNER_FILE):
            self.setup()

    def prepare_job_file(self, job_payload: Dict[str, Any]) -> str:
        """
        Dumps the job payload where the runner will read it, and returns the
        path as the runner sees it
        """
        job_key = job_payload['job_key']
        with self.jobs_lock:
            self.stopped_jobs.discard(job_key)
        storage_backend = job_payload['config']['lithops']['storage']
        storage_bucket = job_payload['config'][storage_backend]['storage_bucket']

        local_job_dir = os.path.join(
            LITHOPS_TEMP_DIR, storage_bucket, JOBS_PREFIX
        )
        docker_job_dir = f'/tmp/{USER_TEMP_DIR}/{storage_bucket}/{JOBS_PREFIX}'
        job_file = f'{job_key}-job.json'

        os.makedirs(local_job_dir, exist_ok=True)
        local_job_filename = os.path.join(local_job_dir, job_file)

        with open(local_job_filename, 'w') as job_file_handle:
            json.dump(job_payload, job_file_handle, default=str)

        return self._job_file_for_runner(
            local_job_filename, f'{docker_job_dir}/{job_file}'
        )

    def _job_file_for_runner(self, local_path: str, container_path: str) -> str:
        """
        Returns the path the runner reads the job file from, which by default
        is where it was written
        """
        return local_path

    def _start_job_process(self, job_key: str, cmd: List[str]):
        """
        Starts the process that runs a whole job and registers it as one step,
        so that a stop() running right now either kills this process or keeps
        it from being started at all. Returns None in the latter case
        """
        with self.jobs_lock:
            if job_key in self.stopped_jobs:
                logger.debug(f'Job {job_key} not started, it was stopped')
                return None
            process = sp.Popen(
                cmd,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
                start_new_session=True,
            )
            self.jobs[job_key] = process
            return process

    def stop(self, job_keys=None):
        """Kills the job processes that are still running"""
        to_delete = job_keys or list(self.jobs.keys())
        with self.jobs_lock:
            # Marked before the sweep, so that a job about to start is not
            # left running behind it
            self.stopped_jobs.update(to_delete)
            for job_key in to_delete:
                try:
                    if job_key not in self.jobs:
                        continue
                    process = self.jobs[job_key]
                    logger.debug(
                        f'Killing job {job_key} with PID {process.pid}'
                    )
                    kill_process(process, self.is_unix_system)
                    del self.jobs[job_key]
                except Exception:
                    pass


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

    def run_job(self, job_key: str, job_filename: str):
        """Starts the runner that executes the whole job, and returns it"""
        self._ensure_runner()

        return self._start_job_process(
            job_key,
            [self.runtime_name, RUNNER_FILE, 'run_job', job_filename],
        )


class ContainerEnvironment(ExecutionEnvironment):
    """Container environment uses a container runtime image."""

    def _job_file_for_runner(self, local_path: str, container_path: str) -> str:
        """The container sees the local temp dir mounted on /tmp"""
        return container_path

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        logger.debug(f'Starting container environment for {self.runtime_name}')
        self.use_gpu = self.config.get('use_gpu', False)
        self.docker_path = get_docker_path()
        self.is_podman = is_podman(self.docker_path)
        self.uid = os.getuid() if self.is_unix_system else None
        self.gid = os.getgid() if self.is_unix_system else None

    def _container_cmd(self, name, container_args, use_gpu=False) -> List[str]:
        return docker_run_cmd(
            self.docker_path,
            self.runtime_name,
            name=name,
            tmp_path=Path(TEMP_DIR).as_posix(),
            uid=self.uid,
            gid=self.gid,
            is_podman=self.is_podman,
            use_gpu=use_gpu,
            container_args=container_args,
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
            self._container_cmd(
                'lithops_metadata', [DOCKER_RUNNER_FILE, 'get_metadata']
            ),
            check=True,
            stdout=sp.PIPE,
            universal_newlines=True,
            start_new_session=True,
        )
        return json.loads(process.stdout.strip())

    def run_job(self, job_key: str, job_filename: str):
        """
        Starts a container that executes the whole job, and returns the
        process that runs it
        """
        self._ensure_runner()

        return self._start_job_process(
            job_key,
            self._container_cmd(
                f'lithops_{job_key}',
                [DOCKER_RUNNER_FILE, 'run_job', job_filename],
                use_gpu=self.use_gpu,
            ),
        )

    def stop(self, job_keys=None):
        """Removes the job containers and kills the processes behind them"""
        for job_key in job_keys or list(self.jobs.keys()):
            sp.Popen(
                docker_rm_cmd(self.docker_path, f'lithops_{job_key}'),
                stdout=sp.DEVNULL,
                stderr=sp.DEVNULL,
            )
        super().stop(job_keys)
