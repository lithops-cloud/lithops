import os
import time
import random
import logging
import threading
from .backends.ibm_cf import IbmCfComputeBackend

logger = logging.getLogger(__name__)


class ThreadSafeSingleton(type):
    _instances = {}
    _singleton_lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._singleton_lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super(ThreadSafeSingleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class Compute(metaclass=ThreadSafeSingleton):
    """
    An InternalCompute object is used by invokers and other components to access underlying compute backend
    without exposing the the implementation details.
    """

    def __init__(self, compute_config):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.compute_config = compute_config

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

    def invoke_with_result(self, runtime_name, runtime_memory, payload={}):
        """
        Invoke waiting for a result -- return information about this invocation
        """
        return self.compute_handler.invoke_with_result(runtime_name, runtime_memory, payload)

    def create_runtime(self, docker_image_name, memory, code=None, is_binary=True, timeout=300000):
        """
        Wrapper method to create a runtime in the compute backend.
        return: the name of the runtime
        """
        return self.compute_handler.create_runtime(docker_image_name, memory, code=code,
                                                   is_binary=is_binary, timeout=timeout)

    def delete_runtime(self, docker_image_name, memory):
        """
        Wrapper method to create a runtime in the compute backend
        """
        self.compute_handler.delete_runtime(docker_image_name, memory)

    def delete_all_runtimes(self):
        """
        Wrapper method to create a runtime in the compute backend
        """
        self.compute_handler.delete_all_runtimes()

    def list_runtimes(self, docker_image_name='all'):
        """
        Wrapper method to list deployed runtime in the compute backend
        """
        return self.compute_handler.list_runtimes(docker_image_name=docker_image_name)

    def get_runtime_key(self, docker_image_name, memory):
        """
        Wrapper method that returns a formated string that represents the runtime key.
        Each backend has its own runtime key format. Used to store modules preinstalls into storage
        """
        return self.compute_handler.get_runtime_key(docker_image_name, memory)
