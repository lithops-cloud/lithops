import getpass

from lithops.multiprocessing import Process


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
    name = getpass.getuser()
    p = Process(target=function, args=(name,), kwargs={'language': 'english'})
    p.start()
    p.join()
