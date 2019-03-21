"""
Simple PyWren example using the map method.

In this example the map() method will launch one
map function for each entry in 'iterdata'. Finally
it will print the results for each invocation with
pw.get_all_result()
"""
import pywren_ibm_cloud as pywren
import time


def my_map_function(x):
    time.sleep(15)
    return x + 7

t1 = time.time()

pw = pywren.ibm_cf_executor()
pw.map(my_map_function, range(200), remote_invocation=True)
result = pw.get_result()

t2 = time.time()

print('Time:', t2-t1)

pw.create_timeline_plots('/home/jsampe/pywren_plots', 'map')
pw.clean()
