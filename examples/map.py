"""
Simple PyWren example using the map method.
In this example the map() method will launch one
map function for each entry in 'iterdata'. Finally
it will print the results for each invocation with
pw.get_all_result()
"""
import pywren_ibm_cloud as pywren

iterdata = [1, 2, 3, 4]


def my_map_function(x):
    return x + 7


pw = pywren.ibm_cf_executor()
pw.map(my_map_function, iterdata)
print(pw.get_result())
