import numpy as np
import time

from lithops.multiprocessing import Pool
from lithops.multiprocessing.managers import SyncManager
# from multiprocessing import Pool
# from multiprocessing.managers import SyncManager


class ParameterServer:
    def __init__(self, dim):
        self.params = np.zeros(dim)

    def get_params(self):
        return self.params

    def update_params(self, grad):
        self.params += grad


if __name__ == '__main__':
    SyncManager.register('ParameterServer', ParameterServer)
    manager = SyncManager()
    manager.start()

    ps = manager.ParameterServer(10)
    lock = manager.Lock()
    print(ps.get_params())


    def worker(parameter_server, manager_lock):
        for _ in range(10):
            with manager_lock:
                params = parameter_server.get_params()
                grad = np.ones(10)
                time.sleep(0.01)
                parameter_server.update_params(grad)


    with Pool() as p:
        p.starmap(worker, [(ps, lock)] * 5)

    print(ps.get_params())
