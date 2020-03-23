import os
import sys
from pywren_ibm_cloud.utils import version_str

RUNTIME_DEFAULT = {'3.5': 'ibmfunctions/pywren:3.5',
                   '3.6': 'ibmfunctions/action-python-v3.6',
                   '3.7': 'ibmfunctions/action-python-v3.7:1.6.0',
                   '3.8': 'jsampe/action-python-v3.8'}

RUNTIME_TIMEOUT_DEFAULT = 600  # Default: 600 seconds => 10 minutes
RUNTIME_MEMORY_DEFAULT = 256  # Default memory: 256 MB
MAX_CONCURRENT_WORKERS = 1200


FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'pywren_ibmcf.zip')


def load_config(config_data):
    if 'runtime_memory' not in config_data['pywren']:
        config_data['pywren']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['pywren']:
        this_version_str = version_str(sys.version_info)
        try:
            config_data['pywren']['runtime'] = RUNTIME_DEFAULT[this_version_str]
        except KeyError:
            raise Exception('Unsupported Python version: {}'.format(this_version_str))
    if 'workers' not in config_data['pywren'] or \
       config_data['pywren']['workers'] > MAX_CONCURRENT_WORKERS:
        config_data['pywren']['workers'] = MAX_CONCURRENT_WORKERS

    if 'ibm_cf' not in config_data:
        raise Exception("ibm_cf section is mandatory in the configuration")

    required_parameters_0 = ('endpoint', 'namespace')
    required_parameters_1 = ('endpoint', 'namespace', 'api_key')
    required_parameters_2 = ('endpoint', 'namespace', 'namespace_id', 'ibm:iam_api_key')

    # Check old format. Convert to new format
    if set(required_parameters_0) <= set(config_data['ibm_cf']):
        endpoint = config_data['ibm_cf'].pop('endpoint')
        namespace = config_data['ibm_cf'].pop('namespace')
        api_key = config_data['ibm_cf'].pop('api_key', None)
        namespace_id = config_data['ibm_cf'].pop('namespace_id', None)
        region = endpoint.split('//')[1].split('.')[0].replace('-', '_')

        for k in list(config_data['ibm_cf']):
            # Delete unnecessary keys
            del config_data['ibm_cf'][k]

        config_data['ibm_cf']['regions'] = {}
        config_data['pywren']['compute_backend_region'] = region
        config_data['ibm_cf']['regions'][region] = {'endpoint': endpoint, 'namespace': namespace}
        if api_key:
            config_data['ibm_cf']['regions'][region]['api_key'] = api_key
        if namespace_id:
            config_data['ibm_cf']['regions'][region]['namespace_id'] = namespace_id
    # -------------------

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data['ibm_cf'].update(config_data['ibm'])

    for region in config_data['ibm_cf']['regions']:
        if not set(required_parameters_1) <= set(config_data['ibm_cf']['regions'][region]) \
           and (not set(required_parameters_0) <= set(config_data['ibm_cf']['regions'][region])
           or 'namespace_id' not in config_data['ibm_cf']['regions'][region] or 'iam_api_key' not in config_data['ibm_cf']):
            raise Exception('You must provide {} or {} to access to IBM Cloud '
                            'Functions'.format(required_parameters_1, required_parameters_2))

    cbr = config_data['pywren'].get('compute_backend_region')
    if type(cbr) == list:
        for region in cbr:
            if region not in config_data['ibm_cf']['regions']:
                raise Exception('Invalid Compute backend region: {}'.format(region))
    else:
        if cbr is None:
            cbr = list(config_data['ibm_cf']['regions'].keys())[0]
            config_data['pywren']['compute_backend_region'] = cbr

        if cbr not in config_data['ibm_cf']['regions']:
            raise Exception('Invalid Compute backend region: {}'.format(cbr))
