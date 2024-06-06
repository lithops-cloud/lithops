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
import uuid
import shlex
import signal
import lithops
import logging
import shutil
import queue
import subprocess as sp
from shutil import copyfile
from pathlib import Path

from lithops.version import __version__
from lithops.constants import (
    JOBS_DIR,
    TEMP_DIR,
    LITHOPS_TEMP_DIR,
    COMPUTE_CLI_MSG,
    CPU_COUNT,
    USER_TEMP_DIR,
)
from lithops.utils import (
    BackendType,
    CountDownLatch,
    get_docker_path,
    is_lithops_worker,
    is_podman,
    is_unix_system
)
from lithops.localhost.config import (
    LocvalhostEnvironment,
    get_environment
)

logger = logging.getLogger(__name__)

RUNNER_FILE = os.path.join(LITHOPS_TEMP_DIR, 'localhost-runner.py')
LITHOPS_LOCATION = os.path.dirname(os.path.abspath(lithops.__file__))


class LocalhostHandlerV2:
    """
    A localhostHandler object is used by invokers and other components to
    access underlying localhost backend without exposing the implementation
    details.
    """

    def __init__(self, localhost_config):
        logger.debug('Creating Localhost compute client')
        self.config = localhost_config
        self.runtime_name = self.config['runtime']
        self.environment = get_environment(self.runtime_name)

        self.env = None
        self.job_manager = None
        self.invocation_in_progress = False

        msg = COMPUTE_CLI_MSG.format('Localhost compute v2')
        logger.info(f"{msg}")

    def get_backend_type(self):
        """
        Wrapper method that returns the type of the backend (Batch or FaaS)
        """
        return BackendType.BATCH.value

    def init(self):
        """
        Init tasks for localhost
        """
        if self.environment == LocvalhostEnvironment.DEFAULT:
            self.env = DefaultEnvironment(self.config)
        else:
            self.env = ContainerEnvironment(self.config)

        self.env.setup()

    def start_manager(self):
        """
        Starts manager thread to keep order in tasks
        """
        def job_manager():
            logger.debug('Staring localhost job manager')

            while True:
                for job_key in list(self.env.jobs.keys()):
                    self.env.jobs[job_key].wait()
                if all(job.done for job in self.env.jobs.values()):
                    if self.invocation_in_progress:
                        continue
                    else:
                        break

            self.job_manager = None
            logger.debug("Localhost job manager finished")

        if not self.job_manager:
            self.job_manager = threading.Thread(target=job_manager)
            self.job_manager.start()
            self.env.start()

    def deploy_runtime(self, runtime_name, *args):
        """
        Extract the runtime metadata and preinstalled modules
        """
        logger.info(f"Deploying runtime: {runtime_name}")
        return self.env.get_metadata()

    def invoke(self, job_payload):
        """
        Run the job description against the selected environment
        """
        self.invocation_in_progress = True
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        total_calls = len(job_payload['call_ids'])

        logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Running '
                     f'{total_calls} activations in the localhost worker')

        self.env.run_job(job_payload)

        self.start_manager()
        self.invocation_in_progress = False

    def get_runtime_key(self, runtime_name, *args):
        """
        Generate the runtime key that identifies the runtime
        """
        runtime_key = os.path.join('localhost', __version__, runtime_name.strip("/"))

        return runtime_key

    def get_runtime_info(self):
        """
        Method that returns a dictionary with all the relevant runtime
        information set in config
        """
        return {
            'runtime_name': self.config['runtime'],
            'runtime_memory': self.config.get('runtime_memory'),
            'runtime_timeout': self.config.get('runtime_timeout'),
            'max_workers': self.config['max_workers'],
        }

    def clean(self, **kwargs):
        """
        Deletes all local runtimes
        """
        pass

    def clear(self, job_keys=None, exception=None):
        """
        Kills the running service in case of exception
        """
        while not self.env.work_queue.empty():
            try:
                self.env.work_queue.get(False)
            except Exception:
                pass

        self.env.stop(job_keys)

        for job_key in list(self.env.jobs.keys()):
            while not self.env.jobs[job_key].done:
                self.env.jobs[job_key].unlock()


