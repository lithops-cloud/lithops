# from multiprocessing.managers import BaseManager
# from multiprocessing import Pool
from lithops.multiprocessing.managers import BaseManager
from lithops.multiprocessing import Pool
import random
import time
import numpy as np


class ParameterServer:
    def __init__(self):
        self.parameters = np.zeros(10)

    def update(self, value):
        self.parameters += value

    def get_parameters(self):
        return self.parameters


BaseManager.register('ParameterServer', ParameterServer)
manager = BaseManager()
manager.start()
param_server = manager.ParameterServer()

param_server.update(1)


# def work(parameter_server):
#     for _ in range(3):
#         time.sleep(random.random())
#         parameter_server.update(1)
#         # print(parameter_server.get_parameters())
#
#
# with Pool() as p:
#     p.starmap(work, [(param_server, ) for _ in range(3)])
#     p.close()
#     p.close()

print(param_server.get_parameters())
