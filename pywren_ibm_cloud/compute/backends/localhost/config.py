import multiprocessing
from psutil import virtual_memory


RUNTIME_NAME_DEFAULT = 'localhost'
RUNTIME_TIMEOUT_DEFAULT = 600  # 10 minutes


def load_config(config_data):
    config_data['pywren']['runtime'] = RUNTIME_NAME_DEFAULT
    mem = virtual_memory()
    config_data['pywren']['runtime_memory'] = round(mem.total/1024/1024, 2)
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    total_cores = multiprocessing.cpu_count()
    if 'localhost' not in config_data:
        config_data['localhost'] = {}
        config_data['localhost']['workers'] = total_cores
    elif 'workers' not in config_data['localhost']:
        config_data['localhost']['workers'] = total_cores
