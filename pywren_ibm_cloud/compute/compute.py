import os
import logging
import importlib

logger = logging.getLogger(__name__)


class Compute:
    """
    A Compute object is used by invokers and other components to access
    underlying compute backend without exposing the implementation details.
    """

    def __init__(self, compute_config):
        self.log_level = os.getenv('PYWREN_LOGLEVEL')
        self.config = compute_config
        self.backend = self.config['backend']

        try:
            module_location = 'pywren_ibm_cloud.compute.backends.{}'.format(self.backend)
            cb_module = importlib.import_module(module_location)
            ComputeBackend = getattr(cb_module, 'ComputeBackend')
            self.compute_handler = ComputeBackend(self.config[self.backend])
        except Exception as e:
            raise Exception("An exception was produced trying to create the "
                            "'{}' compute backend: {}".format(self.backend, e))

    def invoke(self, runtime_name, memory, payload):
        """
        Invoke -- return information about this invocation
        """
        return self.compute_handler.invoke(runtime_name, memory, payload)

    def build_runtime(self, runtime_name, file):
        """
        Wrapper method to build a new runtime for the compute backend.
        return: the name of the runtime
        """
        self.compute_handler.build_runtime(runtime_name, file)

    def create_runtime(self, runtime_name, memory, timeout):
        """
        Wrapper method to create a runtime in the compute backend.
        return: the name of the runtime
        """
        return self.compute_handler.create_runtime(runtime_name, memory, timeout=timeout)

    def delete_runtime(self, runtime_name, memory):
        """
        Wrapper method to create a runtime in the compute backend
        """
        self.compute_handler.delete_runtime(runtime_name, memory)

    def delete_all_runtimes(self):
        """
        Wrapper method to create a runtime in the compute backend
        """
        self.compute_handler.delete_all_runtimes()

    def list_runtimes(self, runtime_name='all'):
        """
        Wrapper method to list deployed runtime in the compute backend
        """
        return self.compute_handler.list_runtimes(runtime_name)

    def get_runtime_key(self, runtime_name, memory):
        """
        Wrapper method that returns a formated string that represents the runtime key.
        Each backend has its own runtime key format. Used to store modules preinstalls
        into the storage
        """
        return self.compute_handler.get_runtime_key(runtime_name, memory)
