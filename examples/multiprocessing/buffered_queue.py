from lithops.multiprocessing import Process, Queue, getpid
import time


def f(q):
    print("I'm process", getpid())
    q.put([42, None, 'hello'])
    time.sleep(5)


if __name__ == '__main__':
    q = Queue()
    p = Process(target=f, args=(q,))
    p.start()
    print(q.get())  # prints "[42, None, 'hello']"
    p.join()
