import os
import tempfile
import multiprocessing
from psutil import virtual_memory
from pywren_ibm_cloud.config import LOGS_PREFIX


RUNTIME_NAME_DEFAULT = 'localhost'
RUNTIME_TIMEOUT_DEFAULT = 600  # 10 minutes

TEMP = tempfile.gettempdir()
STORAGE_BASE_DIR = os.path.join(TEMP)
LOCAL_LOGS_DIR = os.path.join(STORAGE_BASE_DIR, LOGS_PREFIX)


def load_config(config_data):
    config_data['pywren']['runtime'] = RUNTIME_NAME_DEFAULT
    mem = virtual_memory()
    config_data['pywren']['runtime_memory'] = round(mem.total/1024/1024, 2)
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'localhost' not in config_data:
        config_data['localhost'] = {}

    if 'workers' in config_data['pywren']:
        config_data['localhost']['workers'] = config_data['pywren']['workers']
    else:
        if 'workers' not in config_data['localhost']:
            total_cores = multiprocessing.cpu_count()
            config_data['pywren']['workers'] = total_cores
            config_data['localhost']['workers'] = total_cores
        else:
            config_data['pywren']['workers'] = config_data['localhost']['workers']
