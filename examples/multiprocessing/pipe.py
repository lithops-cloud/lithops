# from multiprocessing import Process, Pipe
from lithops.multiprocessing import Process, Pipe
from lithops.utils import setup_lithops_logger
import logging

setup_lithops_logger(logging.DEBUG)


def f(conn):
    conn.send([42, None, 'hello'])
    conn.close()


if __name__ == '__main__':
    parent_conn, child_conn = Pipe()
    p = Process(target=f, args=(child_conn,))
    p.start()
    print(parent_conn.recv())  # prints "[42, None, 'hello']"
    p.join()
