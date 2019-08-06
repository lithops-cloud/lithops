def load_config(config_data=None):
    if 'ibm_cos' not in config_data:
        raise Exception("ibm_cos section is mandatory in the configuration")

    required_parameters_1 = ('endpoint', 'api_key')
    required_parameters_2 = ('endpoint', 'secret_key', 'access_key')
    required_parameters_3 = ('endpoint', 'ibm_iam:api_key')

    if set(required_parameters_1) <= set(config_data['ibm_cos']) or \
       set(required_parameters_2) <= set(config_data['ibm_cos']) or \
       ('endpoint' in config_data['ibm_cos'] and 'ibm_iam' in config_data and 'api_key' in config_data['ibm_iam']):
        pass
    else:
        raise Exception('You must provide {}, {} or {} to access to IBM COS'.format(required_parameters_1,
                                                                                    required_parameters_2,
                                                                                    required_parameters_3))

    if 'ibm_iam' in config_data and config_data['ibm_iam'] is not None:
        config_data['ibm_cos']['ibm_iam'] = config_data['ibm_iam']
