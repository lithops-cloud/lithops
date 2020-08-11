"""
Simple PyWren example using cloudobjects to transparently pass
objects stored in the storage backend between functions without
knowing they exact location (bucket, key)
"""
import pywren_ibm_cloud as pywren
import os


def my_function_put(text, storage):
    co1 = storage.put_cobject('Cloudobject test 1: {}'.format(text, ))
    co2 = storage.put_cobject('Cloudobject test 2: {}'.format(text, ))
    return [co1, co2]


def my_function_get(co, storage):
    data = storage.get_cobject(co)
    return data


if __name__ == "__main__":
    """
    Managing cloudobjects with context manager.
    At the end of the with statement all
    cloudobjects are automatically deleted.
    """
    with pywren.ibm_cf_executor() as pw:
        pw.call_async(my_function_put, 'Hello World')
        cloudobjects = pw.get_result()
        pw.map(my_function_get, cloudobjects)
        print(pw.get_result())

    """
    Managing cloudobjects without context manager.
    pw.clean() must be called at the end to delete
    the cloudobjects created in the same executor as
    long as you used the default location.
    Alternatively, you can call pw.clean(cs=cloudobjects)
    to delete a specific list of cloudobjects.
    pw.clean(cs=cloudobjects) is mandatory if you created
    the cloudobjects in a custom location.
    """
    pw = pywren.ibm_cf_executor()
    pw.call_async(my_function_put, 'Hello World')
    cloudobjects = pw.get_result()
    pw.map(my_function_get, cloudobjects)
    result = pw.get_result()
    pw.clean()  # or pw.clean(cs=cloudobjects)
    print(result)
