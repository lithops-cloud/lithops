import time

from lithops.multiprocessing import Process, Queue, current_process


def f(q):
    print("I'm process {}".format(current_process().pid))
    q.put([42, None, 'hello'])
    for i in range(3):
        q.put('Message no. {} ({})'.format(i, time.time()))
        time.sleep(1)
    print('Done')


if __name__ == '__main__':
    q = Queue()
    p = Process(target=f, args=(q,))
    p.start()

    print(q.get())  # prints "[42, None, 'hello']"

    consuming = True
    while consuming:
        try:
            res = q.get(block=True, timeout=3)
            print(res)
        except q.Empty as e:
            print('Queue empty!')
            consuming = False

    p.join()
