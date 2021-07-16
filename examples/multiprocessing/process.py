import getpass

import lithops.multiprocessing as mp
from lithops.multiprocessing import Process
# from multiprocessing import Process


def function(name, language='english'):
    greeting = {
        'english': 'hello',
        'spanish': 'hola',
        'italian': 'ciao',
        'german': 'hallo',
        'french': 'salut',
        'emoji': '\U0001F44B'
    }

    print(greeting[language], name)


if __name__ == '__main__':
    # mp.config.set_parameter(mp.config.STREAM_STDOUT, True)

    name = getpass.getuser()
    p = Process(target=function, args=(name,), kwargs={'language': 'english'})
    p.start()
    p.join()
