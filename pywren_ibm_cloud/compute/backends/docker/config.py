import sys
import multiprocessing
from pywren_ibm_cloud.utils import version_str

RUNTIME_DEFAULT_35 = 'jsampe/docker-pywren-runtime-v3.5'
RUNTIME_DEFAULT_36 = 'jsampe/docker-pywren-runtime-v3.6'
RUNTIME_DEFAULT_37 = 'jsampe/docker-pywren-runtime-v3.7'
RUNTIME_TIMEOUT_DEFAULT = 600  # 10 minutes
RUNTIME_MEMORY_DEFAULT = 256  # 256 MB


def load_config(config_data):
    if 'runtime_memory' not in config_data['pywren']:
        config_data['pywren']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['pywren']:
        this_version_str = version_str(sys.version_info)
        if this_version_str == '3.5':
            config_data['pywren']['runtime'] = RUNTIME_DEFAULT_35
        elif this_version_str == '3.6':
            config_data['pywren']['runtime'] = RUNTIME_DEFAULT_36
        elif this_version_str == '3.7':
            config_data['pywren']['runtime'] = RUNTIME_DEFAULT_37

    total_cores = multiprocessing.cpu_count()
    if 'docker' not in config_data:
        config_data['docker'] = {}
        config_data['docker']['workers'] = total_cores
    elif 'workers' not in config_data['docker']:
        config_data['docker']['workers'] = total_cores
