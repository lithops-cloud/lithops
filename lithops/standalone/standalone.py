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
from lithops.constants import STANDALONE_INSTALL_DIR, \
    SA_LOG_FILE, STANDALONE_SERVICE_PORT


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

        logger.debug("Standalone handler created successfully")

    def init(self):
        """
        Initialize the backend and create/start the master VM instance
        """
        self.backend.init()

    def _is_instance_ready(self):
        """
        Checks if the VM instance is ready to receive ssh connections
        """
        try:
            self.backend.master.get_ssh_client().run_remote_command('id')
        except Exception:
            return False
        return True

    def _wait_instance_ready(self):
        """
        Waits until the VM instance is ready to receive ssh connections
        """
        logger.debug('Waiting {} to become ready'.format(self.backend.master))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_instance_ready():
                logger.debug('{} ready in {} seconds'.format(self.backend.master,
                                                             round(time.time()-start, 2)))
                return True
            time.sleep(5)

        self.dismantle()
        raise Exception('SSH Readiness probe expired on {}'.format(self.backend.master))

    def _is_service_ready(self):
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

    def _wait_service_ready(self):
        """
        Waits until the proxy is ready to receive http connections
        """
        logger.info('Waiting Lithops to become ready on {}'.format(self.backend.master))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_service_ready():
                return True
            time.sleep(2)

        self.dismantle()
        raise Exception('Lithops readiness probe expired on {}'.format(self.backend.master))

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        total_calls = job_payload['total_calls']
        chunksize = job_payload['chunksize']

        if self.exec_mode == 'create':
            total_workers = total_calls // chunksize + (total_calls % chunksize > 0)
            logger.debug('ExecutorID {} | JobID {} - Going '
                         'to run {} activations in {} workers'
                         .format(executor_id, job_id,
                                 total_calls, total_workers))

            for vm_n in range(total_workers):
                worker_id = "{:04d}".format(vm_n)
                name = 'lithops-{}-{}-{}'.format(executor_id, job_id, worker_id)
                self.backend.create_worker(name)

            def _callback(future):
                # This callback is used to raise in-thread exceptions (if any)
                future.result()

            workers = self.backend.workers
            with ThreadPoolExecutor(len(workers)+1) as executor:
                future = executor.submit(lambda vm: vm.create(check_if_exists=True, start=True), self.backend.master)
                future.add_done_callback(_callback)
                for i in range(len(workers)):
                    future = executor.submit(lambda vm: vm.create(start=True), workers[i])
                    future.add_done_callback(_callback)
        else:
            logger.debug('ExecutorID {} | JobID {} - Going '
                         'to run {} activations in 1 worker'
                         .format(executor_id, job_id, total_calls,))

        logger.debug("Checking if {} is ready".format(self.backend.master))
        if not self._is_service_ready():
            logger.debug("{} not ready".format(self.backend.master))
            if self.exec_mode != 'create':
                self.backend.master.create(check_if_exists=True, start=True)
            # Wait only for the entry point instance
            self._wait_instance_ready()

        logger.debug('{} ready'.format(self.backend.master))

        if self.exec_mode == 'create':
            logger.debug('Be patient, VM startup time may take up to 2 minutes')
            worker_instances = [(inst.name, inst.ip_address, inst.instance_id) for inst in workers]
            job_payload['woreker_instances'] = worker_instances
            cmd = ('curl http://127.0.0.1:{}/run-create -d {} '
                   '-H \'Content-Type: application/json\' -X POST'
                   .format(STANDALONE_SERVICE_PORT,
                           shlex.quote(json.dumps(job_payload))))
        else:
            cmd = ('curl http://127.0.0.1:{}/run -d {} '
                   '-H \'Content-Type: application/json\' -X POST'
                   .format(STANDALONE_SERVICE_PORT,
                           shlex.quote(json.dumps(job_payload))))

        self.backend.master.get_ssh_client().run_remote_command(cmd, run_async=True)
        logger.debug('Job invoked on {}'.format(self.backend.master))

    def create_runtime(self, runtime):
        """
        Installs the proxy and extracts the runtime metadata and
        preinstalled modules
        """
        logger.debug('Checking if {} is ready'.format(self.backend.master))
        if not self._is_instance_ready():
            logger.debug('{} not ready'.format(self.backend.master))
            self.backend.master.create(check_if_exists=True, start=True)
            self._wait_instance_ready()

        self._setup_service()
        self._wait_service_ready()

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
        Clear all the backend resources
        """
        self.backend.clear()

    def get_runtime_key(self, runtime_name):
        """
        Wrapper method that returns a formated string that represents the
        runtime key. Each backend has its own runtime key format. Used to
        store modules preinstalls into the storage
        """
        return self.backend.get_runtime_key(runtime_name)

    def _setup_service(self):
        """
        Setup lithops necessary files and dirs in master VM instance
        """
        logger.debug('Installing Lithops in {}'.format(self.backend.master))
        ssh_client = self.backend.master.get_ssh_client()

        # Upload local lithops version to remote VM instance
        src_proxy = os.path.join(os.path.dirname(__file__), 'proxy.py')
        create_handler_zip(LOCAL_FH_ZIP_LOCATION, src_proxy)
        current_location = os.path.dirname(os.path.abspath(__file__))
        setup_location = os.path.join(current_location, 'master_setup.py')
        controller_location = os.path.join(current_location, 'controller.py')

        logger.debug('Uploading lithops files to {}'.format(self.backend.master))
        files_to_upload = [(LOCAL_FH_ZIP_LOCATION, '/tmp/lithops_standalone.zip'),
                           (setup_location, '/tmp/master_setup.py'.format(STANDALONE_INSTALL_DIR)),
                           (controller_location, '/tmp/controller.py'.format(STANDALONE_INSTALL_DIR))]

        ssh_client.upload_multiple_local_files(files_to_upload)
        os.remove(LOCAL_FH_ZIP_LOCATION)

        master_data = {'instance_name': self.backend.master.name,
                       'ip_address': self.backend.master.ip_address,
                       'instance_id': self.backend.master.instance_id}
        script = """
        mkdir -p /tmp/lithops;
        setup_host(){{
        mv {0}/access.data .;
        rm -R {0};
        mkdir -p {0};
        cp /tmp/lithops_standalone.zip {0};
        mv access.data {0}/access.data;
        test -f {0}/access.data || echo '{1}' > {0}/access.data;
        test -f {0}/config || echo '{2}' > {0}/config;
        mv /tmp/*.py '{0}';
        python3 {0}/master_setup.py;
        }}
        setup_host >> {3} 2>&1;
        """.format(STANDALONE_INSTALL_DIR, json.dumps(master_data),
                   json.dumps(self.config), SA_LOG_FILE)

        logger.debug('Executing lithops installation process on {}'.format(self.backend.master))
        logger.debug('Be patient, initial installation process may take up to 5 minutes')
        ssh_client.run_remote_command(script)
        logger.debug('Lithops installation process completed')
