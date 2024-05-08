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
import xmlrpc.client
import subprocess as sp
from shutil import copyfile
from pathlib import Path

from lithops.version import __version__
from lithops.constants import (
    JOBS_DIR,
    LOCALHOST_RUNTIME_DEFAULT,
    RN_LOG_FILE,
    TEMP_DIR,
    USER_TEMP_DIR,
    LITHOPS_TEMP_DIR,
    COMPUTE_CLI_MSG,
    SV_LOG_FILE,
    CPU_COUNT,
)
from lithops.utils import (
    BackendType,
    find_free_port,
    get_docker_path,
    is_lithops_worker,
    is_unix_system
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
        self.runtime_name = self.config.get('runtime', LOCALHOST_RUNTIME_DEFAULT)
        self.env = None

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
        default_env = self.runtime_name.startswith(('python', '/'))
        self.env = DefaultEnvironment(self.config) if default_env \
            else ContainerEnvironment(self.config)
        self.env.setup()

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
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        total_calls = len(job_payload['call_ids'])

        logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Running '
                     f'{total_calls} activations in the localhost worker')
        self.env.run(job_payload)

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
        self.env.stop(job_keys)


class BaseEnvironment:
    """
    Base environment class for shared methods
    """

    def __init__(self, config):
        self.config = config
        self.runtime_name = self.config['runtime']
        self.worker_processes = self.config.get('worker_processes', CPU_COUNT)
        self.work_queue = queue.Queue()
        self.job_keys = []
        self.job_processes = {}
        self.canceled = []

    def _copy_lithops_to_tmp(self):
        if is_lithops_worker() and os.path.isfile(RUNNER_FILE):
            return
        os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
        shutil.rmtree(os.path.join(LITHOPS_TEMP_DIR, 'lithops'), ignore_errors=True)
        shutil.copytree(LITHOPS_LOCATION, os.path.join(LITHOPS_TEMP_DIR, 'lithops'))
        src_handler = os.path.join(LITHOPS_LOCATION, 'localhost', 'v2', 'runner.py')
        copyfile(src_handler, RUNNER_FILE)

    def get_metadata(self):
        if not os.path.isfile(RUNNER_FILE):
            self.setup()

        logger.debug(f"Extracting runtime metadata from: {self.runtime_name}")
        cmd = [self.runtime_name, RUNNER_FILE, 'get_metadata']
        process = sp.run(
            cmd, check=True,
            stdout=sp.PIPE,
            universal_newlines=True,
            start_new_session=True
        )
        runtime_meta = json.loads(process.stdout.strip())
        return runtime_meta

    def run(self, job_payload):
        """
        Adds a job to the localhost service
        """
        self.job_keys.append(job_payload['job_key'])
        dbr = job_payload['data_byte_ranges']
        for call_id in job_payload['call_ids']:
            task_payload = copy.deepcopy(job_payload)
            task_payload['call_ids'] = [call_id]
            task_payload['data_byte_ranges'] = [dbr[int(call_id)]]
            self.work_queue.put(json.dumps(task_payload))

    def stop(self, job_keys=None):
        """
        Stops running processes
        """
        def kill_job(job_key):
            if self.jobs[job_key].poll() is None:
                logger.debug(f'Killing job {job_key} with PID {self.jobs[job_key].pid}')
                PID = self.jobs[job_key].pid
                if is_unix_system():
                    PGID = os.getpgid(PID)
                    os.killpg(PGID, signal.SIGKILL)
                else:
                    os.kill(PID, signal.SIGTERM)
            del self.jobs[job_key]

        for _ in range(self.worker_processes):
            self.work_queue.put(None)

        for t in self.threads:
            t.join()

        to_delete = job_keys or list(self.jobs.keys())
        for job_key in to_delete:
            try:
                if job_key in self.jobs:
                    kill_job(job_key)
            except Exception:
                pass


