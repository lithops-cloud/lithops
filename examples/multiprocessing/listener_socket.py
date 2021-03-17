# import multiprocessing.connection
from lithops.multiprocessing.connection import Listener, Client
from lithops.multiprocessing import Process, Pool


ADDRESS = ('localhost', 50000)
CLIENTS = 5


def server(address):
    c = CLIENTS
    with Listener(address, authkey=b'secret password') as listener:
        while c > 0:
            print('waiting to receive a connection...')
            with listener.accept() as conn:
                print('connection accepted from', listener.last_accepted)
                c -= 1
                print(conn.recv())
                conn.send('good bye')


def client(address):
    with Client(address, authkey=b'secret password') as conn:
        conn.send('hello')
        print(conn.recv())


serv = Process(target=server, args=(ADDRESS,))
serv.start()

with Pool() as p:
    p.map(client, [(ADDRESS,)] * 5)

serv.join()
