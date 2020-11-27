# from multiprocessing import Pool
from lithops.multiprocessing import Pool


def double(i):
    return i * 2


if __name__ == '__main__':
    with Pool() as pool:
        result = pool.map(double, [1, 2, 3, 4, 5])
        print(result)
