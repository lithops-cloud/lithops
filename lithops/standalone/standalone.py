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
import select
import logging
import urllib3
import importlib
import requests
from threading import Thread

from lithops.utils import is_lithops_worker, create_handler_zip
from lithops.constants import LOGS_DIR, REMOTE_INSTALL_DIR, FN_LOG_FILE
from lithops.storage.utils import create_job_key

urllib3.disable_warnings()

logger = logging.getLogger(__name__)
FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_standalone.zip')

PROXY_SERVICE_NAME = 'lithopsproxy.service'
PROXY_SERVICE_PORT = 8080
PROXY_SERVICE_FILE = """
[Unit]
Description=Lithops Proxy
After=network.target

[Service]
ExecStart=/usr/bin/python3 {}/proxy.py
Restart=always

[Install]
WantedBy=multi-user.target
""".format(REMOTE_INSTALL_DIR)


class StandaloneHandler:
    """
    A StandaloneHandler object is used by invokers and other components to access
    underlying standalone backend without exposing the implementation details.
    """

    def __init__(self, standalone_config):
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.config = standalone_config
        self.backend_name = self.config['backend']
        self.runtime = self.config['runtime']
        self.is_lithops_worker = is_lithops_worker()

        self.start_timeout = self.config.get('start_timeout', 300)

        self.auto_dismantle = self.config.get('auto_dismantle')
        self.hard_dismantle_timeout = self.config.get('hard_dismantle_timeout')
        self.soft_dismantle_timeout = self.config.get('soft_dismantle_timeout')

        # self.cpu = self.config.get('cpu', 2)
        # self.memory = self.config.get('memory', 4)
        # self.instances = self.config.get('instances', 1)

        try:
            module_location = 'lithops.standalone.backends.{}'.format(self.backend_name)
            sb_module = importlib.import_module(module_location)
            StandaloneBackend = getattr(sb_module, 'StandaloneBackend')
            self.backend = StandaloneBackend(self.config[self.backend_name])

        except Exception as e:
            logger.error("There was an error trying to create the "
                         "{} standalone backend".format(self.backend_name))
            raise e

        self.log_monitors = {}

        self.ssh_credentials = self.backend.get_ssh_credentials()
        self.ip_address = self.backend.get_ip_address()

        from lithops.util.ssh_client import SSHClient
        self.ssh_client = SSHClient(self.ssh_credentials)

        logger.debug("Standalone handler created successfully")

    def _is_backend_ready(self):
        """
        Checks if the VM instance is ready to receive ssh connections
        """
        try:
            self.ssh_client.run_remote_command(self.ip_address, 'id', timeout=2)
        except Exception:
            return False
        return True

    def _wait_backend_ready(self):
        """
        Waits until the VM instance is ready to receive ssh connections
        """
        logger.info('Waiting VM instance to become ready')

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_backend_ready():
                return True
            time.sleep(1)

        self.dismantle()
        raise Exception('VM readiness probe expired. Check your VM')

    def _start_backend(self):
        if not self._is_backend_ready():
            # The VM instance is stopped
            init_time = time.time()
            self.backend.start()
            self._wait_backend_ready()
            total_start_time = round(time.time()-init_time, 2)
            logger.info('VM instance ready in {} seconds'.format(total_start_time))

    def _is_proxy_ready(self):
        """
        Checks if the proxy is ready to receive http connections
        """
        try:
            if self.is_lithops_worker:
                url = "http://{}:{}/ping".format('127.0.0.1', PROXY_SERVICE_PORT)
                r = requests.get(url, timeout=1, verify=True)
                if r.status_code == 200:
                    return True
                return False
            else:
                cmd = 'curl -X GET http://127.0.0.1:8080/ping'
                out = self.ssh_client.run_remote_command(self.ip_address, cmd, timeout=2)
                data = json.loads(out)
                if data['response'] == 'pong':
                    return True
        except Exception:
            return False

    def _wait_proxy_ready(self):
        """
        Waits until the proxy is ready to receive http connections
        """
        logger.info('Waiting Lithops proxy to become ready')

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_proxy_ready():
                return True
            time.sleep(1)

        self.dismantle()
        raise Exception('Proxy readiness probe expired. Check your VM')

    def _start_log_monitor(self, executor_id, job_id):
        """
        Starts a process that polls the remote log into a local file
        """

        job_key = create_job_key(executor_id, job_id)

        def log_monitor():
            os.makedirs(LOGS_DIR, exist_ok=True)
            log_file = os.path.join(LOGS_DIR, job_key+'.log')
            fdout_0 = open(log_file, 'wb')
            fdout_1 = open(FN_LOG_FILE, 'ab')

            ssh_client = self.ssh_client.create_client(self.ip_address)
            cmd = 'tail -n +1 -F /tmp/lithops/logs/{}.log'.format(job_key)
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            channel = stdout.channel
            stdin.close()
            channel.shutdown_write()

            data = None
            while not channel.closed:
                try:
                    readq, _, _ = select.select([channel], [], [], 10)
                    if readq and readq[0].recv_ready():
                        data = channel.recv(len(readq[0].in_buffer))
                        fdout_0.write(data)
                        fdout_0.flush()
                        fdout_1.write(data)
                        fdout_1.flush()
                    else:
                        if data:
                            cmd = 'ls /tmp/lithops/jobs/{}.done'.format(job_key)
                            _, out, _ = ssh_client.exec_command(cmd)
                            if out.read().decode().strip():
                                break
                        time.sleep(0.5)
                except Exception:
                    pass

        if not self.is_lithops_worker:
            Thread(target=log_monitor, daemon=True).start()
            logger.debug('ExecutorID {} | JobID {} - Remote log monitor '
                         'started'.format(executor_id, job_id))

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        job_key = create_job_key(executor_id, job_id)
        log_file = os.path.join(LOGS_DIR, job_key+'.log')

        if not self._is_proxy_ready():
            # The VM instance is stopped
            if not self.log_active:
                print('ExecutorID {} - Starting VM instance' .format(executor_id))
            init_time = time.time()
            self.backend.start()
            self._wait_proxy_ready()
            total_start_time = round(time.time()-init_time, 2)
            logger.info('VM instance ready in {} seconds'.format(total_start_time))

        self._start_log_monitor(executor_id, job_id)

        logger.info('ExecutorID {} | JobID {} - Running job'
                    .format(executor_id, job_id))
        logger.info("View execution logs at {}".format(log_file))

        if self.is_lithops_worker:
            url = "http://{}:{}/run".format('127.0.0.1', PROXY_SERVICE_PORT)
            r = requests.post(url, data=json.dumps(job_payload), verify=True)
            response = r.json()
        else:
            cmd = ('curl -X POST http://127.0.0.1:8080/run -d \'{}\' '
                   '-H \'Content-Type: application/json\''.format(json.dumps(job_payload)))
            out = self.ssh_client.run_remote_command(self.ip_address, cmd)
            response = json.loads(out)

        return response['activationId']

    def create_runtime(self, runtime):
        """
        Installs the proxy and extracts the runtime metadata and
        preinstalled modules
        """
        self._start_backend()
        self._setup_proxy()
        self._wait_proxy_ready()

        logger.info('Extracting runtime metadata information')
        payload = {'runtime': runtime}

        if self.is_lithops_worker:
            url = "http://{}:{}/preinstalls".format('127.0.0.1', PROXY_SERVICE_PORT)
            r = requests.get(url, data=json.dumps(payload), verify=True)
            runtime_meta = r.json()
        else:
            cmd = ('curl -X GET http://127.0.0.1:8080/preinstalls -d \'{}\' '
                   '-H \'Content-Type: application/json\''.format(json.dumps(payload)))
            out = self.ssh_client.run_remote_command(self.ip_address, cmd)
            runtime_meta = json.loads(out)

        return runtime_meta

    def get_runtime_key(self, runtime_name):
        """
        Wrapper method that returns a formated string that represents the
        runtime key. Each backend has its own runtime key format. Used to
        store modules preinstalls into the storage
        """
        return self.backend.get_runtime_key(runtime_name)

    def dismantle(self):
        """
        Stop VM instance
        """
        self.backend.stop()

    def init(self):
        """
        Start the VM instance and initialize runtime
        """
        self._start_backend()

        # Not sure if mandatory, but sleep several seconds to let proxy server start
        time.sleep(2)

        # if proxy not started, install it
        if not self._is_proxy_ready():
            self._setup_proxy()

        self._wait_proxy_ready()

    def clean(self):
        pass

    def _setup_proxy(self):
        logger.info('Installing Lithops proxy in the VM instance')
        logger.debug('Be patient, installation process can take up to 3 minutes '
                     'if this is the first time you use the VM instance')

        service_file = '/etc/systemd/system/{}'.format(PROXY_SERVICE_NAME)
        self.ssh_client.upload_data_to_file(self.ip_address, PROXY_SERVICE_FILE, service_file)

        cmd = 'rm -R {}; mkdir -p {}; '.format(REMOTE_INSTALL_DIR, REMOTE_INSTALL_DIR)
        cmd += 'systemctl daemon-reload; systemctl stop {}; '.format(PROXY_SERVICE_NAME)
        self.ssh_client.run_remote_command(self.ip_address, cmd)

        config_file = os.path.join(REMOTE_INSTALL_DIR, 'config')
        self.ssh_client.upload_data_to_file(self.ip_address, json.dumps(self.config), config_file)

        src_proxy = os.path.join(os.path.dirname(__file__), 'proxy.py')
        create_handler_zip(FH_ZIP_LOCATION, src_proxy)
        self.ssh_client.upload_local_file(self.ip_address, FH_ZIP_LOCATION, '/tmp/lithops_standalone.zip')
        os.remove(FH_ZIP_LOCATION)

        # Install dependenices
        cmd = 'apt-get update; apt-get install unzip python3-pip -y; '
        cmd += 'pip3 install flask gevent pika==0.13.1; '
        cmd += 'unzip -o /tmp/lithops_standalone.zip -d {} > /dev/null 2>&1; '.format(REMOTE_INSTALL_DIR)
        cmd += 'rm /tmp/lithops_standalone.zip; '
        cmd += 'chmod 644 {}; '.format(service_file)
        # Start proxy service
        cmd += 'systemctl daemon-reload; '
        cmd += 'systemctl stop {}; '.format(PROXY_SERVICE_NAME)
        cmd += 'systemctl enable {}; '.format(PROXY_SERVICE_NAME)
        cmd += 'systemctl start {}; '.format(PROXY_SERVICE_NAME)
        self.ssh_client.run_remote_command(self.ip_address, cmd, background=True)
