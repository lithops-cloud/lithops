import os
import sys
import json
import pkgutil
import logging
import uuid
import time
import multiprocessing as mp
from pathlib import Path
from types import SimpleNamespace

from lithops.utils import version_str
from lithops.storage.utils import create_job_key
from lithops.worker import function_handler
from lithops.constants import LITHOPS_TEMP_DIR, JOBS_DIR, LOGS_DIR,\
    RN_LOG_FILE
from lithops import __version__, constants

os.makedirs(LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(JOBS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(filename=RN_LOG_FILE, level=logging.INFO,
                    format=constants.LOGGER_FORMAT)
logger = logging.getLogger('lithops.localhost.runner')

CPU_COUNT = mp.cpu_count()


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
        job_payload = SimpleNamespace(**json.load(jf))

    logger.info('ExecutorID {} | JobID {} - Starting execution'
                .format(job_payload.executor_id, job_payload.job_id))

    job = SimpleNamespace(**job_payload.job_description)

    call_ids = ["{:05d}".format(i) for i in range(job.total_calls)]
    payload = {'config': job_payload.config,
               'log_level': job_payload.log_level,
               'func_key': job.func_key,
               'data_key': job.data_key,
               'extra_env': job.extra_env,
               'execution_timeout': job.execution_timeout,
               'data_byte_ranges': job.data_ranges,
               'executor_id': job.executor_id,
               'job_id': job.job_id,
               'call_ids': call_ids,
               'host_submit_tstamp': time.time(),
               'lithops_version': __version__,
               'runtime_name': job.runtime_name,
               'runtime_memory': job.runtime_memory,
               'worker_granularity': CPU_COUNT}

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    os.environ['__LITHOPS_ACTIVATION_ID'] = act_id
    function_handler(payload)

    job_key = create_job_key(job_payload.executor_id, job_payload.job_id)
    done = os.path.join(JOBS_DIR, job_key+'.done')
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
