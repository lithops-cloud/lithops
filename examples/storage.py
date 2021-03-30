"""
Simple Lithops example using the 'Storage' interface
"""
from lithops import FunctionExecutor, Storage

BUCKET_NAME = 'lithops-sample-data'  # change-me


def my_function(obj_id, storage):
    print(obj_id)

    data = storage.get_cloudobject(obj_id)

    return data.decode()


if __name__ == '__main__':

    obj_key = 'cloudobject1.txt'
    storage = Storage()
    obj_id = storage.put_cloudobject('Hello World!', BUCKET_NAME, obj_key)
    print(obj_id)

    fexec = FunctionExecutor()
    fexec.call_async(my_function, obj_id)
    print(fexec.get_result())

    obj_key = 'cloudobject2.txt'
    storage = fexec.storage
    obj_id = storage.put_cloudobject('Hello World!', BUCKET_NAME, obj_key)
    print(obj_id)

    fexec.call_async(my_function, obj_id)
    print(fexec.get_result())
