"""
Simple PyWren example using rabbitmq to monitor map function invocations
"""
import pywren_ibm_cloud as pywren
import time
import logging
#logging.basicConfig(level=logging.DEBUG)

total = 1000


def my_function(x):
    time.sleep(5)
    #os.urandom(1024*1024)

    #if not os.path.isfile('/tmp/hot.txt'):
    #    with open('/tmp/hot.txt', 'w'):
    #        pass
    #    status = 'COLD'
    #else:
    #    status = 'HOT'

    #ip_address = subprocess.check_output("hostname -I", shell=True).decode("ascii").strip()

    return x+7
#runtime='jsampe/python3action', 

#pw = pywren.ibm_cf_executor(runtime="idoye/fasttext-hyperparameters", runtime_memory=2048)

pw = pywren.ibm_cf_executor(runtime_memory=256, rabbitmq_monitor=True)
pw.map(my_function, range(total), remote_invocation=True)
pw.monitor()
#results = pw.get_result()
pw.create_timeline_plots('/home/josep/pywren_plots', 'no_rabbitmq')
pw.clean()
#print(results)

#for res in results:
#    if res[0] == 'COLD':
#        print(res)
# counter = collections.Counter(results)
# print(counter)


# pw = pywren.ibm_cf_executor(runtime_memory=256, rabbitmq_monitor=True)
# pw.map(my_function, range(total))
# pw.monitor()
# pw.create_timeline_plots('/home/josep/pywren_plots', 'rabbitmq')
# pw.clean()
