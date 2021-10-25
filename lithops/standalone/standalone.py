#
# Copyright Cloudlab URV 2020
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
import time
import logging
import importlib
import requests
import shlex
from concurrent.futures import ThreadPoolExecutor

from lithops.utils import is_lithops_worker, create_handler_zip
from lithops.constants import STANDALONE_INSTALL_DIR, STANDALONE_SERVICE_PORT
from lithops.standalone.utils import get_master_setup_script


logger = logging.getLogger(__name__)
LOCAL_FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_standalone.zip')


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

        module_location = 'lithops.standalone.backends.{}'.format(self.backend_name)
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

    def _is_master_instance_ready(self):
        """
        Checks if the VM instance is ready to receive ssh connections
        """
        try:
            self.backend.master.get_ssh_client().run_remote_command('id')
        except Exception:
            return False
        return True

    def _wait_master_instance_ready(self):
        """
        Waits until the VM instance is ready to receive ssh connections
        """
        logger.info('Waiting {} to become ready'
                    .format(self.backend.master))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_master_instance_ready():
                logger.debug('{} ready in {} seconds'
                             .format(self.backend.master,
                                     round(time.time()-start, 2)))
                return True
            time.sleep(5)

        self.dismantle()
        raise Exception('Readiness probe expired on {}'
                        .format(self.backend.master))

    def _is_master_service_ready(self):
        """
        Checks if the proxy is ready to receive http connections
        """
        try:
            if self.is_lithops_worker:
                url = "http://127.0.0.1:{}/ping".format(STANDALONE_SERVICE_PORT)
                r = requests.get(url, timeout=1)
                if r.status_code == 200:
                    return True
                return False
            else:
                cmd = 'curl -X GET http://127.0.0.1:{}/ping'.format(STANDALONE_SERVICE_PORT)
                out = self.backend.master.get_ssh_client().run_remote_command(cmd)
                data = json.loads(out)
                if data['response'] == 'pong':
                    return True
        except Exception:
            return False

    def _wait_master_service_ready(self):
        """
        Waits until the proxy is ready to receive http connections
        """
        logger.info('Waiting Lithops service to become ready on {}'
                    .format(self.backend.master))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_master_service_ready():
                logger.debug('{} ready in {} seconds'
                             .format(self.backend.master,
                                     round(time.time()-start, 2)))
                return True
            time.sleep(2)

        self.dismantle()
        raise Exception('Lithops service readiness probe expired on {}'
                        .format(self.backend.master))

    def invoke(self, job_payload):
        """
        Run the job description against the selected environment
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        total_calls = job_payload['total_calls']
        chunksize = job_payload['chunksize']

        total_workers = (total_calls // chunksize + (total_calls % chunksize > 0)
                         if self.exec_mode in ['create', 'reuse'] else 1)

        def start_master_instance(wait=True):
            if not self._is_master_service_ready():
                self.backend.master.create(check_if_exists=True, start=True)
                if wait:
                    self._wait_master_service_ready()

        def get_workers_on_master():
            workers_on_master = []
            try:
                cmd = (f'curl -X GET http://127.0.0.1:{STANDALONE_SERVICE_PORT}/workers -H \'Content-Type: application/json\'')
                workers_on_master = json.loads(self.backend.master.get_ssh_client().run_remote_command(cmd))
            except Exception:
                pass

            return workers_on_master

        def create_workers():
            current_workers_old = set(self.backend.workers)
            with ThreadPoolExecutor(total_workers+1) as ex:
                ex.submit(start_master_instance, wait=False)
                for vm_n in range(total_workers + 1):
                    worker_id = "{:04d}".format(vm_n)
                    name = 'lithops-worker-{}-{}-{}'.format(executor_id, job_id, worker_id)
                    ex.submit(self.backend.create_worker, name)
            current_workers_new = set(self.backend.workers)
            new_workers = current_workers_new - current_workers_old
            logger.debug("Total worker VM instances created: {}/{}"
                         .format(len(new_workers), total_workers))

            return new_workers

        worker_instances = []

        if self.exec_mode == 'create':
            workers = create_workers()
            total_workers = len(workers)
            worker_instances = [(inst.name,
                                 inst.ip_address,
                                 inst.instance_id,
                                 inst.ssh_credentials)
                                for inst in workers]

        elif self.exec_mode == 'reuse':
            workers = get_workers_on_master()
            logger.info(f"Found {len(workers)} workers connected to master {self.backend.master}")
            if workers:
                total_workers = len(workers)
            if not workers:
                self.backend.workers = []
                workers = create_workers()
                total_workers = len(workers)
                worker_instances = [(inst.name,
                                     inst.ip_address,
                                     inst.instance_id,
                                     inst.ssh_credentials)
                                    for inst in workers]

        if total_workers == 0:
            raise Exception('It was not possible to create any worker')

        logger.debug('ExecutorID {} | JobID {} - Going to run {} activations '
                     'in {} workers'.format(executor_id, job_id, total_calls,
                                            total_workers))

        logger.debug("Checking if {} is ready".format(self.backend.master))
        start_master_instance(wait=True)

        job_payload['worker_instances'] = worker_instances

        if self.is_lithops_worker:
            url = "http://127.0.0.1:{}/run".format(STANDALONE_SERVICE_PORT)
            requests.post(url, data=json.dumps(job_payload))
        else:
            # delete ssh key
            backend = job_payload['config']['lithops']['backend']
            job_payload['config'][backend].pop('ssh_key_filename', None)

            cmd = ('curl http://127.0.0.1:{}/run -d {} '
                   '-H \'Content-Type: application/json\' -X POST'
                   .format(STANDALONE_SERVICE_PORT,
                           shlex.quote(json.dumps(job_payload))))
            self.backend.master.get_ssh_client().run_remote_command(cmd)
            self.backend.master.del_ssh_client()

        logger.debug('Job invoked on {}'.format(self.backend.master))

        self.jobs.append(job_payload['job_key'])

    def create_runtime(self, runtime_name, *args):
        """
        Installs the proxy and extracts the runtime metadata and
        preinstalled modules
        """
        logger.debug('Checking if {} is ready'.format(self.backend.master))
        if not self._is_master_instance_ready():
            logger.debug('{} not ready'.format(self.backend.master))
            self.backend.master.create(check_if_exists=True, start=True)
            self._wait_master_instance_ready()
        self._setup_master_service()
        self._wait_master_service_ready()

        logger.debug('Extracting runtime metadata information')
        payload = {'runtime': runtime_name, 'pull_runtime': True}
        cmd = ('curl http://127.0.0.1:8080/preinstalls -d {} '
               '-H \'Content-Type: application/json\' -X GET'
               .format(shlex.quote(json.dumps(payload))))
        out = self.backend.master.get_ssh_client().run_remote_command(cmd)
        runtime_meta = json.loads(out)

        return runtime_meta

    def dismantle(self):
        """
        Stop all VM instances
        """
        self.backend.dismantle()

    def clean(self):
        """
        Clan all the backend resources
        """
        self.backend.clean()

    def clear(self, job_keys=None):
        """
        Clear all the backend resources.
        clear method is executed after the results are get,
        when an exception is produced, or when a user press ctrl+c
        """
        cmd = ('curl http://127.0.0.1:{}/clear -d {} '
               '-H \'Content-Type: application/json\' -X POST'
               .format(STANDALONE_SERVICE_PORT,
                       shlex.quote(json.dumps(self.jobs))))
        try:
            self.backend.master.get_ssh_client().run_remote_command(cmd)
            self.backend.master.del_ssh_client()
        except Exception:
            pass

        if self.exec_mode != 'reuse':
            self.backend.clear(job_keys)

    def get_runtime_key(self, runtime_name, *args):
        """
        Wrapper method that returns a formated string that represents the
        runtime key. Each backend has its own runtime key format. Used to
        store modules preinstalls into the storage
        """
        return self.backend.get_runtime_key(runtime_name)

    def get_backend_type(self):
        """
        Wrapper method that returns the type of the backend (Batch or FaaS)
        """
        return 'batch'

    def _setup_master_service(self):
        """
        Setup lithops necessary packages and files in master VM instance
        """
        logger.debug('Installing Lithops in {}'.format(self.backend.master))
        ssh_client = self.backend.master.get_ssh_client()

        src_proxy = os.path.join(os.path.dirname(__file__), 'worker.py')
        create_handler_zip(LOCAL_FH_ZIP_LOCATION, src_proxy)
        current_location = os.path.dirname(os.path.abspath(__file__))
        controller_location = os.path.join(current_location, 'master.py')

        logger.debug('Uploading lithops files to {}'.format(self.backend.master))
        files_to_upload = [(LOCAL_FH_ZIP_LOCATION, '/tmp/lithops_standalone.zip'),
                           (controller_location, '/tmp/master.py'.format(STANDALONE_INSTALL_DIR))]
        ssh_client.upload_multiple_local_files(files_to_upload)
        os.remove(LOCAL_FH_ZIP_LOCATION)

        vm_data = {'instance_name': self.backend.master.name,
                   'ip_address': self.backend.master.ip_address,
                   'instance_id': self.backend.master.instance_id}

        script = get_master_setup_script(self.config, vm_data)

        logger.debug('Executing lithops installation process on {}'.format(self.backend.master))
        logger.debug('Be patient, initial installation process may take up to 5 minutes')
        ssh_client.run_remote_command(script)
        logger.debug('Lithops installation process completed')
