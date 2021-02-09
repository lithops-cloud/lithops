import time
import random

# from multiprocessing import Process, Queue
from lithops.multiprocessing import Process, Queue


def work(remote_queue):
    for i in range(5):
        remote_queue.put('Working hard ... {}'.format(i))
        time.sleep(random.random())


if __name__ == '__main__':
    queue = Queue()
    process = Process(target=work, args=(queue,))

    # ctx = mp.get_context('spawn')
    # queue = ctx.Queue()
    # process = ctx.Process(target=work, args=(queue,))

    process.start()
    process.join()

    while True:
        try:
            data = queue.get(timeout=3)
            print(data)
        except queue.Empty:
            print('Queue empty!')
            break