class DefaultEnvironment(BaseEnvironment):
    """
    Default environment uses current python3 installation
    """

    def __init__(self, config):
        super().__init__(config)
        logger.debug(f'Starting python environment for {self.runtime_name}')

    def setup(self):
        logger.debug('Setting up python environment')
        self._copy_lithops_to_tmp()

        def process_task(task_payload_str):
            try:
                task_payload = json.loads(task_payload_str)
                job_key = task_payload['job_key']
                call_id = task_payload['call_ids'][0]
                job_key_call_id = f'{job_key}-{call_id}'

                task_filename = os.path.join(JOBS_DIR, f'{job_key_call_id}.task')

                with open(task_filename, 'w') as jl:
                    json.dump(task_payload, jl, default=str)

                cmd = [self.runtime_name, RUNNER_FILE, 'run_job', task_filename]
                log = open(RN_LOG_FILE, 'a')
                process = sp.Popen(cmd, stdout=log, stderr=log, start_new_session=True)
                self.job_processes[job_key_call_id] = process
                process.communicate()  # blocks until the process finishes
                del self.job_processes[job_key_call_id]

                if os.path.exists(task_filename):
                    os.remove(task_filename)

            except Exception as e:
                logger.error(e)

        def queue_consumer(work_queue):
            while True:
                task_payload_str = work_queue.get()
                if task_payload_str is None:
                    break
                process_task(task_payload_str)

        self.threads = []
        for _ in range(self.worker_processes):
            t = threading.Thread(
                target=queue_consumer,
                args=(self.work_queue,),
                daemon=True)
            t.start()
            self.threads.append(t)


class ContainerEnvironment(BaseEnvironment):
    """
    Container environment uses a container runtime image
    """

    def __init__(self, config):
        super().__init__(config)
        self.use_gpu = self.config.get('use_gpu', False)
        logger.debug(f'Starting container environment for {self.runtime_name}')
        self.container_id = str(uuid.uuid4()).replace('-', '')[:12]
        self.uid = os.getuid() if is_unix_system() else None
        self.gid = os.getgid() if is_unix_system() else None

    def setup(self):
        logger.debug('Setting up container environment')
        self._copy_lithops_to_tmp()

        if self.config.get('pull_runtime', False):
            docker_path = get_docker_path()
            logger.debug(f'Pulling runtime {self.runtime_name}')
            sp.run(
                shlex.split(f'{docker_path} pull {self.runtime_name}'),
                check=True, stdout=sp.PIPE, universal_newlines=True
            )

    def start_service(self):
        if self.service_process and self.service_process.poll() is None:
            return

        if not os.path.isfile(RUNNER_FILE):
            self.setup()

        logger.debug('Starting localhost executor service - Docker environemnt')

        tmp_path = Path(TEMP_DIR).as_posix()
        docker_path = get_docker_path()
        service_port = find_free_port()

        cmd = f'{docker_path} run --name lithops_{self.container_id} '
        cmd += '--gpus all ' if self.use_gpu else ''
        cmd += f'--user {self.uid}:{self.gid} ' if is_unix_system() else ''
        cmd += f'--env USER={os.getenv("USER", "root")} '
        cmd += f'-p {service_port}:{service_port} '
        cmd += f'--rm -v {tmp_path}:/tmp --entrypoint "python3" '
        cmd += f'{self.runtime_name} /tmp/{USER_TEMP_DIR}/localhost-service.py '
        cmd += f'{self.worker_processes} {service_port} '
        cmd += f'{self.max_idle_timeout} {self.check_interval}'

        log = open(SV_LOG_FILE, 'a')
        process = sp.Popen(shlex.split(cmd), stdout=log, stderr=log, start_new_session=True)
        self.service_process = process

        self.client = xmlrpc.client.ServerProxy(f'http://localhost:{service_port}')
        self.service_running = True

    def stop(self):
        """
        Stop localhost container
        """
        sp.Popen(
            shlex.split(f'docker rm -f lithops_{self.container_id}'),
            stdout=sp.DEVNULL, stderr=sp.DEVNULL
        )
        super().stop()
