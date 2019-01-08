"""
Simply PyWren example

In this example the map() method will launch only
one map function, because 'remote_invocation' has been
defined to True. Finally, the reduce() method will
launch without waiting for map invocations to be done
locally so the user now can track the executions from remote
without the necessity of staying online. This option is
done by providing a special PyWren ID to get_result() method
which given after each executor operation.
"""
import pywren_ibm_cloud as pywren

iterdata = [1, 2, 3, 4]


def my_map_function(x):
    return x + 7


def my_reduce_function(results):
    total = 0
    for map_result in results:
        total = total + map_result
    return total


pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, iterdata, my_reduce_function, remote_invocation=True, reducer_wait_local=False)

result = None
while result is None:
    pw = pywren.ibm_cf_executor()
    pywren_id = input('Enter PyWren ID: ')
    result, status = pw.get_result(pywren_id=pywren_id, get_status=True)
    print(result)
    print(status)
