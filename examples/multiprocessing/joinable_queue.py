import time

from multiprocessing import Process, JoinableQueue
# from lithops.multiprocessing import Process, JoinableQueue


def worker(queue):
    working = True
    while working:
        task = queue.get()

        # Do work that may fail
        assert task < 10
        time.sleep(0.25)

        # Confirm task
        queue.task_done()

        if task == -1:
            working = False


if __name__ == '__main__':
    q = JoinableQueue()
    p = Process(target=worker, args=(q,))
    p.start()

    for x in range(10):
        q.put(x)

    # uncomment to hang on the q.join
    # q.put(11)
    q.join()

    q.put(-1)  # end loop
    p.join()
