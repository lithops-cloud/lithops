from lithops.multiprocessing.cloud_proxy import os, open

if __name__ == "__main__":
    filepath = 'bar/foo.txt'
    with open(filepath, 'w') as f:
        f.write('Hello world!')

    dirname = os.path.dirname(filepath)
    print(os.listdir(dirname))

    with open(filepath, 'r') as f:
        print(f.read(6))
        print(f.read())

    os.remove(filepath)
    print(os.listdir(dirname))