class ExecutionEnvironment:
    """
    Base environment class for shared methods
    """

    def __init__(self, config):
        self.config = config
        self.runtime_name = self.config['runtime']
        self.worker_processes = self.config.get('worker_processes', CPU_COUNT)
        self.work_queue = queue.Queue()
        self.is_unix_system = is_unix_system()
        self.task_processes = {}
        self.consumer_threads = []
        self.jobs = {}

    def _copy_lithops_to_tmp(self):
        if is_lithops_worker() and os.path.isfile(RUNNER_FILE):
            return
        os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
        shutil.rmtree(os.path.join(LITHOPS_TEMP_DIR, 'lithops'), ignore_errors=True)
        shutil.copytree(LITHOPS_LOCATION, os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        src_handler = os.path.join(LITHOPS_LOCATION, 'localhost', 'v2', 'runner.py')
        copyfile(src_handler, RUNNER_FILE)

    def run_job(self, job_payload):
        """
        Adds a job to the localhost work queue
        """
        job_key = job_payload['job_key']
        self.jobs[job_key] = CountDownLatch(len(job_payload['call_ids']))
        os.makedirs(os.path.join(JOBS_DIR, job_key), exist_ok=True)

        dbr = job_payload['data_byte_ranges']
        for call_id in job_payload['call_ids']:
            task_payload = copy.deepcopy(job_payload)
            task_payload['call_ids'] = [call_id]
            task_payload['data_byte_ranges'] = [dbr[int(call_id)]]
            self.work_queue.put(json.dumps(task_payload))

    def start(self):
        """
        Starts the threads responsible to consume individual tasks from the queue
        and execute them in the appropiate environment
        """
        if self.consumer_threads:
            return

        def process_task(task_payload_str):
            task_payload = json.loads(task_payload_str)
            job_key = task_payload['job_key']
            call_id = task_payload['call_ids'][0]

            task_filename = os.path.join(JOBS_DIR, job_key, call_id + '.task')
            with open(task_filename, 'w') as jl:
                json.dump(task_payload, jl, default=str)

            self.run_task(job_key, call_id)

            if os.path.exists(task_filename):
                os.remove(task_filename)

            self.jobs[job_key].unlock()

        def queue_consumer(work_queue):
            while True:
                task_payload_str = work_queue.get()
                if task_payload_str is None:
                    break
                process_task(task_payload_str)

        logger.debug("Starting Localhost work queue consumer threads")
        for _ in range(self.worker_processes):
            t = threading.Thread(
                target=queue_consumer,
                args=(self.work_queue,),
                daemon=True)
            t.start()
            self.consumer_threads.append(t)

    def stop(self, job_keys=None):
        """
        Stops running consumer threads
        """
        logger.debug("Stopping Localhost work queue consumer threads")
        for _ in range(self.worker_processes):
            self.work_queue.put(None)

        for t in self.consumer_threads:
            t.join()

        self.consumer_threads = []


class DefaultEnvironment(ExecutionEnvironment):
    """
    Default environment uses current python3 installation
    """

    def __init__(self, config):
        super().__init__(config)
        logger.debug(f'Starting default environment for {self.runtime_name}')

    def setup(self):
        logger.debug('Setting up default environment')
        self._copy_lithops_to_tmp()

    def get_metadata(self):
        if not os.path.isfile(RUNNER_FILE):
            self.setup()

        logger.debug(f"Extracting metadata from: {self.runtime_name}")
        cmd = [self.runtime_name, RUNNER_FILE, 'get_metadata']
        process = sp.run(
            cmd, check=True,
            stdout=sp.PIPE,
            universal_newlines=True,
            start_new_session=True
        )
        runtime_meta = json.loads(process.stdout.strip())
        return runtime_meta

    def start(self):
        if not os.path.isfile(RUNNER_FILE):
            self.setup()

        super().start()

    def run_task(self, job_key, call_id):
        """
        Runs a task
        """
        job_key_call_id = f'{job_key}-{call_id}'
        task_filename = os.path.join(JOBS_DIR, job_key, call_id + '.task')

        logger.debug(f"Going to execute task process {job_key_call_id}")
        cmd = [self.runtime_name, RUNNER_FILE, 'run_job', task_filename]
        process = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.PIPE, start_new_session=True)
        self.task_processes[job_key_call_id] = process
        process.communicate()  # blocks until the process finishes
        if process.returncode != 0:
            logger.error(f"Task process {job_key_call_id} failed with return code {process.returncode}")
        del self.task_processes[job_key_call_id]
        logger.debug(f"Task process {job_key_call_id} finished")

    def stop(self, job_keys=None):
        """
        Stops running processes
        """
        def kill_process(process):
            if process and process.poll() is None:
                PID = process.pid
                if self.is_unix_system:
                    PGID = os.getpgid(PID)
                    os.killpg(PGID, signal.SIGKILL)
                else:
                    os.kill(PID, signal.SIGTERM)

        job_keys_to_stop = job_keys or list(self.jobs.keys())
        for job_key in job_keys_to_stop:
            for job_key_call_id in list(self.task_processes.keys()):
                if job_key_call_id.rsplit('-', 1)[0] == job_key:
                    process = self.task_processes[job_key_call_id]
                    try:
                        kill_process(process)
                    except Exception:
                        pass
                    self.task_processes[job_key_call_id] = None

        super().stop(job_keys)


