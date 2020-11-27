import lithops
from lithops.storage.cloud_proxy import open, os


def map_func(x):
    with open(f'test/{x}.txt', 'w') as file:
        file.write('Hello from function number {}!'.format(str(x)))
    return x


if __name__ == "__main__":
    # Simple file write
    filepath = 'bar/foo.txt'
    with open(filepath, 'w') as f:
        f.write('Hello world!')

    # Listing directories
    dirname = os.path.dirname(filepath)
    print(os.listdir(dirname))

    # Read the previously created file
    with open(filepath, 'r') as f:
        print(f.read(6))
        print(f.read())

    # Remove the file
    os.remove(filepath)
    print(os.listdir(dirname))

    # Get files that have been created in functions
    fexec = lithops.FunctionExecutor()
    fexec.map(map_func, [1, 2, 3, 4])
    res = fexec.get_result()

    with open('test/3.txt', 'r') as f:
        print(f.read())

    # os.walk example
    with open('test/subfolder/hello.txt', 'w') as f:
        f.write('hello')

    for root, dirs, files in os.walk('/', topdown=True):
        print(root, dirs, files)
        print('-------')

    os.remove('/test')
