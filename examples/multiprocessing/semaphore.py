from lithops.multiprocessing import Pool, Semaphore, SimpleQueue, current_process
import time


def f(sem):
    with sem:
        pid = current_process().pid
        time.sleep(3)  # Working...
        msg = 'process: {} - timestamp: {}'.format(pid, time.time())
        return msg


if __name__ == "__main__":
    # inital value to 2
    sem = Semaphore(value=2)

    n = 4
    with Pool() as p:
        res = p.map(f, [sem] * n)

    for msg in res:
        print(msg)
