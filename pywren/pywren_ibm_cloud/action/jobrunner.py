#
# Copyright 2018 PyWren Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import base64
import shutil
import json
import sys
import time
import logging
import inspect
from six.moves import cPickle as pickle
from pywren_ibm_cloud import wrenlogging
from pywren_ibm_cloud.storage import storage
from pywren_ibm_cloud.storage.backends.cos import COSBackend
from pywren_ibm_cloud.storage.backends.swift import SwiftBackend
from pywren_ibm_cloud.libs.tblib import pickling_support

pickling_support.install()

level = logging.DEBUG
logger = logging.getLogger('jobrunner')
logger.setLevel(level)
wrenlogging.ow_config(level)

logger.info("Welcome to job runner")


def b64str_to_bytes(str_data):
    str_ascii = str_data.encode('ascii')
    byte_data = base64.b64decode(str_ascii)
    return byte_data

# initial output file in case job fails
output_dict = {'result': None,
               'success': False}

pickled_output = pickle.dumps(output_dict)
jobrunner_config_filename = sys.argv[1]

jobrunner_config = json.load(open(jobrunner_config_filename, 'r'))
# Create Storage handler
storage_config = json.loads(os.environ.get('STORAGE_CONFIG', ''))
internal_storage = storage.InternalStorage(storage_config)

func_key = jobrunner_config['func_key']

data_key = jobrunner_config['data_key']
data_byte_range = jobrunner_config['data_byte_range']

output_key = jobrunner_config['output_key']

# Jobrunner stats are fieldname float
jobrunner_stats_filename = jobrunner_config['stats_filename']
# open the stats filename
stats_fid = open(jobrunner_stats_filename, 'w')


def write_stat(stat, val):
    stats_fid.write("{} {:f}\n".format(stat, val))
    stats_fid.flush()

try:
    logger.info("Getting function from COS")
    func_download_time_t1 = time.time()
    func_obj = internal_storage.get_func(func_key)
    loaded_func_all = pickle.loads(func_obj)
    func_download_time_t2 = time.time()
    write_stat('func_download_time',
               func_download_time_t2-func_download_time_t1)
    logger.info("Finished getting Function")

    # save modules, before we unpickle actual function
    PYTHON_MODULE_PATH = jobrunner_config['python_module_path']

    logger.info("Writing Function dependencies to local disk")
    shutil.rmtree(PYTHON_MODULE_PATH, True)  # delete old modules
    os.mkdir(PYTHON_MODULE_PATH)
    sys.path.append(PYTHON_MODULE_PATH)

    for m_filename, m_data in loaded_func_all['module_data'].items():
        m_path = os.path.dirname(m_filename)

        if len(m_path) > 0 and m_path[0] == "/":
            m_path = m_path[1:]
        to_make = os.path.join(PYTHON_MODULE_PATH, m_path)
        try:
            os.makedirs(to_make)
        except OSError as e:
            if e.errno == 17:
                pass
            else:
                raise e
        full_filename = os.path.join(to_make, os.path.basename(m_filename))
        #print "creating", full_filename
        with open(full_filename, 'wb') as fid:
            fid.write(b64str_to_bytes(m_data))
    logger.info("Finished writing Function dependencies")

    #logger.info("Finished writing {} module files".format(len(loaded_func_all['module_data'])))
    #logger.debug(subprocess.check_output("find {}".format(PYTHON_MODULE_PATH), shell=True))
    #logger.debug(subprocess.check_output("find {}".format(os.getcwd()), shell=True))

    # now unpickle function; it will expect modules to be there
    logger.info("Unpickle Function")
    loaded_func = pickle.loads(loaded_func_all['func'])
    logger.info("Finished Function unpickle")

    extra_get_args = {}
    if data_byte_range is not None:
        range_str = 'bytes={}-{}'.format(*data_byte_range)
        extra_get_args['Range'] = range_str

    # GET function parameters
    logger.info("Getting function data")
    data_download_time_t1 = time.time()
    data_obj = internal_storage.get_data(data_key, extra_get_args=extra_get_args)
    logger.info("Finished getting Function data")
    logger.info("Unpickle Function data")
    loaded_data = pickle.loads(data_obj)
    logger.info("Finished unpickle Function data")
    data_download_time_t2 = time.time()
    write_stat('data_download_time',
               data_download_time_t2-data_download_time_t1)

    # Verify storage parameters - Create clients
    func_sig = inspect.signature(loaded_func)
    
    if 'storage' in func_sig.parameters:
        # 'storage' generic parameter used in map_reduce method
        if 'ibm_cos' in storage_config:
            mr_storage_client = COSBackend(storage_config['ibm_cos'])
        elif 'swift' in storage_config:
            mr_storage_client = SwiftBackend(storage_config['swift'])
        
        loaded_data['storage'] = mr_storage_client
    
    if 'ibm_cos' in func_sig.parameters:
        ibm_boto3_client = COSBackend(storage_config['ibm_cos']).get_client()
        loaded_data['ibm_cos'] = ibm_boto3_client
    
    if 'swift' in func_sig.parameters:
        swift_client = SwiftBackend(storage_config['swift'])
        loaded_data['swift'] = swift_client
    
    if 'internal_storage' in func_sig.parameters:
        loaded_data['internal_storage'] = internal_storage

    logger.info("Function: Going to execute '{}()'".format(str(loaded_func.__name__)))
    print('------------------- FUNCTION LOG -------------------')
    func_exec_time_t1 = time.time()
    y = loaded_func(**loaded_data)
    func_exec_time_t2 = time.time()
    print('----------------------------------------------------')

    logger.info("Function: Success execution")
    write_stat('function_exec_time', func_exec_time_t2-func_exec_time_t1)
    output_dict = {'result': y,
                   'success': True,
                   #'sys.path' : sys.path
                   }
    pickled_output = pickle.dumps(output_dict)

except Exception as e:
    exc_type, exc_value, exc_traceback = sys.exc_info()
    #traceback.print_tb(exc_traceback)

    # Shockingly often, modules like subprocess don't properly
    # call the base Exception.__init__, which results in them
    # being unpickleable. As a result, we actually wrap this in a try/catch block
    # and more-carefully handle the exceptions if any part of this save / test-reload
    # fails
    logger.error("There was an exception: {}".format(str(e)))
    print('----------------------------------------------------')
    try:
        pickled_output = pickle.dumps({'result': e,
                                       'exc_type': exc_type,
                                       'exc_value': exc_value,
                                       'exc_traceback': exc_traceback,
                                       'sys.path': sys.path,
                                       'success': False})

        # this is just to make sure they can be unpickled
        pickle.loads(pickled_output)

    except Exception as pickle_exception:
        pickled_output = pickle.dumps({'result': str(e),
                                       'exc_type': str(exc_type),
                                       'exc_value': str(exc_value),
                                       'exc_traceback': exc_traceback,
                                       'exc_traceback_str': str(exc_traceback),
                                       'sys.path': sys.path,
                                       'pickle_fail': True,
                                       'pickle_exception': pickle_exception,
                                       'success': False})
finally:
    store_result = True
    if 'STORE_RESULT' in os.environ:
        store_result = eval(os.environ['STORE_RESULT'])

    if store_result:
        output_upload_timestamp_t1 = time.time()
        internal_storage.put_data(output_key, pickled_output)
        output_upload_timestamp_t2 = time.time()
        write_stat("output_upload_time",
                   output_upload_timestamp_t2 - output_upload_timestamp_t1)
    logger.info("Jobrunner finished")
