#
# (C) Copyright Cloudlab URV 2020
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

import os
import uuid
import json
import time
import hashlib
import logging
import importlib
import requests
import shlex
import concurrent.futures as cf
from typing import Any, Dict

from lithops.utils import (
    BackendType,
    is_lithops_worker,
    create_handler_zip,
    log_prefix,
)
from lithops.constants import (
    TEMP_DIR,
    SA_MASTER_SERVICE_PORT,
    SA_MASTER_DATA_FILE,
)
from lithops.standalone.utils import (
    StandaloneMode,
    LithopsValidationError,
    get_host_setup_script,
    get_master_setup_script,
    install_script_kwargs_from_config,
)
from lithops.version import __version__

logger = logging.getLogger(__name__)

_CURL_BODY_INLINE_LIMIT = 130000


class StandaloneHandler:
    """
    A StandaloneHandler object is used by invokers and other components to
    access the underlying standalone backend without exposing implementation
    details.
    """

    def __init__(self, standalone_config: Dict[str, Any]):
        self.config = standalone_config
        self.backend_name = self.config['backend']
        self.start_timeout = self.config['start_timeout']
        self.exec_mode = StandaloneMode[self.config['exec_mode'].upper()]
        self.is_lithops_worker = is_lithops_worker()

        module_location = f'lithops.standalone.backends.{self.backend_name}'
        sb_module = importlib.import_module(module_location)
        standalone_backend_cls = getattr(sb_module, 'StandaloneBackend')
        self.backend = standalone_backend_cls(
            self.config[self.backend_name], self.exec_mode.value
        )

        self.jobs = []
        logger.debug("Standalone handler created successfully")

    def init(self):
        """Prepares the backend resources a standalone run needs"""
        self.backend.init()

    def is_initialized(self):
        """True when the backend has resources from a previous run"""
        return self.backend.is_initialized()

    def build_image(
        self, image_name, script_file, overwrite, include, extra_args=None
    ):
        """Builds the VM image the instances will boot from"""
        self.backend.build_image(
            image_name, script_file, overwrite, include, extra_args or []
        )

    def delete_image(self, name):
        """Deletes a VM image built for Lithops"""
        self.backend.delete_image(name)

    def list_images(self):
        """Lists the VM images built for Lithops"""
        return self.backend.list_images()

    def _master_url(self, endpoint: str) -> str:
        """
        Returns the URL of a master service endpoint. A worker reaches the
        master by the name the setup script put in its hosts file
        """
        host = 'lithops-master' if self.is_lithops_worker else '127.0.0.1'
        return f'http://{host}:{SA_MASTER_SERVICE_PORT}/{endpoint}'

    def _make_request(self, method: str, endpoint: str, data=None):
        """
        Calls the master service. A worker can reach it over the network,
        while the client has to go through the SSH connection it already has
        """
        if self.is_lithops_worker:
            return self._request_from_worker(method, endpoint, data)
        return self._request_via_ssh(method, endpoint, data)

    def _request_from_worker(self, method: str, endpoint: str, data=None):
        """Calls the master service over HTTP, from inside the network"""
        url = self._master_url(endpoint)
        if method == 'GET':
            resp = requests.get(url, timeout=1)
            return resp.json()
        if method == 'POST':
            resp = requests.post(url, data=json.dumps(data))
            resp.raise_for_status()
            if not resp.content:
                return None
            return resp.json()
        raise ValueError(f'Unsupported HTTP method: {method}')

    def _request_via_ssh(self, method: str, endpoint: str, data=None):
        """
        Calls the master service through curl over SSH. A body too large for a
        command line is uploaded to a file the remote curl then reads
        """
        url = self._master_url(endpoint)
        # -sS hides the progress meter. Without it, a 204 from /job/stop or
        # /clean leaves stdout empty and the meter on stderr, which used to
        # be raised as "Could not stop the jobs on the master"
        cmd = (
            f"curl -sS -X {method} {url} "
            f"-H 'Content-Type: application/json'"
        )
        if data is not None:
            json_data = json.dumps(data)
            if len(json_data) < _CURL_BODY_INLINE_LIMIT:
                cmd = f'{cmd} -d {shlex.quote(json_data)}'
            else:
                data_file_name = (
                    f'/tmp/lithops_data_{str(uuid.uuid4())[-6:]}.json'
                )
                self.backend.master.get_ssh_client().upload_data_to_file(
                    json_data, data_file_name
                )
                cmd = f'{cmd} -d @{data_file_name}; rm {data_file_name}'

        out, err = self.backend.master.get_ssh_client().run_remote_command(cmd)
        if not out:
            if err:
                raise ValueError(err)
            return None
        try:
            return json.loads(out)
        except Exception as e:
            # Whatever the master printed instead of a response is the only
            # clue about what went wrong there
            raise ValueError(out) from e

    def _is_master_service_ready(self):
        """
        True when the master service answers and runs this same Lithops
        version, as a master left over from another version cannot be trusted
        """
        try:
            resp = self._make_request('GET', 'ping')
            if resp['response'] != __version__:
                raise LithopsValidationError(
                    f"{self.backend.master} is running Lithops "
                    f"{resp['response']} and it doesn't match local lithops "
                    f"version {__version__}, consider running "
                    f"'lithops clean -b {self.backend_name} --all' to delete "
                    f"the master instance"
                )
            return True
        except LithopsValidationError:
            raise
        except Exception:
            return False

    def _validate_master_service_setup(self):
        """
        Makes sure the master has the service installed and running, setting
        it up when it was never installed and giving up when it is dead
        """
        logger.debug(
            f'Validating lithops master service is installed on '
            f'{self.backend.master}'
        )
        ssh_client = self.backend.master.get_ssh_client()
        out, err = ssh_client.run_remote_command(f'cat {SA_MASTER_DATA_FILE}')
        if not out:
            self._setup_master_service()
            return

        logger.debug(
            f"Validating lithops master service is running on "
            f"{self.backend.master}"
        )
        out, err = ssh_client.run_remote_command("service lithops-master status")
        if not out or 'Active: active (running)' not in out:
            self.dismantle()
            raise LithopsValidationError(
                f"Lithops master service not active on {self.backend.master}, "
                "consider to delete master instance and metadata using "
                "'lithops clean --all'"
            )

    def _wait_master_service_ready(self):
        """Waits until the master service answers, or gives the instance up"""
        logger.info(
            f'Waiting for Lithops service to become ready on '
            f'{self.backend.master}'
        )

        start = time.time()
        while time.time() - start < self.start_timeout:
            if self._is_master_service_ready():
                ready_time = round(time.time() - start, 2)
                logger.debug(
                    f'{self.backend.master} ready in {ready_time} seconds'
                )
                return True
            time.sleep(2)

        self.dismantle()
        raise Exception(
            f'Lithops service readiness probe expired on {self.backend.master}'
        )

    def _get_workers_on_master(
        self, worker_instance_type, worker_processes, runtime_name
    ):
        """
        Returns the free workers the master already has of the requested
        shape, and none when it cannot be asked
        """
        try:
            payload = {
                'worker_instance_type': worker_instance_type,
                'worker_processes': worker_processes,
                'runtime_name': runtime_name,
            }
            return self._make_request('GET', 'worker/get', payload)
        except Exception as e:
            logger.debug(f'Could not get the workers of the master: {e}')
            return []

    def _create_workers(self, workers_to_create: int, executor_id, job_id):
        """
        Creates worker instances in parallel and returns the ones that came
        up. A worker that fails to be created is one worker less, not a
        failed job, so the job runs on whatever came up
        """
        if workers_to_create <= 0:
            return []
        current_workers_old = set(self.backend.workers)
        futures = []
        with cf.ThreadPoolExecutor(min(workers_to_create, 48)) as ex:
            for vm_n in range(workers_to_create):
                worker_id = f"{executor_id}-{job_id}-{vm_n}"
                worker_hash = hashlib.sha1(
                    worker_id.encode("utf-8")
                ).hexdigest()[:8]
                name = f'lithops-worker-{worker_hash}'
                futures.append(ex.submit(self.backend.create_worker, name))

        for future in cf.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.debug(f'Could not create a worker instance: {e}')

        new_workers = set(self.backend.workers) - current_workers_old
        logger.debug(
            f"Total worker VM instances created: "
            f"{len(new_workers)}/{workers_to_create}"
        )
        return list(new_workers)

    def _required_workers(self, job_payload) -> int:
        """
        Returns how many workers the job needs, filling in the instance shape
        the backend offers. Capped by max_workers, as that is the limit the
        user set on how much the run may spend
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        total_calls = job_payload['total_calls']

        worker_instance_type = self.backend.get_worker_instance_type()
        worker_processes = self.backend.get_worker_cpu_count()
        job_payload['worker_instance_type'] = worker_instance_type

        if job_payload['worker_processes'] == "AUTO":
            job_payload['worker_processes'] = worker_processes
            job_payload['config'][self.backend_name]['worker_processes'] = (
                worker_processes
            )

        wp = job_payload['worker_processes']
        max_workers = job_payload['max_workers']
        required_workers = min(
            max_workers, total_calls // wp + (total_calls % wp > 0)
        )
        logger.debug(
            f'{log_prefix(executor_id, job_id)} - Instance Type: '
            f'{worker_instance_type} - Worker '
            f'processes: {job_payload["worker_processes"]} - '
            f'Required Workers: {required_workers}'
        )
        return required_workers

    def _acquire_workers(self, job_payload, required_workers: int):
        """
        Returns the workers the job will run on, as the instances that were
        created for it and the total the job can count on. Consume mode runs
        on the master itself, and reuse mode only creates what the master does
        not already have free
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']

        if self.exec_mode == StandaloneMode.CONSUME:
            return [self.backend.master], 1

        if self.exec_mode == StandaloneMode.CREATE:
            new_workers = self._create_workers(
                required_workers, executor_id, job_id
            )
            return new_workers, len(new_workers)

        workers = self._get_workers_on_master(
            job_payload['worker_instance_type'],
            job_payload['worker_processes'],
            job_payload['runtime_name'],
        )
        total_workers = len(workers)
        logger.debug(
            f"Found {total_workers} free workers connected to "
            f"{self.backend.master}"
        )

        new_workers = []
        if total_workers < required_workers:
            workers_to_create = required_workers - total_workers
            logger.debug(f'Going to create {workers_to_create} new workers')
            new_workers = self._create_workers(
                workers_to_create, executor_id, job_id
            )
            total_workers += len(new_workers)

        return new_workers, total_workers

    def _ensure_master_ready(self) -> None:
        """Sets the master service up unless it is already answering"""
        logger.debug(f"Checking if {self.backend.master} is ready")
        if self._is_master_service_ready():
            return

        self.backend.master.create(check_if_exists=True)
        self.backend.master.wait_ready()
        self._validate_master_service_setup()
        self._wait_master_service_ready()

    def invoke(self, job_payload):
        """
        Runs a job on the standalone backend: works out how many workers it
        needs, gets them up, and hands the job over to the master service
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        total_calls = job_payload['total_calls']
        required_workers = 0

        if self.exec_mode == StandaloneMode.CONSUME:
            logger.debug(
                f'{log_prefix(executor_id, job_id)} - Worker processes: '
                f'{job_payload["worker_processes"]}'
            )
        else:
            required_workers = self._required_workers(job_payload)

        new_workers, total_workers = self._acquire_workers(
            job_payload, required_workers
        )

        if total_workers == 0:
            raise Exception('It was not possible to create any workers')

        logger.debug(
            f'{log_prefix(executor_id, job_id)} - Going to run '
            f'{total_calls} activations in {total_workers} workers'
        )

        self._ensure_master_ready()

        # The key never leaves the client: the master has its own to reach the
        # workers it creates
        backend = job_payload['config']['lithops']['backend']
        job_payload['config'][backend].pop('ssh_key_filename', None)

        job_payload['worker_instances'] = [
            {
                'name': inst.name,
                'private_ip': inst.private_ip,
                'instance_id': inst.instance_id,
                'ssh_credentials': inst.ssh_credentials,
                'instance_type': inst.instance_type,
            }
            for inst in new_workers
        ]

        self._make_request('POST', 'job/run', job_payload)
        logger.debug(f'Job invoked on {self.backend.master}')
        self.jobs.append(job_payload['job_key'])

    def deploy_runtime(self, runtime_name, *args):
        """
        Brings the master up, installs the service on it, and asks it for the
        metadata of the runtime, which only the master can extract
        """
        logger.debug(f'Checking if {self.backend.master} is ready')
        if not self.backend.master.is_ready():
            self.backend.master.create(check_if_exists=True)
            self.backend.master.wait_ready()

        self._setup_master_service()
        self._wait_master_service_ready()

        logger.debug('Extracting runtime metadata information')
        payload = {'runtime': runtime_name, 'pull_runtime': True}
        return self._make_request('GET', 'metadata', payload)

    def dismantle(self, **kwargs):
        """Stops the instances of this run"""
        self.backend.dismantle(**kwargs)

    def clean(self, **kwargs):
        """
        Deletes the resources of this run. The master is asked to clean up
        after itself first, unless everything is going away anyway
        """
        all_clean = kwargs.get('all', False)
        if self.is_initialized() and not all_clean:
            try:
                self.init()
                self._make_request('POST', 'clean')
            except Exception as e:
                # A master that cannot be reached has nothing to clean, and
                # the backend cleanup below still runs
                logger.debug(f'Could not clean up through the master: {e}')

        self.backend.clean(**kwargs)

    def clear(self, job_keys=None, exception=None):
        """
        Stops the jobs this handler invoked. Workers meant to be reused stay
        up, as the next job is going to run on them
        """
        try:
            self._make_request('POST', 'job/stop', self.jobs)
            logger.debug('Jobs stopped on the master')
        except Exception as e:
            logger.debug(f'Could not stop the jobs on the master: {e}')

        if self.exec_mode != StandaloneMode.REUSE:
            self.backend.clear(job_keys)

    def list_jobs(self):
        """Lists the jobs the master knows about"""
        return self._make_request('GET', 'job/list')

    def list_workers(self):
        """Lists the workers connected to the master"""
        return self._make_request('GET', 'worker/list')

    def get_runtime_key(
        self, runtime_name, runtime_memory, version=__version__
    ):
        """
        Returns a formatted string that represents the runtime key.
        Each backend has its own runtime key format. Used to store
        runtime metadata in storage.
        """
        return self.backend.get_runtime_key(runtime_name, version)

    def get_runtime_info(self):
        """Returns the runtime limits the executor reports to the user"""
        return {
            'runtime_name': self.config['runtime'],
            'runtime_memory': None,
            'runtime_timeout': self.config['hard_dismantle_timeout'],
            'max_workers': self.config[self.backend_name]['max_workers'],
        }

    def get_backend_type(self):
        """Returns the backend type, which is invoked with a whole job"""
        return BackendType.BATCH.value

    def _setup_master_service(self):
        """
        Installs Lithops on the master and starts its service, then brings
        back the public key the master generated, which is what the workers
        it creates will trust
        """
        logger.info(f'Installing Lithops in {self.backend.master}')

        ssh_client = self.backend.master.get_ssh_client()

        handler_zip = os.path.join(
            TEMP_DIR, f'lithops_standalone_{str(uuid.uuid4())[-6:]}.zip'
        )
        module_dir = os.path.dirname(__file__)
        create_handler_zip(
            handler_zip,
            [
                os.path.join(module_dir, 'master.py'),
                os.path.join(module_dir, 'worker.py'),
                os.path.join(module_dir, 'runner.py'),
            ],
        )

        logger.debug(f'Uploading lithops files to {self.backend.master}')
        ssh_client.upload_local_file(handler_zip, '/tmp/lithops_standalone.zip')
        os.remove(handler_zip)

        master_data = {
            'name': self.backend.master.name,
            'instance_id': self.backend.master.get_instance_id(),
            'private_ip': self.backend.master.get_private_ip(),
            'delete_on_dismantle': self.backend.master.delete_on_dismantle,
            'lithops_version': __version__,
        }

        logger.debug(
            f'Executing lithops installation process on {self.backend.master}'
        )
        logger.debug(
            'Be patient, initial installation process may take up to 3 minutes'
        )

        remote_script = "/tmp/install_lithops.sh"
        script = get_host_setup_script(
            run_install=False,
            **install_script_kwargs_from_config(self.config),
        )
        script += get_master_setup_script(self.config, master_data)

        ssh_client.upload_data_to_file(script, remote_script)
        cmd = f"chmod 755 {remote_script}; sudo {remote_script}; rm {remote_script}"
        ssh_client.run_remote_command(cmd)

        # Download the master VM public key generated with the installation script
        # This public key will be used to create the workers
        ssh_client.download_remote_file(
            f'{self.backend.master.home_dir}/.ssh/lithops_id_rsa.pub',
            f'{self.backend.cache_dir}/{self.backend.master.name}-id_rsa.pub',
        )
