import signal
import logging
from functools import partial
from lithops.utils import is_unix_system, timeout_handler, is_notebook, is_lithops_worker
from lithops.storage import InternalStorage

from .storage import wait_storage
from .utils import ALL_COMPLETED


logger = logging.getLogger(__name__)


def wait(fs, throw_except=True, return_when=ALL_COMPLETED,
         download_results=False, timeout=None, THREADPOOL_SIZE=128,
         WAIT_DUR_SEC=1, internal_storage=None):
    """
    Wait for the Future instances (possibly created by different Executor instances)
    given by fs to complete. Returns a named 2-tuple of sets. The first set, named done,
    contains the futures that completed (finished or cancelled futures) before the wait
    completed. The second set, named not_done, contains the futures that did not complete
    (pending or running futures). timeout can be used to control the maximum number of
    seconds to wait before returning.

    :param fs: Futures list. Default None
    :param throw_except: Re-raise exception if call raised. Default True.
    :param return_when: One of `ALL_COMPLETED`, `ANY_COMPLETED`, `ALWAYS`
    :param download_results: Download results. Default false (Only get statuses)
    :param timeout: Timeout of waiting for results.
    :param THREADPOOL_SIZE: Number of threads to use. Default 64
    :param WAIT_DUR_SEC: Time interval between each check.

    :return: `(fs_done, fs_notdone)`
        where `fs_done` is a list of futures that have completed
        and `fs_notdone` is a list of futures that have not completed.
    :rtype: 2-tuple of list
    """
    if not internal_storage:
        internal_storage = InternalStorage(fs[0].storage_config)

    if type(fs) != list:
        fs = [fs]

    setup_progressbar = (not is_lithops_worker() and
                         logger.getEffectiveLevel() == logging.INFO)

    if download_results:
        msg = 'Getting results from functions'
        fs_done = [f for f in fs if f.done]
        fs_not_done = [f for f in fs if not f.done]
        # fs_not_ready = [f for f in futures if not f.ready and not f.done]

    else:
        msg = 'Waiting for functions to complete'
        fs_done = [f for f in fs if f.ready or f.done]
        fs_not_done = [f for f in fs if not f.done]
        # fs_not_ready = [f for f in futures if not f.ready and not f.done]

    if not fs_not_done:
        return fs_done, fs_not_done

    logger.info(msg)

    if is_unix_system() and timeout is not None:
        logger.debug('Setting waiting timeout to {} seconds'.format(timeout))
        error_msg = 'Timeout of {} seconds exceeded waiting for function activations to finish'.format(timeout)
        signal.signal(signal.SIGALRM, partial(timeout_handler, error_msg))
        signal.alarm(timeout)

    pbar = None

    if not is_lithops_worker() and setup_progressbar:
        from tqdm.auto import tqdm

        if not is_notebook():
            print()
        pbar = tqdm(bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ',
                    total=len(fs_not_done), disable=None)

    try:
        wait_storage(fs, internal_storage,
                     download_results=download_results,
                     throw_except=throw_except,
                     return_when=return_when, pbar=pbar,
                     THREADPOOL_SIZE=THREADPOOL_SIZE,
                     WAIT_DUR_SEC=WAIT_DUR_SEC)

    except KeyboardInterrupt as e:
        if download_results:
            not_dones_call_ids = [(f.job_id, f.call_id) for f in fs if not f.done]
        else:
            not_dones_call_ids = [(f.job_id, f.call_id) for f in fs if not f.ready and not f.done]
        msg = ('Cancelled - Total Activations not done: {}'.format(len(not_dones_call_ids)))
        if pbar:
            pbar.close()
            print()
        logger.info(msg)
        raise e

    except Exception as e:
        raise e

    finally:
        if is_unix_system():
            signal.alarm(0)
        if pbar and not pbar.disable:
            pbar.close()
            if not is_notebook():
                print()

    if download_results:
        fs_done = [f for f in fs if f.done]
        fs_notdone = [f for f in fs if not f.done]
    else:
        fs_done = [f for f in fs if f.ready or f.done]
        fs_notdone = [f for f in fs if not f.ready and not f.done]

    return fs_done, fs_notdone


def get_result(fs, throw_except=True, timeout=None,
               THREADPOOL_SIZE=128, WAIT_DUR_SEC=1,
               internal_storage=None):
    """
    For getting the results from all function activations

    :param fs: Futures list. Default None
    :param throw_except: Reraise exception if call raised. Default True.
    :param verbose: Shows some information prints. Default False
    :param timeout: Timeout for waiting for results.
    :param THREADPOOL_SIZE: Number of threads to use. Default 128
    :param WAIT_DUR_SEC: Time interval between each check.
    :return: The result of the future/s
    """
    if type(fs) != list:
        fs = [fs]

    if not internal_storage:
        internal_storage = InternalStorage(fs[0]._storage_config)

    fs_done, _ = wait(fs=fs, throw_except=throw_except,
                      timeout=timeout, download_results=True,
                      internal_storage=internal_storage,
                      THREADPOOL_SIZE=THREADPOOL_SIZE,
                      WAIT_DUR_SEC=WAIT_DUR_SEC)
    result = []
    fs_done = [f for f in fs_done if not f.futures and f._produce_output]
    for f in fs_done:
        result.append(f.result(throw_except=throw_except,
                               internal_storage=internal_storage))

    logger.debug("Finished getting results")

    if len(result) == 1:
        return result[0]

    return result
