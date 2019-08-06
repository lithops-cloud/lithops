import sys
from pywren_ibm_cloud.utils import version_str

RUNTIME_DEFAULT_35 = 'ibmfunctions/pywren:3.5'
RUNTIME_DEFAULT_36 = 'ibmfunctions/action-python-v3.6'
RUNTIME_DEFAULT_37 = 'ibmfunctions/action-python-v3.7'

RUNTIME_TIMEOUT_DEFAULT = 600000  # Default: 600000 milliseconds => 10 minutes
RUNTIME_MEMORY_DEFAULT = 256  # Default memory: 256 MB


def load_config(config_data=None):
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

    if 'ibm_cf' not in config_data:
        raise Exception("ibm_cf section is mandatory in the configuration")

    if 'ibm_iam' in config_data['ibm_cf']:
        del config_data['ibm_cf']['ibm_iam']

    required_parameters_0 = ('endpoint', 'namespace')
    if set(required_parameters_0) <= set(config_data['ibm_cf']):
        # old format. convert to new format
        endpoint = config_data['ibm_cf'].pop('endpoint')
        namespace = config_data['ibm_cf'].pop('namespace')
        api_key = config_data['ibm_cf'].pop('api_key', None)
        region = endpoint.split('//')[1].split('.')[0].replace('-', '_')

        for k in list(config_data['ibm_cf']):
            # Delete unnecessary keys
            del config_data['ibm_cf'][k]

        config_data['pywren']['compute_backend_region'] = region
        config_data['ibm_cf'][region] = {'endpoint': endpoint, 'namespace': namespace}
        if api_key:
            config_data['ibm_cf'][region]['api_key'] = api_key
    else:
        # new format
        for region in config_data['ibm_cf']:
            required_parameters_1 = ('endpoint', 'namespace', 'api_key')
            required_parameters_2 = ('endpoint', 'namespace', 'ibm_iam:api_key')

            if set(required_parameters_1) <= set(config_data['ibm_cf'][region]) or \
               set(required_parameters_0) <= set(config_data['ibm_cf'][region]) and 'api_key' in config_data['ibm_iam']:
                pass
            else:
                raise Exception('You must provide {} or {} to access to IBM Cloud Functions'.format(required_parameters_1,
                                                                                                    required_parameters_2))

        if 'compute_backend_region' not in config_data['pywren']:
            config_data['pywren']['compute_backend_region'] = list(config_data['ibm_cf'].keys())[0]

        cbr = config_data['pywren']['compute_backend_region']
        if cbr is not None and cbr not in config_data['ibm_cf']:
            raise Exception('Invalid Compute backend region: {}'.format(cbr))

    if 'ibm_iam' in config_data and config_data['ibm_iam'] is not None:
        config_data['ibm_cf']['ibm_iam'] = config_data['ibm_iam']
