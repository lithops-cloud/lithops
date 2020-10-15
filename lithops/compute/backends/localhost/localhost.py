import atexit
import os
import sys
import uuid
import pkgutil
import logging
from multiprocessing import Process, Queue
from threading import Thread
from lithops.version import __version__
from lithops.utils import version_str, is_unix_system
from lithops.worker import function_handler
from lithops.config import STORAGE_FOLDER, LOGS_PREFIX

logger = logging.getLogger(__name__)


class LocalhostBackend:
    """
    A wrap-up around Localhost multiprocessing APIs.
    """

    def __init__(self, local_config, storage_config):
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.config = local_config
        self.name = 'local'
        self.alive = True
        self.queue = Queue()
        self.logs_dir = os.path.join(STORAGE_FOLDER, LOGS_PREFIX)
        self.num_workers = self.config['workers']
        self.use_threads = not is_unix_system()

        self.workers = []

        atexit.register(self.close)

        if self.use_threads:
            for worker_id in range(self.num_workers):
                p = Thread(target=self._process_runner, args=(worker_id,))
                self.workers.append(p)
                p.daemon = True
                p.start()
        else:
            for worker_id in range(self.num_workers):
                p = Process(target=self._process_runner, args=(worker_id,))
                self.workers.append(p)
                p.start()

        log_msg = 'Lithops v{} init for Localhost - Total workers: {}'.format(__version__, self.num_workers)
        logger.info(log_msg)
        if not self.log_active:
            print(log_msg)

    def _local_handler(self, event):
        """
        Handler to run local functions.
        """
        if not self.log_active:
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')

        event['extra_env']['__PW_LOCAL_EXECUTION'] = 'True'
        act_id = str(uuid.uuid4()).replace('-', '')[:12]
        os.environ['__PW_ACTIVATION_ID'] = act_id
        function_handler(event)

        if not self.log_active:
            sys.stdout = old_stdout

    def _process_runner(self, worker_id):
        logger.debug('Localhost worker process {} started'.format(worker_id))

        while self.alive:
            try:
                event = self.queue.get(block=True)
                if event is None:
                    break
                self._local_handler(event)
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
        return os.path.join(self.name, runtime_name)

    def close(self):
        if self.alive:
            self.alive = False
            for worker in self.workers:
                self.queue.put(None)

            # Clean up process-based workers in case any are stuck
            if not self.use_threads:
                for worker_id, worker in enumerate(self.workers):
                    if worker.is_alive():
                        logger.debug('Terminating worker process {}'.format(worker_id))
                        worker.terminate()

    def __del__(self):
        atexit.unregister(self.close)
        self.close()
