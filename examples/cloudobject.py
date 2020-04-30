"""
Simple PyWren example using cloudobjects to transparently pass
objects stored in the storage backend between functions without
knowing they exact location (bucket, key)
"""
import pywren_ibm_cloud as pywren


def my_function_put(text, ibm_cos):
    co1 = ibm_cos.put_cobject('Cloudobject test 1: {}'.format(text, ))
    co2 = ibm_cos.put_cobject('Cloudobject test 2: {}'.format(text, ))
    return [co1, co2]


def my_function_get(co, ibm_cos):
    data = ibm_cos.get_cobject(co)
    return data


if __name__ == "__main__":
    with pywren.ibm_cf_executor() as pw:
        pw.call_async(my_function_put, 'Hello World')
        cloudobjects = pw.get_result()
        pw.map(my_function_get, cloudobjects)
        print(pw.get_result())
