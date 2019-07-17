"""
Simple PyWren example for invoking knative serving http sync api
"""
import pywren_ibm_cloud as pywren


iterdata = [1, 2, 3, 4]

def my_function(x):
    return x + 7

config = {'pywren': {'compute_backend': 'knative', 'runtime': 'pywren-action', 'storage_bucket': 'pywren-knative', 'storage_prefix': 'pywren.jobs'},
          'compute_backend': 'knative', 
          'knative': {'endpoint': <IP:PORT>, 'host': 'pywren-action.default.example.com'},
          'ibm_cos': {'endpoint': 'http://s3-api.us-geo.objectstorage.softlayer.net',
                      'access_key': '',
                      'secret_key': ''}}

if __name__ == '__main__':
    pw = pywren.ibm_cf_executor(config=config)
    #pw.call_async(my_function, 3)
    pw.map(my_function, iterdata)
    print (pw.get_result())
