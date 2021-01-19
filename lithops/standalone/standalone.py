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
import shlex
import json
import time
import select
import logging
import importlib
import requests
import copy
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

from lithops.utils import is_lithops_worker, create_handler_zip
from lithops.constants import LOGS_DIR, REMOTE_INSTALL_DIR, FN_LOG_FILE
from lithops.storage.utils import create_job_key

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
        self.config = standalone_config
        self.backend_name = self.config['backend']
        self.runtime = self.config['runtime']
        self.is_lithops_worker = is_lithops_worker()

        self.start_timeout = self.config.get('start_timeout', 300)

        self.auto_dismantle = self.config.get('auto_dismantle')
        self.disable_log_monitoring = self.config.get('disable_log_monitoring', 'False')
        self.hard_dismantle_timeout = self.config.get('hard_dismantle_timeout')
        self.soft_dismantle_timeout = self.config.get('soft_dismantle_timeout')
        self.module_location = 'lithops.standalone.backends.{}'.format(self.backend_name)

        backend = self.create_backend_handler()

        self.log_monitors = {}

        self.exec_mode = self.config.get('exec_mode', 'consume')
        self.backends = []
        self.provided_backed = False

        if self.exec_mode != 'create' and \
            backend.get_ip_address() is not None and \
            backend.get_instance_id() is not None:
                self.backends.append(backend)
                self.provided_backed = True

        logger.debug("Standalone handler created successfully")

    def _is_backend_ready(self, backend):
        """
        Checks if the VM instance is ready to receive ssh connections
        """
        try:
            backend.get_ssh_client().run_remote_command(backend.get_ip_address(), 'id', timeout=2)
        except Exception:
            return False
        return True

    def _wait_backend_ready(self, backend):
        """
        Waits until the VM instance is ready to receive ssh connections
        """
        logger.debug('Waiting VM instance {} to become ready'.format(backend.get_ip_address()))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_backend_ready(backend):
                return True

            time.sleep(2)

        self.dismantle()
        raise Exception('VM readiness {} probe expired. Check your VM'.format(backend.get_ip_address()))

    def _start_backend(self, backend):
        logger.debug("Starting backend {}".format(backend.get_ip_address()))
        init_time = time.time()
        backend.start()
        self._wait_backend_ready(backend)
        total_start_time = round(time.time()-init_time, 2)
        logger.info('VM instance {} ready in {} seconds'.format(backend.get_ip_address(), total_start_time))

    def _is_proxy_ready(self, backend):
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
                out = backend.get_ssh_client().run_remote_command(backend.get_ip_address(), cmd, timeout=2)
                data = json.loads(out)
                if data['response'] == 'pong':
                    return True
        except Exception:
            return False

    def _wait_proxy_ready(self, backend):
        """
        Waits until the proxy is ready to receive http connections
        """
        logger.info('Waiting Lithops proxy to become ready for {}'.format(backend.get_ip_address()))

        start = time.time()
        while(time.time() - start < self.start_timeout):
            if self._is_proxy_ready(backend):
                return True
            time.sleep(5)

        self.dismantle()
        raise Exception('Proxy readiness probe expired for {}. Check your VM'.format(backend.get_ip_address()))

    def _start_log_monitor(self, executor_id, job_id, backend):
        """
        Starts a process that polls the remote log into a local file
        """

        job_key = create_job_key(executor_id, job_id)

        def log_monitor():
            os.makedirs(LOGS_DIR, exist_ok=True)
            log_file = os.path.join(LOGS_DIR, job_key+'.log')
            fdout_0 = open(log_file, 'wb')
            fdout_1 = open(FN_LOG_FILE, 'ab')

            ssh_client = backend.get_ssh_client().create_client(backend.get_ip_address())
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

    def _thread_invoke(self, lock, job_key, call_id, job_payload):
        backend = self.create(lock, job_key, call_id)
        job_payload['job_description']['call_id'] = call_id
        logger.debug("thread invoke for {} : call id {}".format(backend.get_ip_address(), job_payload['job_description']['call_id']))
        self._single_invoke(backend, job_payload)

    def run_job(self, job_payload):
        """
        Run the job description against the selected environment
        """
        if self.provided_backed:
            return self._single_invoke(self.backends[0], job_payload)
        else:
            executor_id = job_payload['executor_id']
            job_id = job_payload['job_id']
            job_key = create_job_key(executor_id, job_id)
            executor = ThreadPoolExecutor(int(job_payload['job_description']['total_calls']))
            import threading
            lock = threading.Lock()
            for i in range(job_payload['job_description']['total_calls']):
                call_id = "{:05d}".format(i)
                executor.submit(self._thread_invoke, lock, job_key, call_id, copy.deepcopy(job_payload))

    def _single_invoke(self, backend, job_payload):
        logger.debug("_single_invoke - Thread invoke for {} ".format(backend.get_ip_address()))
        ip_address = backend.get_ip_address()
        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        job_key = create_job_key(executor_id, job_id)
        log_file = os.path.join(LOGS_DIR, job_key+'.log')

        logger.debug("_single_invoke - check if proxy ready for  {} ".format(ip_address))
        if not self._is_proxy_ready(backend):
            logger.debug("_single_invoke -  proxy {} stopped".format(ip_address))
            # The VM instance is stopped
            init_time = time.time()
            self._start_backend(backend)
            self._wait_proxy_ready(backend)
            total_start_time = round(time.time()-init_time, 2)
            logger.info('_single_invoke - VM instance ready in {} seconds'.format(total_start_time))

        logger.debug("_single_invoke - before starting log {} ".format(ip_address))
        if self.disable_log_monitoring == 'False':
            self._start_log_monitor(executor_id, job_id, backend)

        logger.info('ExecutorID {} | JobID {} - Running job'
                    .format(executor_id, job_id))
        logger.info("View execution logs at {}".format(log_file))

        if self.is_lithops_worker:
            url = "http://{}:{}/run".format('127.0.0.1', PROXY_SERVICE_PORT)
            r = requests.post(url, data=json.dumps(job_payload), verify=True)
            response = r.json()
        else:
            cmd = ('curl -X POST http://127.0.0.1:8080/run -d {} '
                   '-H \'Content-Type: application/json\''
                   .format(shlex.quote(json.dumps(job_payload))))
            out = backend.get_ssh_client().run_remote_command(ip_address, cmd)
            response = json.loads(out)

        return response['activationId']

    def create_runtime(self, runtime):
        """
        Installs the proxy and extracts the runtime metadata and
        preinstalled modules
        """
        if self.provided_backed:
            backend = self.backends[0]
            self._start_backend(backend)
            self._setup_proxy(backend)
            self._wait_proxy_ready(backend)
        else:
            backend = self.create(None, 'proxy', runtime)

        logger.debug('Extracting runtime metadata information')
        payload = {'runtime': runtime}

        if self.is_lithops_worker:
            url = "http://{}:{}/preinstalls".format('127.0.0.1', PROXY_SERVICE_PORT)
            r = requests.get(url, data=json.dumps(payload), verify=True)
            runtime_meta = r.json()
        else:
            cmd = ('curl http://127.0.0.1:8080/preinstalls -d {} '
                   '-H \'Content-Type: application/json\' -X GET'
                   .format(shlex.quote(json.dumps(payload))))
            out = backend.get_ssh_client().run_remote_command(backend.get_ip_address(), cmd)
            runtime_meta = json.loads(out)

        if not self.provided_backed:
            backend.stop()

        return runtime_meta

    def get_runtime_key(self, runtime_name):
        """
        Wrapper method that returns a formated string that represents the
        runtime key. Each backend has its own runtime key format. Used to
        store modules preinstalls into the storage
        """
        if len(self.backends) > 0:
            return self.backends[0].get_runtime_key(runtime_name)
        else:
            # return default
            return runtime_name.strip("/")

    def dismantle(self):
        """
        Stop VM instance
        """
        logger.info("Entering dismantle for length {}".format(len(self.backends)))
        for backend in self.backends:
            logger.debug("Dismantle {} for {}".format(backend.get_instance_id(), backend.get_ip_address()))
            backend.stop()

    def create_backend_handler(self, instance_id=None, ip_address=None):
        try:
            sb_module = importlib.import_module(self.module_location)
            StandaloneBackend = getattr(sb_module, 'StandaloneBackend')
            backend = StandaloneBackend(self.config[self.backend_name])
            if instance_id is not None:
                backend.set_instance_id(instance_id)
            if ip_address is not None:
                backend.set_ip_address(ip_address)

        except Exception as e:
            logger.error("There was an error trying to create the "
                         "{} standalone backend".format(self.backend_name))
            raise e
        return backend

    def create(self, lock, name_prefix, name_suffix):

        backend = self.create_backend_handler()
        backend.create(name_prefix, name_suffix)

        if lock is not None:
            lock.acquire()
        self.backends.append(backend)
        if lock is not None:
            lock.release()

        self._start_backend(backend)
        self._setup_proxy(backend)
        self._wait_proxy_ready(backend)

        return backend

    def clean(self):
        pass

    def clear(self):
        pass

    def _setup_proxy(self, backend):
        ip_address = backend.get_ip_address()
        logger.debug('Installing Lithops proxy in the VM instance {}'.format(ip_address))
        ssh_client = backend.get_ssh_client()

        service_file = '/etc/systemd/system/{}'.format(PROXY_SERVICE_NAME)
        logger.debug('Upload service file {} - started'.format(service_file))
        ssh_client.upload_data_to_file(ip_address, PROXY_SERVICE_FILE, service_file)
        logger.debug('Upload service file {} - completed'.format(service_file))

        cmd = 'rm -R {}; mkdir -p {}; '.format(REMOTE_INSTALL_DIR, REMOTE_INSTALL_DIR)
        ssh_client.run_remote_command(ip_address, cmd)

        config_file = os.path.join(REMOTE_INSTALL_DIR, 'config')
        ssh_client.upload_data_to_file(ip_address, json.dumps(self.config), config_file)

        src_proxy = os.path.join(os.path.dirname(__file__), 'proxy.py')
        FH_ZIP_LOCATION_IP = os.path.join(os.getcwd(), ip_address.replace('.', 'a') + 'lithops_standalone.zip')
        create_handler_zip(FH_ZIP_LOCATION_IP, src_proxy)
        logger.debug('Upload zip file to {} - start'.format(ip_address))
        ssh_client.upload_local_file(ip_address, FH_ZIP_LOCATION_IP, '/tmp/lithops_standalone.zip')
        logger.debug('Upload zip file to {} - completed'.format(ip_address))
        os.remove(FH_ZIP_LOCATION_IP)

        # Install dependenices
        if not backend.is_custom_image():
            logger.debug('Be patient, installation process can take up to 3 minutes '
             'since this is the first time you use the VM instance')

            cmd = 'mkdir -p /tmp/lithops; '
            cmd += 'sudo rm /var/lib/apt/lists/* -vf; '
            cmd += 'apt-get clean; '
            cmd += 'apt-get update >> /tmp/lithops/proxy.log; '
            cmd += 'apt-get install unzip python3-pip -y >> /tmp/lithops/proxy.log; '
            cmd += 'pip3 install flask gevent pika==0.13.1 cloudpickle tblib ps-mem ibm-vpc namegenerator >> /tmp/lithops/proxy.log; '
            logger.debug('Non custom image. Executing initial install for {}'.format(ip_address))
            ssh_client.run_remote_command(ip_address, cmd, timeout=300)

        cmd = 'mkdir -p /tmp/lithops; '
        cmd += 'touch {}/access.data; '.format(REMOTE_INSTALL_DIR)
        cmd += 'echo "{} {}" > {}/access.data; '.format(backend.get_ip_address(), backend.get_instance_id(), REMOTE_INSTALL_DIR)
        cmd += 'unzip -o /tmp/lithops_standalone.zip -d {} > /dev/null 2>&1; '.format(REMOTE_INSTALL_DIR)
        cmd += 'rm /tmp/lithops_standalone.zip; '
        cmd += 'chmod 644 {}; '.format(service_file)
        # Start proxy service
        cmd += 'systemctl daemon-reload; '
        cmd += 'systemctl stop {}; '.format(PROXY_SERVICE_NAME)
        cmd += 'systemctl enable {}; '.format(PROXY_SERVICE_NAME)
        cmd += 'systemctl start {}; '.format(PROXY_SERVICE_NAME)
        logger.debug('Executing main ssh for Lithops proxy to VM instance {}'.format(ip_address))
        ssh_client.run_remote_command(ip_address, cmd, timeout=300)
        logger.debug('Completed main ssh for Lithops proxy to VM instance {}'.format(ip_address))