class ContainerEnvironment(ExecutionEnvironment):
    """
    Container environment uses a container runtime image
    """

    def __init__(self, config):
        super().__init__(config)
        logger.debug(f'Starting container environment for {self.runtime_name}')
        self.use_gpu = self.config.get('use_gpu', False)
        self.docker_path = get_docker_path()
        self.is_podman = is_podman(self.docker_path)
        self.container_name = "lithops_" + str(uuid.uuid4()).replace('-', '')[:12]
        self.container_process = None
        self.uid = os.getuid() if self.is_unix_system else None
        self.gid = os.getgid() if self.is_unix_system else None

    def setup(self):
        logger.debug('Setting up container environment')
        self._copy_lithops_to_tmp()

        if self.config.get('pull_runtime', False):
            logger.debug(f'Pulling runtime {self.runtime_name}')
            sp.run(
                shlex.split(f'{self.docker_path} pull {self.runtime_name}'),
                check=True, stdout=sp.PIPE, universal_newlines=True
            )

    def get_metadata(self):
        if not os.path.isfile(RUNNER_FILE):
            self.setup()

        logger.debug(f"Extracting metadata from: {self.runtime_name}")

        tmp_path = Path(TEMP_DIR).as_posix()

        cmd = f'{self.docker_path} run --name lithops_metadata '
        cmd += f'--user {self.uid}:{self.gid} ' if self.is_unix_system and not self.is_podman else ''
        cmd += f'--env USER={os.getenv("USER", "root")} '
        cmd += f'--rm -v {tmp_path}:/tmp --entrypoint "python3" '
        cmd += f'{self.runtime_name} /tmp/{USER_TEMP_DIR}/localhost-runner.py get_metadata'

        process = sp.run(
            shlex.split(cmd), check=True, stdout=sp.PIPE,
            universal_newlines=True, start_new_session=True
        )
        runtime_meta = json.loads(process.stdout.strip())

        return runtime_meta

    def start(self):
        if not os.path.isfile(RUNNER_FILE):
            self.setup()

        tmp_path = Path(TEMP_DIR).as_posix()

        cmd = f'{self.docker_path} run --name {self.container_name} '
        cmd += '--gpus all ' if self.use_gpu else ''
        cmd += f'--user {self.uid}:{self.gid} ' if self.is_unix_system and not self.is_podman else ''
        cmd += f'--env USER={os.getenv("USER", "root")} '
        cmd += f'--rm -v {tmp_path}:/tmp -it --detach '
        cmd += f'--entrypoint=/bin/bash {self.runtime_name}'

        self.container_process = sp.Popen(shlex.split(cmd), stdout=sp.DEVNULL, start_new_session=True)
        self.container_process.communicate()  # blocks until the process finishes

        super().start()

    def run_task(self, job_key, call_id):
        """
        Runs a task
        """
        job_key_call_id = f'{job_key}-{call_id}'
        docker_job_dir = f'/tmp/{USER_TEMP_DIR}/jobs/{job_key}'
        docker_task_filename = f'{docker_job_dir}/{call_id}.task'

        logger.debug(f"Going to execute task process {job_key_call_id}")
        cmd = f'{self.docker_path} exec {self.container_name} /bin/bash -c '
        cmd += f'"python3 /tmp/{USER_TEMP_DIR}/localhost-runner.py '
        cmd += f'run_job {docker_task_filename}"'

        process = sp.Popen(shlex.split(cmd), stdout=sp.PIPE, stderr=sp.PIPE, start_new_session=True)
        self.task_processes[job_key_call_id] = process
        process.communicate()  # blocks until the process finishes
        if process.returncode != 0:
            logger.error(f"Task process {job_key_call_id} failed with return code {process.returncode}")
        logger.debug(f"Task process {job_key_call_id} finished")

    def stop(self, job_keys=None):
        """
        Stop localhost container
        """
        sp.Popen(
            shlex.split(f'{self.docker_path} rm -f {self.container_name}'),
            stdout=sp.DEVNULL, stderr=sp.DEVNULL
        )
        super().stop(job_keys)
