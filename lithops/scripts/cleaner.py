#
# Copyright Cloudlab URV 2021
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
import sys
import time
import pickle
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lithops.storage import Storage
from lithops.storage.utils import clean_bucket
from lithops.constants import JOBS_PREFIX, TEMP_PREFIX, CLEANER_DIR, \
    CLEANER_PID_FILE, CLEANER_LOG_FILE, CLEANER_TMP_SUFFIX

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:  # everything but Windows
    msvcrt = None

logger = logging.getLogger('lithops')

_SKIP_FILES = {CLEANER_LOG_FILE, CLEANER_PID_FILE}

# After the last request, wait once more so a parallel job can drop its file
# before this process exits and releases the lock
_IDLE_CONFIRM_SECONDS = 2

# A cleaner that finds the lock taken keeps trying for this long, but only
# while there is something pending: the cleaner holding it may be exiting
_LOCK_RETRY_SECONDS = 10
_LOCK_RETRY_INTERVAL = 0.5

# One pickled request dropped in CLEANER_DIR: where the file lives on disk
# and the payload describing what it asks to be deleted
CleanerEntry = Dict[str, Any]


def _configure_cleaner_logging() -> None:
    """Redirect process output into the cleaner log (subprocess only)."""
    os.makedirs(CLEANER_DIR, exist_ok=True)
    log_file_stream = open(CLEANER_LOG_FILE, 'a')
    sys.stdout = log_file_stream
    sys.stderr = log_file_stream
    logging.basicConfig(
        stream=log_file_stream,
        level=logging.INFO,
        format=(
            '%(asctime)s [%(levelname)s] %(module)s [%(threadName)s] - '
            '%(funcName)s: %(message)s'
        ),
    )
    logger.setLevel(logging.DEBUG)


