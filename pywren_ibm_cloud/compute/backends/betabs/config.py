import os
import sys
from pywren_ibm_cloud.utils import version_str

RUNTIME_DEFAULT = {'3.5': 'cactusone/pywren-betabs-v3.5',
                   '3.6': 'cactusone/pywren-betabs-v3.6',
                   '3.7': 'cactusone/pywren-betabs-v3.7',
                   '3.8': 'cactusone/pywren-betabs-v3.8'}

RUNTIME_TIMEOUT_DEFAULT = 600  # Default: 600 seconds => 10 minutes
RUNTIME_MEMORY_DEFAULT = 128  # Default memory: 256 MB
MAX_CONCURRENT_WORKERS = 1200
CPU_DEFAULT = 1 # default number of CPU

DEFAULT_API_VERSION = 'coligo.cloud.ibm.com/v1alpha1'
DEFAULT_GROUP = "coligo.cloud.ibm.com"
DEFAULT_VERSION = "v1alpha1"


JOB_RUN_RESOURCE = {
    'apiVersion': '', 
    'kind': 'JobRun', 
    'metadata': {
            'name': ''
            },
    'spec': {
        'jobDefinitionSpec': {
            'containers': [{
                'name': 'run', 
                'image': '',
                'command' : ['/usr/local/bin/python'],
                'args' : [
                '/pywren/pywrenentry.py',
                '$(ACTION)',
                '$(PAYLOAD)'],
                'env': [{
                    'name' :'ACTION',
                    'value' : ''
                    },{
                    'name' :'PAYLOAD',
                    'value' : ''
                    }],
                'resources': {
                    'requests': {
                        'memory': '128Mi',
                        'cpu': '1'
                        }
                    }
                }
            ]}
        }
    }


FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'pywren_betabs.zip')


def load_config(config_data):
    if 'runtime_memory' not in config_data['pywren']:
        config_data['pywren']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['pywren']:
        python_version = version_str(sys.version_info)
        try:
            config_data['pywren']['runtime'] = RUNTIME_DEFAULT[python_version]
        except KeyError:
            raise Exception('Unsupported Python version: {}'.format(python_version))
    if 'workers' not in config_data['pywren'] or \
       config_data['pywren']['workers'] > MAX_CONCURRENT_WORKERS:
        config_data['pywren']['workers'] = MAX_CONCURRENT_WORKERS
    
    if 'betabs' in config_data:
        if 'runtime_cpu' not in config_data['betabs']:
            config_data['betabs']['runtime_cpu'] = CPU_DEFAULT
        if 'api_version' not in config_data['betabs']:
            config_data['betabs']['api_version'] = DEFAULT_API_VERSION
        if 'group' not in config_data['betabs']:
            config_data['betabs']['group'] = DEFAULT_GROUP
        if 'version' not in config_data['betabs']:
            config_data['betabs']['version'] = DEFAULT_VERSION
