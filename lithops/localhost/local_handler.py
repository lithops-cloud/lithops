import os
import sys
import json
import pkgutil
import logging
import uuid
import time
import multiprocessing
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from multiprocessing import Process, Queue
from lithops.utils import version_str, is_unix_system
from lithops.worker import function_handler
from lithops.config import STORAGE_DIR, JOBS_DONE_DIR
from lithops import __version__

os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(JOBS_DONE_DIR, exist_ok=True)

log_file = os.path.join(STORAGE_DIR, 'local_handler.log')
logging.basicConfig(filename=log_file, level=logging.INFO)
logger = logging.getLogger('handler')

CPU_COUNT = multiprocessing.cpu_count()


def extract_runtime_meta():
    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta["preinstalls"] = [entry for entry in sorted([[mod, is_pkg]for _, mod, is_pkg in mods])]
    runtime_meta["python_ver"] = version_str(sys.version_info)

    print(json.dumps(runtime_meta))


class ShutdownSentinel():
    """Put an instance of this class on the queue to shut it down"""
    pass


class LocalhostExecutor:
    """
    A wrap-up around Localhost multiprocessing APIs.
    """

    def __init__(self, config, executor_id, job_id, log_level):

        logging.basicConfig(filename=log_file, level=log_level)

        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.config = config
        self.queue = Queue()
        self.use_threads = not is_unix_system()
        self.num_workers = self.config['lithops'].get('workers', CPU_COUNT)
        self.workers = []

        sys.stdout = open(log_file, 'a')
        sys.stderr = open(log_file, 'a')

        if self.use_threads:
            for worker_id in range(self.num_workers):
                p = Thread(target=self._process_runner, args=(worker_id,))
                self.workers.append(p)
                p.start()
        else:
            for worker_id in range(self.num_workers):
                p = Process(target=self._process_runner, args=(worker_id,))
                self.workers.append(p)
                p.start()

        logger.info('ExecutorID {} | JobID {} - Localhost Executor started - {} workers'
                    .format(job.executor_id, job.job_id, self.num_workers))

    def _process_runner(self, worker_id):
        logger.debug('Localhost worker process {} started'.format(worker_id))

        while True:
            event = self.queue.get(block=True)

            if isinstance(event, ShutdownSentinel):
                break

            act_id = str(uuid.uuid4()).replace('-', '')[:12]
            os.environ['__LITHOPS_ACTIVATION_ID'] = act_id
            event['extra_env']['__LITHOPS_LOCAL_EXECUTION'] = 'True'
            function_handler(event)

    def _invoke(self, job, call_id):
        payload = {'config': self.config,
                   'log_level': logging.getLevelName(logger.getEffectiveLevel()),
                   'func_key': job.func_key,
                   'data_key': job.data_key,
                   'extra_env': job.extra_env,
                   'execution_timeout': job.execution_timeout,
                   'data_byte_range': job.data_ranges[int(call_id)],
                   'executor_id': job.executor_id,
                   'job_id': job.job_id,
                   'call_id': call_id,
                   'host_submit_tstamp': time.time(),
                   'lithops_version': __version__,
                   'runtime_name': job.runtime_name,
                   'runtime_memory': job.runtime_memory,
                   'runtime_timeout': job.runtime_timeout}

        self.queue.put(payload)

    def run(self, job_description):
        job = SimpleNamespace(**job_description)

        for i in range(job.total_calls):
            call_id = "{:05d}".format(i)
            self._invoke(job, call_id)

        for i in self.workers:
            self.queue.put(ShutdownSentinel())

    def wait(self):
        for worker in self.workers:
            worker.join()


if __name__ == "__main__":
    logger.info('Starting Localhost job handler')
    command = sys.argv[1]
    logger.info('Received command: {}'.format(command))

    if command == 'preinstalls':
        extract_runtime_meta()

    elif command == 'run':
        job_filename = sys.argv[2]
        logger.info('Got {} job file'.format(job_filename))

        with open(job_filename, 'rb') as jf:
            job = SimpleNamespace(**json.load(jf))

        logger.info('ExecutorID {} | JobID {} - Starting execution'
                    .format(job.executor_id, job.job_id))
        localhost_execuor = LocalhostExecutor(job.config, job.executor_id,
                                              job.job_id, job.log_level)
        localhost_execuor.run(job.job_description)
        localhost_execuor.wait()

        sentinel = '{}/{}_{}.done'.format(JOBS_DONE_DIR,
                                          job.executor_id.replace('/', '-'),
                                          job.job_id)
        Path(sentinel).touch()

        logger.info('ExecutorID {} | JobID {} - Execution Finished'
                    .format(job.executor_id, job.job_id))
