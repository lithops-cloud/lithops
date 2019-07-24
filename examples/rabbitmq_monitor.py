"""
Simple PyWren example using rabbitmq to monitor map function invocations
"""
import pywren_ibm_cloud as pywren
import time

total = 100


def my_function(x):
    time.sleep(2)
    return x + 7


if __name__ == "__main__":
    pw = pywren.ibm_cf_executor(runtime_memory=256)
    pw.map(my_function, range(total))
    pw.get_result()
    pw.create_timeline_plots('/home/josep/pywren_plots', 'no_rabbitmq')
    pw.clean()

    pw = pywren.ibm_cf_executor(runtime_memory=256, rabbitmq_monitor=True)
    pw.map(my_function, range(total))
    pw.monitor()
    pw.create_timeline_plots('/home/josep/pywren_plots', 'rabbitmq')
    pw.clean()
