import os
import io
import sys
import json
import pkgutil
import logging
import uuid
import time
import queue
import multiprocessing as mp
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from contextlib import redirect_stdout, redirect_stderr

from lithops.utils import version_str, is_unix_system, setup_logger
from lithops.storage.utils import create_job_key
from lithops.worker import function_handler
from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DONE_DIR, LOGS_DIR,\
    RN_LOG_FILE, FN_LOG_FILE
from lithops import __version__, constants

os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(JOBS_DONE_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(filename=RN_LOG_FILE, level=logging.INFO,
                    format=constants.LOGGER_FORMAT)
logger = logging.getLogger('runner')

CPU_COUNT = mp.cpu_count()


class ShutdownSentinel():
    """Put an instance of this class on the queue to shut it down"""
    pass


class Runner:
    """
    A wrap-up around Localhost multiprocessing APIs.
    """

    def __init__(self, config, executor_id, job_id):
        self.config = config
        self.executor_id = executor_id
        self.job_id = job_id
        self.use_threads = not is_unix_system()
        self.num_workers = self.config['lithops'].get('workers', CPU_COUNT)
        self.workers = []

        if self.use_threads:
            self.queue = queue.Queue()
            WORKER = Thread
        else:
            if 'fork' in mp.get_all_start_methods():
                mp.set_start_method('fork')
            self.queue = mp.Queue()
            WORKER = mp.Process

        for worker_id in range(self.num_workers):
            p = WORKER(target=self._process_runner, args=(worker_id,))
            self.workers.append(p)
            p.start()

        logger.info('ExecutorID {} | JobID {} - Localhost runner started '
                    '- {} workers'.format(self.executor_id,
                                          self.job_id,
                                          self.num_workers))

    def _process_runner(self, worker_id):
        logger.debug('Localhost worker process {} started'.format(worker_id))

        p_logger = logging.getLogger('lithops')

        while True:
            with io.StringIO() as buf,  redirect_stdout(buf), redirect_stderr(buf):
                try:
                    event = self.queue.get(block=True)
                    if isinstance(event, ShutdownSentinel):
                        break
                    act_id = str(uuid.uuid4()).replace('-', '')[:12]
                    os.environ['__LITHOPS_ACTIVATION_ID'] = act_id

                    executor_id = event['executor_id']
                    job_id = event['job_id']
                    setup_logger(event['log_level'])
                    p_logger.info("Lithops v{} - Starting execution".format(__version__))
                    event['extra_env']['__LITHOPS_LOCAL_EXECUTION'] = 'True'
                    function_handler(event)
                except KeyboardInterrupt:
                    break

                header = "Activation: '{}' ({})\n[\n".format(event['runtime_name'], act_id)
                tail = ']\n\n'
                output = buf.getvalue()
                output = output.replace('\n', '\n    ', output.count('\n')-1)

            job_key = create_job_key(executor_id, job_id)
            log_file = os.path.join(LOGS_DIR, job_key+'.log')
            with open(log_file, 'a') as lf:
                lf.write(header+'    '+output+tail)
            with open(FN_LOG_FILE, 'a') as lf:
                lf.write(header+'    '+output+tail)

    def _invoke(self, job, call_id, log_level):
        payload = {'config': self.config,
                   'log_level': log_level,
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
                   'runtime_memory': job.runtime_memory}

        self.queue.put(payload)

    def run(self, job_description, log_level):
        job = SimpleNamespace(**job_description)

        for i in range(job.total_calls):
            call_id = "{:05d}".format(i)
            self._invoke(job, call_id, log_level)

        for i in self.workers:
            self.queue.put(ShutdownSentinel())

    def wait(self):
        for worker in self.workers:
            worker.join()


def extract_runtime_meta():
    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta["preinstalls"] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
    runtime_meta["python_ver"] = version_str(sys.version_info)

    print(json.dumps(runtime_meta))


def run():
    log_file_stream = open(RN_LOG_FILE, 'a')
    sys.stdout = log_file_stream
    sys.stderr = log_file_stream

    job_filename = sys.argv[2]
    logger.info('Got {} job file'.format(job_filename))

    with open(job_filename, 'rb') as jf:
        job = SimpleNamespace(**json.load(jf))

    logger.info('ExecutorID {} | JobID {} - Starting execution'
                .format(job.executor_id, job.job_id))

    runner = Runner(job.config, job.executor_id, job.job_id)
    runner.run(job.job_description, job.log_level)
    runner.wait()

    job_key = create_job_key(job.executor_id, job.job_id)
    done = os.path.join(JOBS_DONE_DIR, job_key+'.done')
    Path(done).touch()

    if os.path.exists(job_filename):
        os.remove(job_filename)

    logger.info('ExecutorID {} | JobID {} - Execution Finished'
                .format(job.executor_id, job.job_id))


if __name__ == "__main__":
    logger.info('Starting Localhost job runner')
    command = sys.argv[1]
    logger.info('Received command: {}'.format(command))

    switcher = {
        'preinstalls': extract_runtime_meta,
        'run': run
    }

    func = switcher.get(command, lambda: "Invalid command")
    func()
