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
        self.runtime = self.config['runtime']
        self.is_lithops_worker = is_lithops_worker()

        self.start_timeout = self.config.get('start_timeout', 300)
        self.auto_dismantle = self.config.get('auto_dismantle')
        self.hard_dismantle_timeout = self.config.get('hard_dismantle_timeout')
        self.soft_dismantle_timeout = self.config.get('soft_dismantle_timeout')
        self.pull_runtime = self.config.get('pull_runtime', True)
        self.exec_mode = self.config.get('exec_mode', 'consume')

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
        logger.debug('Waiting {} to become ready'
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

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        total_calls = job_payload['total_calls']
        chunksize = job_payload['chunksize']

        total_workers = total_calls // chunksize + (total_calls % chunksize > 0) \
            if self.exec_mode == 'create' else 1

        def start_master_instance(wait=True):
            if not self._is_master_service_ready():
                self.backend.master.create(check_if_exists=True, start=True)
                if wait:
                    self._wait_master_service_ready()

        if self.exec_mode == 'create':
            with ThreadPoolExecutor(total_workers+1) as ex:
                ex.submit(start_master_instance, wait=False)
                for vm_n in range(total_workers):
                    worker_id = "{:04d}".format(vm_n)
                    name = 'lithops-{}-{}-{}'.format(executor_id, job_id, worker_id)
                    ex.submit(self.backend.create_worker, name)

            logger.debug("Total worker VM instances created: {}/{}"
                         .format(len(self.backend.workers), total_workers))

        logger.debug('ExecutorID {} | JobID {} - Going '
                     'to run {} activations in {} workers'
                     .format(executor_id, job_id,
                             total_calls, len(self.backend.workers)))

        logger.debug("Checking if {} is ready".format(self.backend.master))
        start_master_instance(wait=True)

        if self.exec_mode == 'create':
            worker_instances = [(inst.name, inst.ip_address, inst.instance_id)
                                for inst in self.backend.workers]
            job_payload['worker_instances'] = worker_instances

        cmd = ('curl http://127.0.0.1:{}/run -d {} '
               '-H \'Content-Type: application/json\' -X POST'
               .format(STANDALONE_SERVICE_PORT,
                       shlex.quote(json.dumps(job_payload))))

        self.backend.master.get_ssh_client().run_remote_command(cmd)
        self.backend.master.del_ssh_client()
        logger.debug('Job invoked on {}'.format(self.backend.master))

        self.jobs.append(job_payload['job_key'])

    def create_runtime(self, runtime):
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
        payload = {'runtime': runtime, 'pull_runtime': self.pull_runtime}
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

    def clear(self):
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
        self.backend.clear()

    def get_runtime_key(self, runtime_name):
        """
        Wrapper method that returns a formated string that represents the
        runtime key. Each backend has its own runtime key format. Used to
        store modules preinstalls into the storage
        """
        return self.backend.get_runtime_key(runtime_name)

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
