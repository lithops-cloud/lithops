import os
import logging
from pywren_ibm_cloud.invoker.ibm_cf.invoker import IBMCloudFunctionsInvoker
from pywren_ibm_cloud.runtime import get_runtime_preinstalls
from pywren_ibm_cloud.version import __version__

logger = logging.getLogger(__name__)


class Invoker:

    def __init__(self, config, internal_storage):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.config = config
        self.internal_storage = internal_storage

        self.invoker_type = config['pywren']['invoker_backend']

        if self.invoker_type == 'ibm_cf':
            self.invoker_handler = IBMCloudFunctionsInvoker(config)
        else:
            raise NotImplementedError(("Using {} as internal storage backend is" +
                                       "not supported yet").format(self.backend_type))

        self.runtime_name = self.config['pywren']['runtime']
        self.runtime_memory = self.config['pywren']['runtime_memory']
        self.runtime_preinstalls = get_runtime_preinstalls(self.internal_storage,
                                                           self.runtime_name,
                                                           self.runtime_memory,
                                                           self.config)

    def invoke(self, payload):
        return self.invoker_handler.invoke(payload, self.runtime_memory)

    def set_memory(self, memory):
        if memory is not None:
            self.runtime_memory = int(memory)

        logger.info('PyWren v{} init for Runtime: {} - {}MB'.format(__version__, self.runtime_name, self.runtime_memory))
        if not self.log_level:
            print('PyWren v{} init for Runtime: {} - {}MB'.format(__version__, self.runtime_name, self.runtime_memory), end=' ')

        # TODO: check if memory is deployed

    def get_runtime_preinstalls(self):
        return self.runtime_preinstalls

    def get_config(self):
        """
        Return config dict
        """
        return self.invoker_handler.config()
