# import multiprocessing as mp
import lithops.multiprocessing as mp


def multiple_args(arg1, arg2, arg3):
    print(arg1, arg2, arg3)


def single_arg(arg):
    print(arg)


if __name__ == '__main__':
    # Processes unpack the iterable passed to args as arguments. Usually tuples are used
    p = mp.Process(target=multiple_args, args=(1, 2, 3))
    p.start()
    p.join()

    # But other iterable objects like string or list are allowed, as long as the length matches the number of args
    p = mp.Process(target=multiple_args, args='ABC')
    p.start()
    p.join()

    # To pass a single argument you must encapsulate it in a 1-element tuple
    p = mp.Process(target=single_arg, args=('hello',))
    p.start()
    p.join()

    pool = mp.Pool()

    # Pool.map function MUST have only one argument
    pool.map(single_arg, [1, 2, 3])
    pool.map(single_arg, (1, 2, 3))

    # You can pass multiple arguments to a map function
    # However, keep in mind that map function does not implicitly unpack arguments
    pool.map(single_arg, [(1, 'a', 'one'), (2, 'b', 'two'), (3, 'c', 'three')])

    # You can't use a function that receives more than one required positional argument for Pool.map
    try:
        pool.map(multiple_args, [(1, 'a', 'one'), (2, 'b', 'two'), (3, 'c', 'three')])
    except Exception as e:
        print(e)

    # Pool.starmap unpacks arguments passed as list of tuples
    pool.starmap(multiple_args, [(1, 'a', 'one'), (2, 'b', 'two'), (3, 'c', 'three')])

    # You can't use a function that receives one argument and pass multiple arguments for Pool.starmap
    try:
        pool.starmap(single_arg, [(1, 'a', 'one'), (2, 'b', 'two'), (3, 'c', 'three')])
    except Exception as e:
        print(e)

    # Pool.apply con accept positional arguments, key word arguments or both
    pool.apply(multiple_args, args=(1, 2, 3))
    pool.apply(multiple_args, kwds={'arg1': 1, 'arg2': 2, 'arg3': 3})
    pool.apply(multiple_args, args=(1, 2), kwds={'arg3': 3})

    pool.close()
