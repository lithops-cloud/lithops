import os
import sys
import uuid
import pkgutil
import logging
import multiprocessing
from pywren_ibm_cloud.version import __version__
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.function import function_handler
from .config import LOCAL_LOGS_DIR

logger = logging.getLogger(__name__)


class LocalhostBackend:
    """
    A wrap-up around Localhost multiprocessing APIs.
    """

    def __init__(self, local_config):
        self.log_level = os.getenv('PYWREN_LOGLEVEL')
        self.config = local_config
        self.name = 'local'
        self.queue = multiprocessing.Queue()
        self.logs_dir = LOCAL_LOGS_DIR
        self.workers = self.config['workers']

        for worker_id in range(self.workers):
            p = multiprocessing.Process(target=self._process_runner, args=(worker_id,))
            p.daemon = True
            p.start()

        log_msg = 'PyWren v{} init for Localhost - Total workers: {}'.format(__version__, self.workers)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

    def _local_handler(self, event, original_dir):
        """
        Handler to run local functions.
        """
        current_run_dir = os.path.join(self.logs_dir, event['executor_id'], event['job_id'])
        os.makedirs(current_run_dir, exist_ok=True)
        os.chdir(current_run_dir)
        old_stdout = sys.stdout
        sys.stdout = open('{}.log'.format(event['call_id']), 'w')

        event['extra_env']['LOCAL_EXECUTION'] = 'True'
        function_handler(event)

        os.chdir(original_dir)
        sys.stdout = old_stdout

    def _process_runner(self, worker_id):
        logger.debug('Localhost worker process {} started'.format(worker_id))
        while True:
            try:
                event = self.queue.get(block=True)
                self._local_handler(event, os.getcwd())
            except KeyboardInterrupt:
                break

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
        self.queue.put(payload)
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
        return []

    def get_runtime_key(self, runtime_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know what runtimes are installed and what not.
        """
        runtime_key = '{}_{}MB'.format(runtime_name, str(runtime_memory))
        runtime_key = os.path.join(self.name, runtime_key)

        return runtime_key
