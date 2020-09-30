import os
import sys
import importlib

from lithops.utils import version_str

RUNTIME_DEFAULT = {'3.5': 'ibmfunctions/lithops:3.5:latest',
                   '3.6': 'ibmfunctions/action-python-v3.6:latest',
                   '3.7': 'ibmfunctions/action-python-v3.7:1.6.0',
                   '3.8': 'jsampe/action-python-v3.8:latest'}
RUNTIME_TIMEOUT_DEFAULT = 600  # 10 minutes

LITHOPS_SERVER_PORT = 8080

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_docker.zip')


def load_config(config_data):
    if 'runtime_memory' not in config_data['lithops']:
        config_data['lithops']['runtime_memory'] = None
    if 'runtime_timeout' not in config_data['lithops']:
        config_data['lithops']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['lithops']:
        python_version = version_str(sys.version_info)
        try:
            config_data['lithops']['runtime'] = RUNTIME_DEFAULT[python_version]
        except KeyError:
            raise Exception('Unsupported Python version: {}'.format(python_version))

    config_data['lithops']['remote_invoker'] = True

    if 'storage_backend' not in config_data['lithops']:
        config_data['lithops']['storage_backend'] = 'localhost'

    if 'docker' not in config_data:
        config_data['docker'] = {'host': 'localhost'}

    if config_data['docker']['host'] not in ['127.0.0.1', 'localhost']:

        if 'ssh_user' not in config_data['docker']:
            raise Exception('You must provide ssh credentials to access to the remote host')

        if 'ssh_password' not in config_data['docker']:
            config_data['docker']['ssh_password'] = ''
        else:
            config_data['docker']['ssh_password'] = str(config_data['docker']['ssh_password'])

        if config_data['lithops']['storage_backend'] == 'localhost':
            raise Exception('Localhost storage backend is not supported for Docker remote host')

    if 'workers' not in config_data['lithops']:
        config_data['lithops']['workers'] = None

    if 'ibm_cos' in config_data and 'private_endpoint' in config_data['ibm_cos']:
        del config_data['ibm_cos']['private_endpoint']