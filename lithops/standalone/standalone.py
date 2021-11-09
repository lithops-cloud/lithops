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
import concurrent.futures

from concurrent.futures import ThreadPoolExecutor

from lithops.utils import is_lithops_worker, create_handler_zip
from lithops.constants import STANDALONE_SERVICE_PORT, STANDALONE_INSTALL_DIR
from lithops.standalone.utils import get_master_setup_script

from lithops.version import __version__ as lithops_version

logger = logging.getLogger(__name__)
LOCAL_FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_standalone.zip')


class LithopsValidationError(Exception):
    pass


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
                if data['response'] == lithops_version:
                    return True
        except LithopsValidationError as e:
            raise e
        except Exception:
            return False

    def _validate_master_service_setup(self):
        logger.debug(f'Validating lithops version installed on master matches {lithops_version}')
        cmd = f'cat {STANDALONE_INSTALL_DIR}/access.data'

        ssh_client = self.backend.master.get_ssh_client(unbinded=True)
        res = ssh_client.run_remote_command(cmd)
        if not res:
            raise Exception(
                f"Lithops service not installed on {self.backend.master}, consider using 'lithops clean' "
                 "to delete runtime metadata or 'lithops clean --all' to delete master instance as well")

        master_lithops_version = json.loads(res).get('lithops_version')
        if master_lithops_version != lithops_version:
            raise Exception(
                f"Lithops version {master_lithops_version} on {self.backend.master}, doesn't match local "
                f"lithops version {lithops_version}, consider running 'lithops clean' to delete runtime "
                "metadata leftovers or 'lithops clean --all' to delete master instance as well")

        logger.debug(
            f'Validating lithops lithops master service is running on {self.backend.master}')
        cmd = "service lithops-master status"
        res = ssh_client.run_remote_command(cmd)
        if not res:
            raise Exception(
                f"Lithops master service not installed on {self.backend.master}, consider to delete master "
                "instance and metadata using 'lithops clean --all'")

        if 'Active: active (running)' not in res:
            raise Exception(
                f"Lithops master service not active on {self.backend.master}, consider to delete master "
                "instance and metadata using 'lithops clean --all'", res)
        ssh_client.close()
        ssh_client = None

    def _wait_master_service_ready(self):
        """
        Waits until the proxy is ready to receive http connections
        """
        self._validate_master_service_setup()

        logger.info('Waiting Lithops service to become ready on {}'
                    .format(self.backend.master))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_master_service_ready():
                ready_time = round(time.time()-start, 2)
                logger.debug(f'{self.backend.master} ready in {ready_time} seconds')
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

        total_required_workers = (total_calls // chunksize + (total_calls % chunksize > 0)
                                  if self.exec_mode in ['create', 'reuse'] else 1)

        def start_master_instance(wait=True):
            if not self._is_master_service_ready():
                self.backend.master.create(check_if_exists=True)
                if wait:
                    self._wait_master_instance_ready()
                    self._wait_master_service_ready()

        def get_workers_on_master():
            workers_on_master = []
            try:
                cmd = (f'curl -X GET http://127.0.0.1:{STANDALONE_SERVICE_PORT}/workers '
                       '-H \'Content-Type: application/json\'')
                resp = self.backend.master.get_ssh_client().run_remote_command(cmd)
                workers_on_master = json.loads(resp)
            except LithopsValidationError as e:
                raise e
            except Exception:
                pass
            return workers_on_master

        def create_workers(workers_to_create):
            current_workers_old = set(self.backend.workers)
            futures = []
            with ThreadPoolExecutor(workers_to_create+1) as ex:
                futures.append(ex.submit(start_master_instance, wait=False))
                for vm_n in range(workers_to_create):
                    worker_id = "{:04d}".format(vm_n)
                    name = 'lithops-worker-{}-{}-{}'.format(executor_id, job_id, worker_id)
                    ex.submit(self.backend.create_worker, name)
            for future in concurrent.futures.as_completed(futures):
                future.result()

            current_workers_new = set(self.backend.workers)
            new_workers = current_workers_new - current_workers_old
            logger.debug("Total worker VM instances created: {}/{}"
                         .format(len(new_workers), workers_to_create))

            return list(new_workers)

        def wait_workers_ready(workers_num):
            logger.info(f'Waiting {workers_num} workers to become ready')

            start = time.time()
            workers_state_on_master = {}
            while(time.time() - start < self.start_timeout * 2):
                try:
                    cmd = (f'curl -X GET http://127.0.0.1:{STANDALONE_SERVICE_PORT}/workers-state '
                        '-H \'Content-Type: application/json\'')
                    resp = self.backend.master.get_ssh_client().run_remote_command(cmd)
                    prev = workers_state_on_master

                    workers_state_on_master = json.loads(resp)

                    running = 0
                    if prev != workers_state_on_master:
                        logger.debug(f'Workers state from master: {workers_state_on_master}')

                        msg = 'Workers states: '
                        for w in workers_state_on_master:
                            w_state = workers_state_on_master[w]["state"]
                            msg += f'({w} - {w_state})'
                            if w_state == 'running':
                                running += 1

                        logger.info(msg)

                    if running >= workers_num:
                        logger.info(f'All {workers_num} workers are ready')

                        # on backend, in case workers failed to get optimal workers setup, they may run
                        # but in order to notify user they will have running state, but 'err' containing error
                        for w in workers_state_on_master:
                            if workers_state_on_master[w]["state"] == 'running' and  workers_state_on_master[w].get('err'):
                                logger.warning('Workers may operate not in desired configuration, worker {w} error: {workers_state_on_master[w].get("err")}')
                        return

                except LithopsValidationError as e:
                    breakpoint()
                    raise e
                except Exception as e:
                    breakpoint()
                    pass

                time.sleep(10)

            raise Exception('Lithops service readiness probe expired on {}'
                        .format(self.backend.master))

        worker_instances = []

        if self.exec_mode == 'consume':
            total_workers = total_required_workers

        elif self.exec_mode == 'create':
            new_workers = create_workers(total_required_workers)
            total_workers = len(new_workers)
            worker_instances = [(inst.name,
                                 inst.ip_address,
                                 inst.instance_id,
                                 inst.ssh_credentials)
                                for inst in new_workers]

        elif self.exec_mode == 'reuse':
            workers = get_workers_on_master()
            total_started_workers = len(workers)
            logger.debug(f"Found {total_started_workers} free workers connected to master {self.backend.master}")
            if total_started_workers < total_required_workers:
                # create missing delta of workers
                workers_to_create = total_required_workers - total_started_workers
                logger.debug(f'Going to create {workers_to_create} new workers')
                new_workers = create_workers(workers_to_create)
                total_workers = len(new_workers) + total_started_workers
                worker_instances = [(inst.name,
                                     inst.ip_address,
                                     inst.instance_id,
                                     inst.ssh_credentials)
                                    for inst in new_workers]
            else:
                total_workers = total_started_workers

        if total_workers == 0:
            raise Exception('It was not possible to create any worker')

        logger.debug('ExecutorID {} | JobID {} - Going to run {} activations '
                     'in {} workers'.format(executor_id, job_id, total_calls,
                                            min(total_workers, total_required_workers)))

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
        wait_workers_ready(total_required_workers)

    def create_runtime(self, runtime_name, *args):
        """
        Installs the proxy and extracts the runtime metadata and
        preinstalled modules
        """
        logger.debug('Checking if {} is ready'.format(self.backend.master))
        if not self._is_master_instance_ready():
            logger.debug('{} not ready'.format(self.backend.master))
            self.backend.master.create(check_if_exists=True)
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

    def clean(self, **kwargs):
        """
        Clan all the backend resources
        """
        self.backend.clean(**kwargs)

    def clear(self, job_keys=None):
        """
        Clear all the backend resources.
        clear method is executed after the results are get,
        when an exception is produced, or when a user press ctrl+c
        """
        cmd = ('curl http://127.0.0.1:{}/stop -d {} '
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
        logger.info('Installing Lithops in {}'.format(self.backend.master))
        ssh_client = self.backend.master.get_ssh_client()

        worker_path = os.path.join(os.path.dirname(__file__), 'worker.py')
        master_path = os.path.join(os.path.dirname(__file__), 'master.py')
        create_handler_zip(LOCAL_FH_ZIP_LOCATION, [master_path, worker_path])

        logger.debug('Uploading lithops files to {}'.format(self.backend.master))
        ssh_client.upload_local_file(LOCAL_FH_ZIP_LOCATION, '/tmp/lithops_standalone.zip')
        os.remove(LOCAL_FH_ZIP_LOCATION)

        vm_data = {'instance_name': self.backend.master.name,
                   'ip_address': self.backend.master.ip_address,
                   'instance_id': self.backend.master.instance_id,
                   'lithops_version': lithops_version
                   }

        logger.debug('Executing lithops installation process on {}'.format(self.backend.master))
        logger.debug('Be patient, initial installation process may take up to 3 minutes')

        remote_script = "/tmp/install_lithops.sh"
        script = get_master_setup_script(self.config, vm_data)
        ssh_client.upload_data_to_file(script, remote_script)
        ssh_client.run_remote_command(f"chmod 777 {remote_script}; sudo {remote_script};")

