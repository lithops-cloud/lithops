import os
import sys
import logging
from pywren_ibm_cloud.compute import Compute
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.runtime import create_runtime
from pywren_ibm_cloud.wrenconfig import extract_compute_config

logger = logging.getLogger(__name__)


def select_runtime(config, internal_storage, executor_id, runtime_name, runtime_memory):
    """
    Auxiliary method that gets the runtime metadata from the storage. This metadata contains the preinstalled
    python modules needed to serialize the local function.  If the .metadata file does not exists in the storage,
    this means that the runtime is not installed, so this method will proceed to install it.
    """
    log_level = os.getenv('PYWREN_LOG_LEVEL')
    compute_config = extract_compute_config(config)
    internal_compute = Compute(compute_config)

    log_msg = 'ExecutorID {} - Selected Runtime: {} - {}MB'.format(executor_id, runtime_name, runtime_memory)
    logger.info(log_msg)
    if not log_level:
        print(log_msg, end=' ')

    runtime_key = internal_compute.get_runtime_key(runtime_name, runtime_memory)
    try:
        runtime_meta = internal_storage.get_runtime_info(runtime_key)
        if not log_level:
            print()
    except Exception:
        logger.debug('ExecutorID {} - Runtime {} with {}MB is not yet installed'.format(executor_id, runtime_name, runtime_memory))
        if not log_level:
            print('(Installing...)')
        create_runtime(runtime_name, memory=runtime_memory, config=config)
        runtime_meta = internal_storage.get_runtime_info(runtime_key)

    if not _runtime_valid(runtime_meta):
        raise Exception(("The indicated runtime: {} "
                         "is not appropriate for this Python version.")
                        .format(runtime_name))

    return runtime_meta['preinstalls']


def _runtime_valid(runtime_meta):
    """
    Basic checks
    """
    this_version_str = version_str(sys.version_info)
    return this_version_str == runtime_meta['python_ver']
