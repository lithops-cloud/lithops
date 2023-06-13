import os
from lithops.constants import TEMP_DIR


DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 5 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'max_workers': 300,
    'worker_processes': 1,
    'invoke_pool_threads': 64,
}

CONNECTION_POOL_SIZE = 300

APPLICATION_NAME = 'lithops'
BUILD_DIR = os.path.join(TEMP_DIR, 'OracleRuntimeBuild')

AVAILABLE_PY_RUNTIMES = {
    '3.8': 'python3',
}

REQUIREMENTS_FILE = """
    oci
    pika
    tblib
    cloudpickle
    ps-mem
"""

REQ_PARAMS = ('tenancy', 'user', 'fingerprint', 'key_file', 'region')

def load_config(config_data=None):
    if 'oracle' not in config_data:
        raise Exception("'oracle' section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['oracle']:
            msg = f'"{param}" is mandatory in the "oci" section of the configuration'
            raise Exception(msg)

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['oracle_f']:
            config_data['oracle_f'][key] = DEFAULT_CONFIG_KEYS[key]

    if 'vcn' not in config_data['oracle_f'] or 'subnet_ids' not in config_data['oracle_f']['vcn']:
        raise Exception("'vcn' and 'subnet_ids' are mandatory in the 'oracle_f' section of the configuration")
    else:
        config_data['oracle_f']['subnet_ids'] = config_data['oracle_f']['vcn']['subnet_ids']

    config_data['oracle_f'].update(config_data['oracle'])
    