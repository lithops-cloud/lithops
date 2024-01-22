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
import logging
import importlib
import requests
import shlex
import concurrent.futures as cf

from lithops.utils import BackendType, is_lithops_worker, create_handler_zip
from lithops.constants import SA_SERVICE_PORT, SA_INSTALL_DIR, TEMP_DIR
from lithops.standalone.utils import StandaloneMode, LithopsValidationError, get_master_setup_script
from lithops.version import __version__

logger = logging.getLogger(__name__)


class StandaloneHandler:
    """
    A StandaloneHandler object is used by invokers and other components to access
    underlying standalone backend without exposing the implementation details.
    """

    def __init__(self, standalone_config):
        self.config = standalone_config
        self.backend_name = self.config['backend']
        self.start_timeout = self.config['start_timeout']
        self.exec_mode = self.config['exec_mode']
        self.is_lithops_worker = is_lithops_worker()

        exec_modes = [StandaloneMode.CONSUME.value, StandaloneMode.CREATE.value, StandaloneMode.REUSE.value]
        if self.exec_mode not in exec_modes:
            raise Exception(f"Invalid execution mode '{self.exec_mode}'. Use one of {exec_modes}")

        module_location = f'lithops.standalone.backends.{self.backend_name}'
        sb_module = importlib.import_module(module_location)
        StandaloneBackend = getattr(sb_module, 'StandaloneBackend')
        self.backend = StandaloneBackend(self.config[self.backend_name], self.exec_mode)

        self.jobs = []  # list to store executed jobs (job_keys)
        logger.debug("Standalone handler created successfully")

    def init(self):
        """
        Initialize the backend and create/start the master VM instance
        """
        self.backend.init()

    def is_initialized(self):
        """
        Check if the backend is initialized
        """
        return self.backend.is_initialized()

    def build_image(self, image_name, script_file, overwrite, extra_args=[]):
        """
        Builds a new VM Image
        """
        self.backend.build_image(image_name, script_file, overwrite, extra_args)

    def delete_image(self, name):
        """
        Deletes VM Image
        """
        self.backend.delete_image(name)

    def list_images(self):
        """
        Lists VM Images
        """
        return self.backend.list_images()

    def _make_request(self, method, endpoint, data=None):
        """
        Makes a requests to the master VM
        """
        if self.is_lithops_worker:
            url = f"http://lithops-master:{SA_SERVICE_PORT}/{endpoint}"
            if method == 'GET':
                resp = requests.get(url, timeout=1)
                return resp.json()
            elif method == 'POST':
                resp = requests.post(url, data=json.dumps(data))
                resp.raise_for_status()
                return resp.json()
        else:
            url = f'http://127.0.0.1:{SA_SERVICE_PORT}/{endpoint}'
            cmd = f'curl -X {method} {url} -H \'Content-Type: application/json\''
            if data is not None:
                data_str = shlex.quote(json.dumps(data))
                cmd = f'{cmd} -d {data_str}'
            out = self.backend.master.get_ssh_client().run_remote_command(cmd)
            return json.loads(out)

    def _is_master_service_ready(self):
        """
        Checks if the proxy is ready to receive http connections
        """
        try:
            resp = self._make_request('GET', 'ping')
            if resp['response'] != __version__:
                raise LithopsValidationError(
                    f"{self.backend.master} is running Lithops {resp['response']} and "
                    f"it doesn't match local lithops version {__version__}, consider "
                    "running 'lithops clean --all' to delete the master instance")
            return True
        except LithopsValidationError as e:
            raise e
        except Exception:
            return False

    def _validate_master_service_setup(self):
        """
        Checks the master VM is correctly installed
        """
        logger.debug(f'Validating lithops master service is installed on {self.backend.master}')
        ssh_client = self.backend.master.get_ssh_client()
        res = ssh_client.run_remote_command(f'cat {SA_INSTALL_DIR}/access.data')
        if not res:
            self._setup_master_service()
            return

        logger.debug(f"Validating lithops master service is running on {self.backend.master}")
        res = ssh_client.run_remote_command("service lithops-master status")
        if not res or 'Active: active (running)' not in res:
            self.dismantle()
            raise LithopsValidationError(
                f"Lithops master service not active on {self.backend.master}, "
                "consider to delete master instance and metadata using "
                "'lithops clean --all'")

    def _wait_master_service_ready(self):
        """
        Waits until the master service is ready to receive http connections
        """
        logger.info(f'Waiting Lithops service to become ready on {self.backend.master}')

        start = time.time()
        while (time.time() - start < self.start_timeout):
            if self._is_master_service_ready():
                ready_time = round(time.time() - start, 2)
                logger.debug(f'{self.backend.master} ready in {ready_time} seconds')
                return True
            time.sleep(2)

        self.dismantle()
        raise Exception(f'Lithops service readiness probe expired on {self.backend.master}')

    def _get_workers_on_master(self, worker_instance_type, runtime_name):
        """
        gets the total available workers on the master VM
        """
        workers_on_master = []
        try:
            endpoint = f'worker/{worker_instance_type}/{runtime_name}'
            workers_on_master = self._make_request('GET', endpoint)
        except Exception:
            pass
        return workers_on_master

    def invoke(self, job_payload):
        """
        Run the job description against the selected environment
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        total_calls = job_payload['total_calls']

        if self.exec_mode != StandaloneMode.CONSUME.value:
            worker_instance_type = self.backend.get_worker_instance_type()
            worker_processes = self.backend.get_worker_cpu_count()

            job_payload['worker_instance_type'] = worker_instance_type

            if job_payload['worker_processes'] == "AUTO":
                job_payload['worker_processes'] = worker_processes
                job_payload['config'][self.backend_name]['worker_processes'] = worker_processes

            if job_payload['chunksize'] == 0:
                job_payload['chunksize'] = job_payload['worker_processes']
                job_payload['config']['lithops']['chunksize'] = job_payload['worker_processes']

            # Make sure only max_workers are started
            chunksize = job_payload['chunksize']
            max_workers = job_payload['max_workers']
            required_workers = min(max_workers, total_calls // chunksize + (total_calls % chunksize > 0))

            logger.debug('ExecutorID {} | JobID {} - Worker processes: {} - Chunksize: {} - Required Workers: {}'
                         .format(executor_id, job_id, job_payload['worker_processes'],
                                 job_payload['chunksize'], required_workers))

        def create_workers(workers_to_create):
            current_workers_old = set(self.backend.workers)
            futures = []
            with cf.ThreadPoolExecutor(min(workers_to_create, 48)) as ex:
                for vm_n in range(workers_to_create):
                    worker_id = "{:04d}".format(vm_n)
                    name = f'lithops-worker-{executor_id}-{job_id}-{worker_id}'
                    futures.append(ex.submit(self.backend.create_worker, name))

            for future in cf.as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass

            current_workers_new = set(self.backend.workers)
            new_workers = current_workers_new - current_workers_old
            logger.debug(f"Total worker VM instances created: {len(new_workers)}/{workers_to_create}")

            return list(new_workers)

        new_workers = []

        if self.exec_mode == StandaloneMode.CONSUME.value:
            total_workers = 1

        elif self.exec_mode == StandaloneMode.CREATE.value:
            new_workers = create_workers(required_workers)
            total_workers = len(new_workers)

        elif self.exec_mode == StandaloneMode.REUSE.value:
            workers = self._get_workers_on_master(
                job_payload['worker_instance_type'],
                job_payload['runtime_name']
            )
            total_workers = len(workers)
            logger.debug(f"Found {total_workers} free workers connected to {self.backend.master}")
            if total_workers < required_workers:
                # create missing delta of workers
                workers_to_create = required_workers - total_workers
                logger.debug(f'Going to create {workers_to_create} new workers')
                new_workers = create_workers(workers_to_create)
                total_workers += len(new_workers)

        if total_workers == 0:
            raise Exception('It was not possible to create any worker')

        logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Going to run '
                     f'{total_calls} activations in {total_workers} workers')

        logger.debug(f"Checking if {self.backend.master} is ready")
        if not self._is_master_service_ready():
            self.backend.master.create(check_if_exists=True)
            self.backend.master.wait_ready()
            self._validate_master_service_setup()
            self._wait_master_service_ready()

        # delete ssh key
        backend = job_payload['config']['lithops']['backend']
        job_payload['config'][backend].pop('ssh_key_filename', None)

        # prepare worker instances data
        job_payload['worker_instances'] = [
            {'name': inst.name,
             'private_ip': inst.private_ip,
             'instance_id': inst.instance_id,
             'ssh_credentials': inst.ssh_credentials}
            for inst in new_workers
        ]

        # invoke Job
        self._make_request('POST', 'job/run', job_payload)
        logger.debug(f'Job invoked on {self.backend.master}')

        self.jobs.append(job_payload['job_key'])

    def deploy_runtime(self, runtime_name, *args):
        """
        Installs the proxy and extracts the runtime metadata
        """
        logger.debug(f'Checking if {self.backend.master} is ready')
        if not self.backend.master.is_ready():
            self.backend.master.create(check_if_exists=True)
            self.backend.master.wait_ready()

        if not self._is_master_service_ready():
            self._setup_master_service()
            self._wait_master_service_ready()

        logger.debug('Extracting runtime metadata information')
        payload = {'runtime': runtime_name, 'pull_runtime': True}
        runtime_meta = self._make_request('GET', 'metadata', payload)

        return runtime_meta

    def dismantle(self, **kwargs):
        """
        Stop all VM instances
        """
        self.backend.dismantle(**kwargs)

    def clean(self, **kwargs):
        """
        Clan all the backend resources
        """
        self.backend.clean(**kwargs)

    def clear(self, job_keys=None, exception=None):
        """
        Clear all the backend resources.
        clear method is executed after the results are get,
        when an exception is produced, or when a user press ctrl+c
        """
        try:
            self._make_request('POST', 'stop', self.jobs)
        except Exception:
            pass

        if self.exec_mode != StandaloneMode.REUSE.value:
            self.backend.clear(job_keys)

    def list_jobs(self):
        """
        Lists jobs in master VM
        """
        return self._make_request('GET', 'job/list')

    def list_workers(self):
        """
        Lists available workers in master VM
        """
        return self._make_request('GET', 'worker/list')

    def get_runtime_key(self, runtime_name, runtime_memory, version=__version__):
        """
        Wrapper method that returns a formated string that represents the
        runtime key. Each backend has its own runtime key format. Used to
        store runtime metadata into the storage
        """
        return self.backend.get_runtime_key(runtime_name, version)

    def get_runtime_info(self):
        """
        Method that returns a dictionary with all the runtime information
        set in config
        """
        runtime_info = {
            'runtime_name': self.config['runtime'],
            'runtime_memory': None,
            'runtime_timeout': self.config['hard_dismantle_timeout'],
            'max_workers': self.config[self.backend_name]['max_workers'],
        }

        return runtime_info

    def get_backend_type(self):
        """
        Wrapper method that returns the type of the backend (Batch or FaaS)
        """
        return BackendType.BATCH.value

    def _setup_master_service(self):
        """
        Setup lithops necessary packages and files in master VM instance
        """
        logger.info(f'Installing Lithops in {self.backend.master}')

        ssh_client = self.backend.master.get_ssh_client()

        handler_zip = os.path.join(TEMP_DIR, f'lithops_standalone_{str(uuid.uuid4())[-6:]}.zip')
        worker_path = os.path.join(os.path.dirname(__file__), 'worker.py')
        master_path = os.path.join(os.path.dirname(__file__), 'master.py')
        create_handler_zip(handler_zip, [master_path, worker_path])

        logger.debug(f'Uploading lithops files to {self.backend.master}')
        ssh_client.upload_local_file(handler_zip, '/tmp/lithops_standalone.zip')
        os.remove(handler_zip)

        vm_data = {'name': self.backend.master.name,
                   'instance_id': self.backend.master.get_instance_id(),
                   'private_ip': self.backend.master.get_private_ip(),
                   'delete_on_dismantle': self.backend.master.delete_on_dismantle,
                   'lithops_version': __version__}

        logger.debug(f'Executing lithops installation process on {self.backend.master}')
        logger.debug('Be patient, initial installation process may take up to 3 minutes')

        remote_script = "/tmp/install_lithops.sh"
        script = get_master_setup_script(self.config, vm_data)
        ssh_client.upload_data_to_file(script, remote_script)
        ssh_client.run_remote_command(f"chmod 777 {remote_script}; sudo {remote_script};")

        # Download the master VM public key generated with the installation script
        # This public key will be used to create the workers
        ssh_client.download_remote_file(
            f'{self.backend.master.home_dir}/.ssh/lithops_id_rsa.pub',
            f'{self.backend.cache_dir}/{self.backend.master.name}-id_rsa.pub')
