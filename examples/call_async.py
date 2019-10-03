"""
Simple PyWren example using one single function invocation
"""
import pywren_ibm_cloud as pywren


def my_function(x):
    return x + 7


if __name__ == '__main__':
    pw = pywren.ibm_cf_executor()
    pw.call_async(my_function, 3)
    print(pw.get_result())
