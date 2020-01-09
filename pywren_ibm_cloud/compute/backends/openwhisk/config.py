import os
import sys
from pywren_ibm_cloud.utils import version_str

RUNTIME_DEFAULT_35 = 'ibmfunctions/pywren:3.5'
RUNTIME_DEFAULT_36 = 'ibmfunctions/action-python-v3.6'
RUNTIME_DEFAULT_37 = 'ibmfunctions/action-python-v3.7:1.6.0'

RUNTIME_TIMEOUT_DEFAULT = 300  # Default: 300 seconds => 5 minutes
RUNTIME_MEMORY_DEFAULT = 256  # Default memory: 256 MB
CONCURRENT_WORKERS_DEFAULT = 100


FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'pywren_openwhisk.zip')


def load_config(config_data):
    if 'openwhisk' not in config_data:
        raise Exception("openwhisk section is mandatory in configuration")

    required_keys = ('endpoint', 'namespace', 'api_key')
    if not set(required_keys) <= set(config_data['openwhisk']):
        raise Exception('You must provide {} to access to openwhisk'.format(required_keys))

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
    if 'workers' not in config_data['pywren']:
        config_data['pywren']['workers'] = CONCURRENT_WORKERS_DEFAULT
