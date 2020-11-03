from lithops.config import default_logging_config
default_logging_config('DEBUG')

# from multiprocessizzng import Pool, Manager
from lithops.multiprocessing import Pool, Manager


man = Manager()
val = man.Value('i', 0)
lock = man.Lock()


def incr(val, lock):
    with lock:
        val.value += 1


with Pool() as p:
    p.starmap(incr, [(val, lock) for _ in range(10)])
    p.close()
    p.join()

print(val.value)
