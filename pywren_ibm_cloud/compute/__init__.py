import os
import time
import random
import logging
from pywren_ibm_cloud.utils import runtime_valid
from pywren_ibm_cloud.utils import format_action_name
from .backends.ibm_cf import IbmCfComputeBackend

logger = logging.getLogger(__name__)


class InternalCompute:
    """
    An InternalCompute object is used by invokers and other components to access underlying compute backend
    without exposing the the implementation details.
    """

    def __init__(self, compute_config, internal_storage):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.compute_config = compute_config
        self.internal_storage = internal_storage

        self.compute_backend = compute_config['compute_backend']

        if self.compute_backend == 'ibm_cf':
            self.compute_handler = IbmCfComputeBackend(compute_config['ibm_cf'])

        else:
            raise NotImplementedError(("Using {} as compute backend is" +
                                       "not supported yet").format(self.compute_backend))

    def invoke(self, runtime_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        act_id = self.compute_handler.invoke(runtime_name, runtime_memory, payload)
        attempts = 1

        while not act_id and self.invocation_retry and attempts < self.retries:
            attempts += 1
            selected_sleep = random.choice(self.retry_sleeps)
            exec_id = payload['executor_id']
            call_id = payload['call_id']
            log_msg = ('ExecutorID {} - Function {} - Retry {} in {} seconds'.format(exec_id, call_id, attempts, selected_sleep))
            logger.debug(log_msg)
            time.sleep(selected_sleep)
            act_id = self.compute_handler.invoke(runtime_name, runtime_memory, payload)

        return act_id

    def get_runtime_preinstalls(self, executor_id, runtime_name, runtime_memory):
        runtime_memory = int(runtime_memory)
        log_msg = 'ExecutorID {} - Selected Runtime: {} - {}MB'.format(executor_id, runtime_name, runtime_memory)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg, end=' ')

        try:
            runtime_meta = self.compute_handler.get_runtime_info(runtime_name, runtime_memory, self.internal_storage)
            if not self.log_level:
                print()

        except Exception as e:
            print(e)
            logger.debug('ExecutorID {} - Runtime {} with {}MB is not yet installed'.format(executor_id, runtime_name, runtime_memory))
            if not self.log_level:
                print('(Installing...)')
            self.compute_handler.create_runtime(runtime_name, runtime_memory, self.internal_storage)
            runtime_meta = self.compute_handler.get_runtime_info(runtime_name, runtime_memory, self.internal_storage)

        if not runtime_valid(runtime_meta):
            raise Exception(("The indicated runtime: {} "
                             "is not appropriate for this Python version.")
                            .format(self.runtime_name))

        return runtime_meta['preinstalls']
