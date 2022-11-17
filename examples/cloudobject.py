"""
Simple Lithops example using cloudobjects to transparently pass
objects stored in the storage backend between functions without
knowing they exact location (bucket, key)
"""
import lithops


def my_function_put(text, storage):
    co1 = storage.put_cloudobject(f'Cloudobject test 1: {text}')
    co2 = storage.put_cloudobject(f'Cloudobject test 2: {text}')
    return [co1, co2]


def my_function_get(co, storage):
    data = storage.get_cloudobject(co)
    return data


if __name__ == "__main__":
    """
    Managing cloudobjects with context manager.
    At the end of the with statement all
    cloudobjects are automatically deleted.
    """
    with lithops.FunctionExecutor() as fexec:
        fexec.call_async(my_function_put, 'Hello World')
        cloudobjects = fexec.get_result()
        fexec.map(my_function_get, cloudobjects)
        print(fexec.get_result())

    """
    Managing cloudobjects without context manager.
    fexec.clean() must be called at the end to delete
    the cloudobjects created in the same executor as
    long as you used the default location.
    Alternatively, you can call fexec.clean(cs=cloudobjects)
    to delete a specific list of cloudobjects.
    fexec.clean(cs=cloudobjects) is mandatory if you created
    the cloudobjects in a custom location.
    """
    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function_put, 'Hello World')
    cloudobjects = fexec.get_result()
    fexec.map(my_function_get, cloudobjects)
    result = fexec.get_result()
    fexec.clean()  # or fexec.clean(cs=cloudobjects)
    print(result)
