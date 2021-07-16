import time

from lithops.multiprocessing import Pool, Lock, SimpleQueue, current_process


def f(lock, q):
    with lock:
        pid = current_process().pid
        ts = time.time()
        msg = 'process: {} - timestamp: {}'.format(pid, ts)
        q.put(msg)
        time.sleep(1)


if __name__ == "__main__":
    lock = Lock()
    q = SimpleQueue()

    n = 3
    with Pool() as p:
        res = p.starmap_async(f, [(lock, q)] * n)
        res.get()

        for _ in range(n):
            print(q.get())
