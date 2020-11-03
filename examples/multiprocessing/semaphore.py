from lithops.multiprocessing import Pool, Semaphore, SimpleQueue, getpid
import time


def f(sem, q):
    with sem:
        pid = getpid()
        ts = time.time()
        msg = 'process: {} - timestamp: {}'.format(pid, ts)
        q.put(msg)
        time.sleep(3)


if __name__ == "__main__":
    # inital value to 3
    sem = Semaphore(value=3)
    q = SimpleQueue()

    n = 6
    with Pool() as p:
        p.map_async(f, [[sem, q]] * n)

        for _ in range(n):
            print(q.get())
