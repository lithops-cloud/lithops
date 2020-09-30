import os
import sys
import json
import logging
import uuid
from threading import Thread
from types import SimpleNamespace
from multiprocessing import Process, Queue
from lithops.utils import version_str, is_unix_system
from lithops.worker import function_handler
from lithops.config import TEMP_STORAGE_DIR, LOGS_PREFIX


log_file = os.path.join(TEMP_STORAGE_DIR, 'handler.log')
logging.basicConfig(filename=log_file, level=logging.DEBUG)
logger = logging.getLogger('handler')


class LocalhostHandler:
    """
    A wrap-up around Localhost multiprocessing APIs.
    """

    def __init__(self, local_config):
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.config = local_config
        self.name = 'local'
        self.alive = True
        self.queue = Queue()
        self.logs_dir = os.path.join(TEMP_STORAGE_DIR, LOGS_PREFIX)
        self.num_workers = self.config['workers']
        self.use_threads = not is_unix_system()

        self.workers = []

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

        event['extra_env']['__LITHOPS_LOCAL_EXECUTION'] = 'True'
        act_id = str(uuid.uuid4()).replace('-', '')[:12]
        os.environ['__PW_ACTIVATION_ID'] = act_id
        function_handler(event)

        if not self.log_active:
            sys.stdout = old_stdout

    def _process_runner(self, worker_id):
        logger.debug('Localhost worker process {} started'.format(worker_id))

        while True:
            event = self.queue.get(block=True)
            if event is None:
                break
            self._local_handler(event)


if __name__ == "__main__":
    logger.info('Starting Localhost job handler')
    job_filename = sys.argv[1]
    logger.info('Got {} job file'.format(job_filename))

    with open(job_filename, 'rb') as jf:
        job = SimpleNamespace(**json.load(jf))