def _remove_if_exists(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _lock_pid_file() -> Optional[int]:
    """
    Takes the machine wide cleaner lock, returning the open descriptor of the
    pid file, or None when another cleaner already holds it.

    The lock belongs to the process, not to the contents of the file: the
    operating system drops it as soon as this process ends, so a cleaner that
    is killed cannot block the next one, and there is no stale pid to detect.
    The pid is written for diagnostics only, and the file is never removed:
    unlinking it would leave this process holding a lock on an inode nobody
    can see, and let a second cleaner lock a fresh file at the same path.
    """
    os.makedirs(CLEANER_DIR, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_BINARY', 0)
    pid_fd = os.open(CLEANER_PID_FILE, flags)
    try:
        if fcntl is not None:
            fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:
            msvcrt.locking(pid_fd, msvcrt.LK_NBLCK, 1)
        # On a platform with neither there is no lock to take, and every
        # cleaner runs. They honour the same requests, which is wasteful
        # but not wrong: each one is removed by whoever gets to it first
    except OSError:
        os.close(pid_fd)
        return None

    try:
        os.truncate(pid_fd, 0)
        os.write(pid_fd, str(os.getpid()).encode())
    except OSError:
        # The pid is only there to be read by a human. The lock is taken
        # either way, and failing to note it down must not end the cleaner
        logger.debug('Could not write the cleaner pid', exc_info=True)
    return pid_fd


def _acquire_cleaner_lock() -> Optional[int]:
    """
    Takes the cleaner lock, retrying for a short while when it is held and
    there are requests pending. The cleaner holding it normally honours them,
    but it may be on its way out, and then nobody else would pick them up
    """
    deadline = time.monotonic() + _LOCK_RETRY_SECONDS
    while True:
        pid_fd = _lock_pid_file()
        if pid_fd is not None:
            return pid_fd
        if not _pending_request_files() or time.monotonic() >= deadline:
            return None
        time.sleep(_LOCK_RETRY_INTERVAL)


def _clean_job_prefixes(
    storage: Storage, root_prefix: str, job_keys: Iterable[str], what: str
) -> None:
    """
    Deletes everything each job stored under the given top level prefix
    """
    for job_key in job_keys:
        prefix = '/'.join([root_prefix, job_key]) + '/'
        logger.debug(f"Cleaning {what} from {prefix}")
        clean_bucket(storage, storage.bucket, prefix)


def clean_executor_jobs(
    executor_id: str, executor_data: List[CleanerEntry]
) -> None:
    """
    Deletes the data left behind by the jobs of a single executor. Every
    entry targets the same executor, so one Storage client serves them all
    """
    storage = None
    logger.debug(f"Cleaning Executor ID: {executor_id}")

    for file_data in executor_data:
        file_location = file_data['file_location']
        data = file_data['data']

        logger.debug(f"File location: {file_location}")

        if storage is None:
            storage = Storage(storage_config=data['storage_config'])

        _clean_job_prefixes(
            storage, JOBS_PREFIX, data['jobs_to_clean'], 'data'
        )
        if data['clean_cloudobjects']:
            _clean_job_prefixes(
                storage, TEMP_PREFIX, data['jobs_to_clean'], 'cloudobjects'
            )

        _remove_if_exists(file_location)
        logger.info('Finished')


def clean_cloudobjects(cloudobjects_data: CleanerEntry) -> None:
    """
    Deletes the cloudobjects of a request, skipping the ones that live in a
    storage backend other than the one the request was created with
    """
    file_location = cloudobjects_data['file_location']
    data = cloudobjects_data['data']

    logger.info('Going to clean cloudobjects')
    storage = Storage(storage_config=data['storage_config'])

    for co in data['cos_to_clean']:
        if co.backend == storage.backend:
            logger.info(f'Cleaning {co.backend}://{co.bucket}/{co.key}')
            storage.delete_object(co.bucket, co.key)

    _remove_if_exists(file_location)
    logger.info('Finished')


def clean_functions(functions_data: CleanerEntry) -> None:
    """
    Deletes the serialized functions an executor uploaded
    """
    file_location = functions_data['file_location']
    data = functions_data['data']

    storage = Storage(storage_config=data['storage_config'])
    prefix = '/'.join([JOBS_PREFIX, data['fn_to_clean']]) + '/'
    logger.info(f'Cleaning functions from {prefix}')
    key_list = storage.list_keys(storage.bucket, prefix)
    storage.delete_objects(storage.bucket, key_list)

    _remove_if_exists(file_location)
    logger.info('Finished')


def _load_cleaner_file(file_location: str) -> Dict[str, Any]:
    with open(file_location, 'rb') as pk:
        return pickle.load(pk)


def _executor_id_from_jobs(jobs_to_clean: Iterable[str]) -> Optional[str]:
    """
    Derives the executor id of a job key, which is the key minus its job
    number. Returns None when there is no job to derive it from
    """
    first_key = next(iter(jobs_to_clean), None)
    if not first_key:
        return None
    return first_key.rsplit('-', 1)[0]


def _classify_cleaner_files(
    files_to_clean: List[str]
) -> Tuple[Dict[str, List[CleanerEntry]], List[CleanerEntry], List[CleanerEntry]]:
    """
    Reads every pending request and sorts it by the kind of data it asks to
    delete, grouping the job requests by executor so that they share a client
    """
    executor_jobs: Dict[str, List[CleanerEntry]] = {}
    cloudobjects: List[CleanerEntry] = []
    functions: List[CleanerEntry] = []

    for file_name in files_to_clean:
        file_location = os.path.join(CLEANER_DIR, file_name)
        if file_location in _SKIP_FILES:
            continue

        try:
            data = _load_cleaner_file(file_location)
        except FileNotFoundError:
            # Honoured between the listing and the read
            continue
        except Exception:
            # A request nobody can read is dropped rather than retried: it
            # would otherwise be picked up on every pass, and the loop below
            # would never see an empty directory again
            logger.warning(
                f'Discarding unreadable request {file_location}',
                exc_info=True
            )
            _remove_if_exists(file_location)
            continue

        entry = {'file_location': file_location, 'data': data}

        if not isinstance(data, dict):
            logger.warning(f'Discarding {file_location}: not a request')
            _remove_if_exists(file_location)
        elif 'jobs_to_clean' in data:
            executor_id = _executor_id_from_jobs(data['jobs_to_clean'])
            if executor_id is None:
                logger.warning(
                    f'Skipping {file_location}: jobs_to_clean is empty'
                )
                _remove_if_exists(file_location)
                continue
            executor_jobs.setdefault(executor_id, []).append(entry)
        elif 'cos_to_clean' in data:
            cloudobjects.append(entry)
        elif 'fn_to_clean' in data:
            functions.append(entry)
        else:
            logger.warning(
                f'Discarding {file_location}: unknown request {sorted(data)}'
            )
            _remove_if_exists(file_location)

    return executor_jobs, cloudobjects, functions


def _run_clean_tasks(
    executor_jobs: Dict[str, List[CleanerEntry]],
    cloudobjects: List[CleanerEntry],
    functions: List[CleanerEntry],
) -> None:
    """
    Runs every classified request in parallel and waits for all of them,
    re-raising the first failure so that it is not silently swallowed
    """
    tasks = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        for executor_id, jobs in executor_jobs.items():
            tasks.append(ex.submit(clean_executor_jobs, executor_id, jobs))
        for item in cloudobjects:
            tasks.append(ex.submit(clean_cloudobjects, item))
        for item in functions:
            tasks.append(ex.submit(clean_functions, item))
        for task in tasks:
            task.result()


def _pending_request_files() -> List[str]:
    """
    Lists the request files waiting in CLEANER_DIR, leaving out the log and
    the pid file, which are not requests and may or may not be there, and
    the staging files of a request another process is still writing
    """
    try:
        file_names = os.listdir(CLEANER_DIR)
    except FileNotFoundError:
        return []

    return [
        file_name for file_name in file_names
        if not file_name.endswith(CLEANER_TMP_SUFFIX)
        and os.path.join(CLEANER_DIR, file_name) not in _SKIP_FILES
    ]


def clean() -> None:
    """
    Processes the pending requests until none is left. After a quiet poll,
    wait once more so a parallel Lithops command can still drop a request
    before this process exits.
    """
    while True:
        files_to_clean = _pending_request_files()
        if not files_to_clean:
            time.sleep(_IDLE_CONFIRM_SECONDS)
            files_to_clean = _pending_request_files()
            if not files_to_clean:
                break

        executor_jobs, cloudobjects, functions = _classify_cleaner_files(
            files_to_clean
        )
        _run_clean_tasks(executor_jobs, cloudobjects, functions)
        time.sleep(5)


def main() -> None:
    """
    Entry point of the cleaner process. One cleaner serves every Lithops
    command on this machine, so a run that cannot take the lock exits and
    lets the one holding it honour the requests of them all
    """
    pid_fd = _acquire_cleaner_lock()
    if pid_fd is None:
        return

    _configure_cleaner_logging()
    logger.info("Starting Job and Cloudobject Cleaner")
    try:
        clean()
    finally:
        # Closing drops the lock, which is what lets the next cleaner start.
        # The pid file itself stays, see _lock_pid_file()
        os.close(pid_fd)
    logger.info("Job and Cloudobject Cleaner finished")


if __name__ == '__main__':
    main()
