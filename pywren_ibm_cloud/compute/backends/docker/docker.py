import os
import json
import sys
import uuid
import docker
import pkgutil
import logging
import tempfile
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.config import STORAGE_PREFIX_DEFAULT
from pywren_ibm_cloud.runtime.function_handler import function_handler
from pywren_ibm_cloud.version import __version__

logger = logging.getLogger(__name__)

TEMP = tempfile.gettempdir()
STORAGE_BASE_DIR = os.path.join(TEMP, STORAGE_PREFIX_DEFAULT)
LOCAL_RUN_DIR = os.path.join(os.getcwd(), 'pywren_jobs')


class DockerBackend:
    """
    A wrap-up around Docker APIs.
    """

    def __init__(self, docker_config):
        self.log_level = os.getenv('PYWREN_LOGLEVEL')
        self.config = docker_config
        self.name = 'docker'
        self.run_dir = LOCAL_RUN_DIR

        self.workers = self.config['workers']
        self.docker_client = docker.from_env()

        log_msg = 'PyWren v{} init for Docker - Total workers: {}'.format(__version__, self.workers)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

    def _local_handler(self, event, original_dir):
        """
        Handler to run local functions.
        """
        current_run_dir = os.path.join(LOCAL_RUN_DIR, event['executor_id'], event['job_id'])
        os.makedirs(current_run_dir, exist_ok=True)
        os.chdir(current_run_dir)
        old_stdout = sys.stdout
        sys.stdout = open('{}.log'.format(event['call_id']), 'w')

        event['extra_env']['LOCAL_EXECUTION'] = 'True'
        function_handler(event)

        os.chdir(original_dir)
        sys.stdout = old_stdout

    def _process_runner(self):
        while True:
            event = self.queue.get(block=True)
            self._local_handler(event, os.getcwd())

    def _generate_python_meta(self):
        """
        Extracts installed Python modules from the local machine
        """
        logger.debug("Extracting preinstalled Python modules...")
        runtime_meta = dict()
        mods = list(pkgutil.iter_modules())
        runtime_meta["preinstalls"] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
        runtime_meta["python_ver"] = version_str(sys.version_info)

        return runtime_meta

    def invoke(self, runtime_name, memory, payload):
        """
        Invoke the function with the payload. runtime_name and memory
        are not used since it runs in the local machine.
        """
        exec_id = payload['executor_id']
        job_id = payload['job_id']
        call_id = payload['call_id']

        payload_dir = os.path.join(STORAGE_BASE_DIR, exec_id, job_id, call_id)
        os.makedirs(payload_dir, exist_ok=True)
        payload_filename = os.path.join(payload_dir, 'payload.json')

        with open(payload_filename, "w") as f:
            f.write(json.dumps(payload))

        self.docker_client.containers.run(runtime_name, payload_filename, volumes=['/tmp:/tmp'], detach=True, auto_remove=True)

        act_id = str(uuid.uuid4()).replace('-', '')[:12]
        return act_id

    def invoke_with_result(self, runtime_name, memory, payload={}):
        """
        Invoke waiting for a result. Never called in this case
        """
        return self.invoke(runtime_name, memory, payload)

    def create_runtime(self, runtime_name, memory, timeout):
        """
        Extracts local python metadata. No need to create any runtime
        since it runs in the local machine
        """
        runtime_meta = self._generate_python_meta()

        return runtime_meta

    def build_runtime(self, runtime_name, dockerfile):
        """
        Pass. No need to build any runtime since it runs in the local machine
        """
        pass

    def delete_runtime(self, runtime_name, memory):
        """
        Pass. No runtime to delete since it runs in the local machine
        """
        pass

    def delete_all_runtimes(self):
        """
        Pass. No runtimes to delete since it runs in the local machine
        """
        pass

    def list_runtimes(self, runtime_name='all'):
        """
        Pass. No runtimes to list since it runs in the local machine
        """
        pass

    def get_runtime_key(self, runtime_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know what runtimes are installed and what not.
        """
        runtime_key = '{}_{}'.format(runtime_name, str(runtime_memory))

        return runtime_key
