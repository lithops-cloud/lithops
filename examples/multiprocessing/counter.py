from lithops.config import default_logging_config
default_logging_config('DEBUG')

# from multiprocessing import Pool, Manager
from lithops.multiprocessing import Pool, Manager


man = Manager()
val = man.Value('i', 0)
lock = man.Lock()


def incr(i, val, lock):
    with lock:
        val.value += 1


with Pool() as p:
    p.starmap(incr, [(i, val, lock) for i in range(10)])
    p.close()
    p.join()

print(val.value)
