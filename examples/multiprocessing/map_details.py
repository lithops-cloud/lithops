import lithops.multiprocessing as mp
from lithops.multiprocessing import config as mp_config


def my_map_function(x):
    return x + 7


if __name__ == "__main__":
    iterdata = [1, 2, 3, 4]

    mp_config.set_parameter(mp_config.EXPORT_EXECUTION_DETAILS, '.')

    with mp.Pool() as pool:
        results = pool.map(my_map_function, iterdata)

    print(results)
