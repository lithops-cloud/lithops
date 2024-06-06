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
import shlex
import queue
import signal
import lithops
import logging
import shutil
import threading
import subprocess as sp
from shutil import copyfile
from pathlib import Path

from lithops.version import __version__
from lithops.constants import (
    TEMP_DIR,
    USER_TEMP_DIR,
    LITHOPS_TEMP_DIR,
    COMPUTE_CLI_MSG,
    JOBS_PREFIX
)
from lithops.utils import (
    BackendType,
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


class LocalhostHandlerV1:
    """
    A localhostHandler object is used by invokers and other components to access
    underlying localhost backend without exposing the implementation details.
    """

    def __init__(self, config):
        logger.debug('Creating Localhost compute client')
        self.config = config
        self.runtime_name = self.config['runtime']
        self.environment = get_environment(self.runtime_name)

        self.env = None
        self.job_queue = queue.Queue()
        self.job_manager = None
        self.invocation_in_progress = False

        msg = COMPUTE_CLI_MSG.format('Localhost compute v1')
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
                job_payload, job_filename = self.job_queue.get()

                if job_payload is None and job_filename is None:
                    if self.invocation_in_progress or not self.job_queue.empty():
                        continue
                    else:
                        break

                executor_id = job_payload['executor_id']
                job_id = job_payload['job_id']
                total_calls = len(job_payload['call_ids'])
                job_key = job_payload['job_key']
                logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Running '
                             f'{total_calls} activations in the localhost worker')
                process = self.env.run_job(job_key, job_filename)
                process.communicate()  # blocks until the process finishes
                if process.returncode != 0:
                    logger.error(f"ExecutorID {executor_id} | JobID {job_id} - Job "
                                 f"process failed with return code {process.returncode}")
                logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Execution finished')

                if self.job_queue.empty():
                    if self.invocation_in_progress:
                        continue
                    else:
                        break

            self.job_manager = None
            logger.debug("Localhost job manager finished")

        if not self.job_manager:
            self.job_manager = threading.Thread(target=job_manager)
            self.job_manager.start()

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

        logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Putting job into localhost queue')

        job_filename = self.env.prepare_job_file(job_payload)
        self.job_queue.put((job_payload, job_filename))

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
        Method that returns a dictionary with all the relevant runtime information
        set in config
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
        Kills all running jobs processes
        """
        while not self.job_queue.empty():
            try:
                self.job_queue.get(False)
            except Exception:
                pass

        self.env.stop(job_keys)

        if self.job_manager:
            self.job_queue.put((None, None))


class ExecutionEnvironment:
    """
    Base environment class for shared methods
    """

    def __init__(self, config):
        self.config = config
        self.runtime_name = self.config['runtime']
        self.is_unix_system = is_unix_system()
        self.jobs = {}  # dict to store executed jobs (job_keys) and PIDs

    def _copy_lithops_to_tmp(self):
        if is_lithops_worker() and os.path.isfile(RUNNER_FILE):
            return
        os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
        shutil.rmtree(os.path.join(LITHOPS_TEMP_DIR, 'lithops'), ignore_errors=True)
        shutil.copytree(LITHOPS_LOCATION, os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        src_handler = os.path.join(LITHOPS_LOCATION, 'localhost', 'v1', 'runner.py')
        copyfile(src_handler, RUNNER_FILE)

    def prepare_job_file(self, job_payload):
        """
        Creates the job file that contains the job payload to be executed
        """
        job_key = job_payload['job_key']
        storage_backend = job_payload['config']['lithops']['storage']
        storage_bucket = job_payload['config'][storage_backend]['storage_bucket']

        local_job_dir = os.path.join(LITHOPS_TEMP_DIR, storage_bucket, JOBS_PREFIX)
        docker_job_dir = f'/tmp/{USER_TEMP_DIR}/{storage_bucket}/{JOBS_PREFIX}'
        job_file = f'{job_key}-job.json'

        os.makedirs(local_job_dir, exist_ok=True)
        local_job_filename = os.path.join(local_job_dir, job_file)

        with open(local_job_filename, 'w') as jl:
            json.dump(job_payload, jl, default=str)

        if isinstance(self, ContainerEnvironment):
            job_filename = f'{docker_job_dir}/{job_file}'
        else:
            job_filename = local_job_filename

        return job_filename

    def stop(self, job_keys=None):
        """
        Stops running processes
        """

        def kill_job(job_key):
            if self.jobs[job_key].poll() is None:
                logger.debug(f'Killing job {job_key} with PID {self.jobs[job_key].pid}')
                PID = self.jobs[job_key].pid
                if self.is_unix_system:
                    PGID = os.getpgid(PID)
                    os.killpg(PGID, signal.SIGKILL)
                else:
                    os.kill(PID, signal.SIGTERM)
            del self.jobs[job_key]

        to_delete = job_keys or list(self.jobs.keys())
        for job_key in to_delete:
            try:
                if job_key in self.jobs:
                    kill_job(job_key)
            except Exception:
                pass


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

    def run_job(self, job_key, job_filename):
        """
        Runs a job
        """
        if not os.path.isfile(RUNNER_FILE):
            self.setup()

        cmd = [self.runtime_name, RUNNER_FILE, 'run_job', job_filename]
        process = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.PIPE, start_new_session=True)
        self.jobs[job_key] = process

        return process


class ContainerEnvironment(ExecutionEnvironment):
    """
    Docker environment uses a docker runtime image
    """

    def __init__(self, config):
        super().__init__(config)
        logger.debug(f'Starting container environment for {self.runtime_name}')
        self.use_gpu = self.config.get('use_gpu', False)
        self.docker_path = get_docker_path()
        self.is_podman = is_podman(self.docker_path)
        self.uid = os.getuid() if self.is_unix_system else None
        self.gid = os.getgid() if self.is_unix_system else None

    def setup(self):
        logger.debug('Setting up container environment')
        self._copy_lithops_to_tmp()
        if self.config.get('pull_runtime', False):
            logger.debug(f'Pulling runtime {self.runtime_name}')
            sp.run(
                shlex.split(f'docker pull {self.runtime_name}'), check=True,
                stdout=sp.PIPE, universal_newlines=True
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

    def run_job(self, job_key, job_filename):
        """
        Runs a job
        """
        if not os.path.isfile(RUNNER_FILE):
            self.setup()

        tmp_path = Path(TEMP_DIR).as_posix()

        cmd = f'{self.docker_path} run --name lithops_{job_key} '
        cmd += '--gpus all ' if self.use_gpu else ''
        cmd += f'--user {self.uid}:{self.gid} ' if self.is_unix_system and not self.is_podman else ''
        cmd += f'--env USER={os.getenv("USER", "root")} '
        cmd += f'--rm -v {tmp_path}:/tmp --entrypoint "python3" '
        cmd += f'{self.runtime_name} /tmp/{USER_TEMP_DIR}/localhost-runner.py run_job {job_filename}'

        process = sp.Popen(shlex.split(cmd), stdout=sp.PIPE, stderr=sp.PIPE, start_new_session=True)
        self.jobs[job_key] = process

        return process

    def stop(self, job_keys=None):
        """
        Stops running containers
        """
        jk_to_delete = job_keys or list(self.jobs.keys())

        for job_key in jk_to_delete:
            sp.Popen(
                shlex.split(f'{self.docker_path} rm -f lithops_{job_key}'),
                stdout=sp.DEVNULL, stderr=sp.DEVNULL
            )

        super().stop(job_keys)
