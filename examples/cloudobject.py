"""
Simple PyWren example using cloudobjects to transparently pass
objects stored in the storage backend between functions without
knowing they exact location (bucket, key)
"""
import pywren_ibm_cloud as pywren


def my_function_put(text, internal_storage):
    co1 = internal_storage.put_object('Temp object test 1: {}'.format(text, ))
    co2 = internal_storage.put_object('Temp object test 2: {}'.format(text, ))
    return [co1, co2]


def my_function_get(co, internal_storage):
    data = internal_storage.get_object(co)
    return data


if __name__ == "__main__":
    pw = pywren.ibm_cf_executor()
    pw.call_async(my_function_put, 'Hello World')
    cloudobjects = pw.get_result()
    pw.map(my_function_get, cloudobjects)
    print(pw.get_result())
    pw.clean()
