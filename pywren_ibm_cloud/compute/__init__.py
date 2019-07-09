import os
import time
import random
import logging
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

    def invoke(self, payload, runtime_memory):
        """
        Invoke -- return information about this invocation
        """
        self.runtime_memory = runtime_memory
        action_name = format_action_name(self.runtime_name, self.runtime_memory)
        act_id = self.compute_handler.invoke(action_name, payload)
        attempts = 1

        while not act_id and self.invocation_retry and attempts < self.retries:
            attempts += 1
            selected_sleep = random.choice(self.retry_sleeps)
            exec_id = payload['executor_id']
            call_id = payload['call_id']
            log_msg = ('ExecutorID {} - Function {} - Retry {} in {} seconds'.format(exec_id, call_id, attempts, selected_sleep))
            logger.debug(log_msg)
            time.sleep(selected_sleep)
            act_id = self.compute_handler.invoke(action_name, payload)

        return act_id

    def config(self):
        """
        Return config dict
        """
        return {'runtime': self.runtime_name,
                'runtime_memory': self.runtime_memory,
                'runtime_timeout': self.runtime_timeout,
                'namespace': self.namespace,
                'endpoint': self.endpoint}
