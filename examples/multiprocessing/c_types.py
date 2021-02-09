# from multiprocessing import Pool, Array, Process
from lithops.multiprocessing import Pool, Array, Process


def replace(index, value):
    a[index] = value


def add(index, value):
    a[index] += value


def to_upper():
    my_str.value.upper()


if __name__ == '__main__':
    x = [4, 8, 15, 16, 23, 42]
    a = Array('i', x)
    my_str = Array('c', b'hello')

    p = Process(target=replace, args=(0, 45))
    p.start()
    p.join()

    print(a[0])

    with Pool() as p:
        res = p.starmap_async(add, [(i, 1) for i in range(len(a))])
        p.close()
        res.wait()
        p.join()

    print(a[:])

    a[:] = [i for i in range(len(a))]
    print(a[2:4])

    print(my_str.value)

    p = Process(target=to_upper)
    p.start()
    p.join()

    print(my_str[:])
    for char in my_str.value:
        print(bytes([char]))
