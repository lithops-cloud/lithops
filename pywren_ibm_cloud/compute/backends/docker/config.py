import os
import sys
import tempfile
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.config import LOGS_PREFIX

RUNTIME_DEFAULT = {'3.5': 'ibmfunctions/pywren:3.5',
                   '3.6': 'ibmfunctions/action-python-v3.6',
                   '3.7': 'ibmfunctions/action-python-v3.7:1.6.0',
                   '3.8': 'jsampe/action-python-v3.8'}
RUNTIME_TIMEOUT_DEFAULT = 600  # 10 minutes

PYWREN_SERVER_PORT = 8080

TEMP = tempfile.gettempdir()
STORAGE_BASE_DIR = os.path.join(TEMP)
LOCAL_LOGS_DIR = os.path.join(STORAGE_BASE_DIR, LOGS_PREFIX)
FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'pywren_docker.zip')


def load_config(config_data):
    if 'runtime_memory' not in config_data['pywren']:
        config_data['pywren']['runtime_memory'] = None
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['pywren']:
        python_version = version_str(sys.version_info)
        try:
            config_data['pywren']['runtime'] = RUNTIME_DEFAULT[python_version]
        except KeyError:
            raise Exception('Unsupported Python version: {}'.format(python_version))

    if 'docker' not in config_data:
        config_data['docker'] = {'host': '127.0.0.1'}

    if 'workers' not in config_data['pywren']:
        config_data['pywren']['workers'] = None
