'''
Created on 21 May 2020

@author: gilv
'''
import os
import zipfile
import logging
import pywren_ibm_cloud

logger = logging.getLogger(__name__)

def create_function_handler_zip(config, main_exec_file = '__main__.py', 
                                backend_location  = None):
    logger.debug("Creating function handler zip in {}".format(config.FH_ZIP_LOCATION))

    def add_folder_to_zip(zip_file, full_dir_path, sub_dir=''):
        for file in os.listdir(full_dir_path):
            full_path = os.path.join(full_dir_path, file)
            if os.path.isfile(full_path):
                zip_file.write(full_path, os.path.join('pywren_ibm_cloud', sub_dir, file))
            elif os.path.isdir(full_path) and '__pycache__' not in full_path:
                add_folder_to_zip(zip_file, full_path, os.path.join(sub_dir, file))

    try:
        with zipfile.ZipFile(config.FH_ZIP_LOCATION, 'w', zipfile.ZIP_DEFLATED) as pywren_zip:
            current_location = os.path.dirname(os.path.abspath(backend_location))
            module_location = os.path.dirname(os.path.abspath(pywren_ibm_cloud.__file__))
            main_file = os.path.join(current_location, 'entry_point.py')
            pywren_zip.write(main_file, main_exec_file)
            add_folder_to_zip(pywren_zip, module_location)
    except Exception as e:
        raise Exception('Unable to create the {} package: {}'.format(config.FH_ZIP_LOCATION, e))
    
def format_action_name(runtime_name, runtime_memory):
    runtime_name = runtime_name.replace('/', '_').replace(':', '_')
    return '{}_{}MB'.format(runtime_name, runtime_memory)
