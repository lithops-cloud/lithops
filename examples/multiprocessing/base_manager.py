import time
import random

# from multiprocessing import Process
# from multiprocessing.managers import BaseManager

from lithops.multiprocessing import Process
from lithops.multiprocessing.managers import BaseManager

import numpy as np


class ParameterServer:
    def __init__(self, dim):
        # Alternatively, params could be a dictionary
        # mapping keys to arrays.
        self.params = np.zeros(dim)

    def get_params(self):
        return self.params

    def update_params(self, grad):
        self.params += grad


BaseManager.register('ParameterServer', ParameterServer)
manager = BaseManager()
manager.start()

ps = manager.ParameterServer(10)
print(ps.get_params())


def worker(ps):
    for _ in range(10):
        params = ps.get_params()
        grad = np.ones(10)
        time.sleep(random.random())
        ps.update_params(grad)


procs = []

for _ in range(3):
    p = Process(target=worker, args=(ps,))
    p.start()
    procs.append(p)

for p in procs:
    p.join()

print(ps.get_params())
