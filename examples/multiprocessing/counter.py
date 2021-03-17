# from multiprocessing import Pool, Value, RawValue
from lithops.multiprocessing import Pool, Value, RawValue
from lithops.utils import setup_lithops_logger

# setup_lithops_logger('DEBUG')


def incr(proc_id):
    for _ in range(100):
        v.value += 1


def sync_incr(proc_id):
    for _ in range(100):
        with v.get_lock():
            v.value += 1


if __name__ == '__main__':
    # Raw shared value
    v = RawValue('i', 0)
    print(v.value)

    with Pool() as p:
        res = p.map_async(incr, [str(i) for i in range(4)])
        p.close()
        res.get()
        p.join()

    print(v.value)

    # Synchronized shared value
    v = Value('i')
    print(v.value)

    with Pool() as p:
        res = p.map_async(sync_incr, [str(i) for i in range(4)])
        p.close()
        res.get()
        p.join()

    print(v.value)
