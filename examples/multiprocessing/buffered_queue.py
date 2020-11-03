from lithops.multiprocessing import Process, Queue, getpid
import time


def f(q):
    print("I'm process", getpid())
    q.put([42, None, 'hello'])
    for i in range(3):
        q.put('Message no. {} ({})'.format(i, time.time()))
        time.sleep(1)


if __name__ == '__main__':
    q = Queue()
    p = Process(target=f, args=(q,))
    p.start()
    print(q.get())  # prints "[42, None, 'hello']"
    p.join()
    for _ in range(3):
        print(q.get())
