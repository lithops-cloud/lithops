import os
import sys
import logging
from pywren_ibm_cloud.utils import version_str

logger = logging.getLogger(__name__)


def select_runtime(config, internal_storage, compute_handler, executor_id, job_id, runtime_memory):
    """
    Auxiliary method that gets the runtime metadata from the storage. This metadata contains the preinstalled
    python modules needed to serialize the local function.  If the .metadata file does not exists in the storage,
    this means that the runtime is not installed, so this method will proceed to install it.
    """
    log_level = os.getenv('CB_LOG_LEVEL')
    runtime_name = config['pywren']['runtime']
    if runtime_memory is None:
        runtime_memory = config['pywren']['runtime_memory']
    runtime_memory = int(runtime_memory)

    log_msg = 'ExecutorID {} | JobID {} - Selected Runtime: {} - {}MB'.format(executor_id, job_id, runtime_name, runtime_memory)
    logger.info(log_msg)
    if not log_level:
        print(log_msg, end=' ')

    runtime_key = compute_handler.get_runtime_key(runtime_name, runtime_memory)
    try:
        runtime_meta = internal_storage.get_runtime_meta(runtime_key)
        if not log_level:
            print()
    except Exception:
        logger.debug('ExecutorID {} | JobID {} - Runtime {} with {}MB is not yet installed'.format(executor_id, job_id, runtime_name, runtime_memory))
        if not log_level:
            print('(Installing...)')

        timeout = config['pywren']['runtime_timeout']
        logger.debug('Creating runtime: {}, memory: {}'.format(runtime_name, runtime_memory))
        runtime_meta = compute_handler.generate_runtime_meta(runtime_name)
        compute_handler.create_runtime(runtime_name, runtime_memory, timeout=timeout)
        internal_storage.put_runtime_meta(runtime_key, runtime_meta)

    py_local_version = version_str(sys.version_info)
    py_remote_version = runtime_meta['python_ver']

    if py_local_version != py_remote_version:
        raise Exception(("The indicated runtime '{}' is running Python {} and it "
                         "is not compatible with the local Python version {}")
                        .format(runtime_name, py_remote_version, py_local_version))

    return runtime_meta
