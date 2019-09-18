"""
Simple PyWren example using one single function invocation
"""
import pywren_ibm_cloud as pywren


#iterdata = [1, 2, 3, 4]
iterdata = range(10)
#iterdata = [2, 3, 4]

def my_function(x):
    return x + 7

config = {'pywren': {'runtime': '<>','compute_backend': 'knative', 'storage_bucket': 'pywren-knative', 'storage_prefix': 'pywren.jobs'},
          #'knative': {'docker_user': 'iamapikey', 'docker_password': '<iamkey>', 'docker_repo': 'uk.icr.io'},
          'knative': {'docker_user': '<docker-hub user>', 'docker_password': 'docker-hub password', 'docker_repo': 'docker.io'},
          'ibm_cos': {}}

if __name__ == '__main__':
    pw = pywren.ibm_cf_executor(config=config)
    #pw.call_async(my_function, 3)
    pw.map(my_function, iterdata)
    print (pw.get_result())
