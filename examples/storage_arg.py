"""
Simple Lithops example using the 'storage' parameter, which is
a ready-to-use Storage instance.
"""
import lithops


def my_function(bucket_name, obj_key, storage):
    print(f'I am processing the object //{bucket_name}/{obj_key}')
    counter = {}

    data = storage.get_object(bucket_name, obj_key)

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1

    return counter


if __name__ == '__main__':
    bucket_name = 'lithops-sample-data'
    obj_key = 'obj1.txt'
    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function, (bucket_name, obj_key))
    print(fexec.get_result())
