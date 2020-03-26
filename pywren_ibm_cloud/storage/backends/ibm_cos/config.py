def load_config(config_data):
    if 'ibm_cos' not in config_data:
        raise Exception("ibm_cos section is mandatory in the configuration")

    if config_data['pywren']['compute_backend'] == 'ibm_cf':
        # Private endpoint is mandatory when using IBM CF
        if 'private_endpoint' not in config_data['ibm_cos']:
            raise Exception('You must provide the private_endpoint to access to IBM COS')
        elif 'private' not in config_data['ibm_cos']['private_endpoint']:
            raise Exception('The private_endpoint you provided to access to IBM COS is not valid')
    elif 'private_endpoint' in config_data['ibm_cos']:
        del config_data['ibm_cos']['private_endpoint']

    required_keys_1 = ('endpoint', 'api_key')
    required_keys_2 = ('endpoint', 'secret_key', 'access_key')
    required_keys_3 = ('endpoint', 'ibm:iam_api_key')

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data['ibm_cos'].update(config_data['ibm'])

    if not set(required_keys_1) <= set(config_data['ibm_cos']) and \
       not set(required_keys_2) <= set(config_data['ibm_cos']) and \
       ('endpoint' not in config_data['ibm_cos'] or 'iam_api_key' not in config_data['ibm_cos']
       or config_data['ibm_cos']['iam_api_key'] is None):
        raise Exception('You must provide {}, {} or {} to access to IBM COS'
                        .format(required_keys_1, required_keys_2, required_keys_3))

    if not config_data['ibm_cos']['endpoint'].startswith('http'):
        raise Exception('IBM COS Endpoint must start with http:// or https://')
    if not config_data['ibm_cos']['private_endpoint'].startswith('http'):
        raise Exception('IBM COS Private Endpoint must start with http:// or https://')
