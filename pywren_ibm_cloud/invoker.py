import os
import logging
from pywren_ibm_cloud.runtime import create_runtime
from pywren_ibm_cloud.utils import runtime_valid, format_action_name
from pywren_ibm_cloud.compute import InternalCompute
from pywren_ibm_cloud import wrenconfig

logger = logging.getLogger(__name__)


class Invoker:

    def __init__(self, config, internal_storage, executor_id):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.config = config
        self.internal_storage = internal_storage
        self.executor_id = executor_id

        compute_config = wrenconfig.extract_compute_config(self.config)
        self.internal_compute = InternalCompute(compute_config, internal_storage)

        self.runtime_name = self.config['pywren']['runtime']
        self.runtime_memory = self.config['pywren']['runtime_memory']

    def invoke(self, payload):
        return self.internal_compute.invoke(self.runtime_name, self.runtime_memory, payload)

    def set_memory(self, memory):
        
        self.internal_compute.set_memory()
        
        if memory is None:
            memory = self.runtime_memory
        else:
            self.runtime_memory = int(memory)

        log_msg = 'ExecutorID {} - Selected Runtime: {} - {}MB'.format(self.executor_id, self.runtime_name, memory)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg, end=' ')

        try:
            action_name = format_action_name(self.runtime_name, memory)
            self.runtime_meta = self.internal_storage.get_runtime_info(self.region, self.namespace, action_name)
            if not self.log_level:
                print()

        except Exception:
            logger.debug('ExecutorID {} - Runtime {} with {}MB is not yet installed'.format(self.executor_id, self.runtime_name, memory))
            if not self.log_level:
                print('(Installing...)')
            create_runtime(self.runtime_name, memory=memory, config=self.config)
            self.runtime_meta = self.internal_storage.get_runtime_info(self.region, self.namespace, action_name)

        if not runtime_valid(self.runtime_meta):
            raise Exception(("The indicated runtime: {} "
                             "is not appropriate for this Python version.")
                            .format(self.runtime_name))

    def get_runtime_preinstalls(self):
        return self.runtime_meta['preinstalls']

    def get_config(self):
        """
        Return config dict
        """
        return self.invoker_handler.config()
