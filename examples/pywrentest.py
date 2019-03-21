"""
Simple PyWren example using one single function invocation
"""
import pywren_ibm_cloud as pywren
import time


total = 1000


def my_map_function(x):
    time.sleep(5)
    return x


def invoker(x):
    pw = pywren.ibm_cf_executor()
    return pw.map(my_map_function, range(total))


def my_reduce_function(results):
    return 0


if __name__ == '__main__':

    #pw = pywren.ibm_cf_executor(runtime='pywren-dlib-runtime_3.6')
    t1 = time.time()
    pw = pywren.ibm_cf_executor()
    #pw.call_async(my_function, 3, extra_env={'SHOW_MEMORY_USAGE': True})
    #pw.call_async(invoker, 1)
    #pw.map_reduce(my_map_function, range(total), my_reduce_function)
    pw.map(my_map_function, range(total))
    pw.monitor()
    #pw.get_result()
    t2 = time.time()

    #result = pw.get_result()

    #run_statuses = result['run_statuses']
    #invoke_statuses = result['invoke_statuses']

    #pw.create_timeline_plots('/home/jsampe/pywren_plots', 'no_rabbitmq', run_statuses=run_statuses, invoke_statuses=invoke_statuses)
    pw.create_timeline_plots('/home/josep/pywren_plots', 'no_rabbitmq')

    pw.clean()

    print('Done! - Waiting Time: {} seconds\n'.format(round(t2-t1, 3)))

    t1 = time.time()
    pw = pywren.ibm_cf_executor(use_rabbitmq=True)
    #pw.map(my_function, range(total), remote_invocation=True)
    pw.map(my_map_function, range(total))
    pw.monitor()
    t2 = time.time()

    pw.create_timeline_plots('/home/josep/pywren_plots', 'rabbitmq')
    pw.clean()

    print('Done! - Waiting Time: {} seconds\n'.format(round(t2-t1, 3)))
