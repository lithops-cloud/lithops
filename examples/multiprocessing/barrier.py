import time

from lithops.multiprocessing import Pool, Barrier, current_process
# from multiprocessing import Pool, Barrier, current_process


def f():
    print('waiting...')
    barrier.wait()
    pid = current_process().pid
    msg = 'process: {} - timestamp: {}'.format(pid, time.time())
    return msg


if __name__ == "__main__":
    n = 2
    barrier = Barrier(n)

    async_results = []
    with Pool(processes=2) as p:
        res = p.apply_async(f, ())
        async_results.append(res)
        time.sleep(3)
        res = p.apply_async(f, ())
        async_results.append(res)

    for res in async_results:
        print(res.get())
