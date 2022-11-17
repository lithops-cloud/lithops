"""
This example show how a lithops function can be invoked
in one machine and get the results in another machine by
simply serializing and passing the futures.
"""
import time
import os

# ---------------------- Machine 1 ---------------------
import lithops
import pickle


def my_map_function(id, x):
    print(f"I'm activation number {id}")
    return x + 7


fexec = lithops.FunctionExecutor()
futures = fexec.map(my_map_function, range(5))
with open('futures.pickle', 'wb') as file:
    pickle.dump(futures, file)

time.sleep(5)


# ---------------------- Machine 2---------------------
import pickle
from lithops.wait import get_result

with open('futures.pickle', 'rb') as file:
    futures = pickle.load(file)
results = get_result(futures)
print(results)
os.remove('futures.pickle')
