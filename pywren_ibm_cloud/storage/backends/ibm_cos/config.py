IBM_AUTH_ENDPOINT_DEFAULT = 'https://iam.cloud.ibm.com/oidc/token'


def load_config(config_data=None):
    if 'ibm_cos' not in config_data:
        raise Exception("ibm_cos section is mandatory in the configuration")

    if 'ibm_iam' not in config_data or config_data['ibm_iam'] is None:
        config_data['ibm_iam'] = {}
    if 'ibm_auth_endpoint' not in config_data['ibm_iam']:
        config_data['ibm_iam']['ibm_auth_endpoint'] = IBM_AUTH_ENDPOINT_DEFAULT

    required_parameters_1 = ('endpoint', 'api_key')
    required_parameters_2 = ('endpoint', 'secret_key', 'access_key')
    required_parameters_3 = ('endpoint', 'ibm_iam:api_key')

    if set(required_parameters_1) <= set(config_data['ibm_cos']) or \
            set(required_parameters_2) <= set(config_data['ibm_cos']) or \
            ('endpoint' in config_data['ibm_cos'] and 'api_key' in config_data['ibm_iam']):
        pass
    else:
        raise Exception('You must provide {}, {} or {} to access to IBM COS'.format(required_parameters_1,
                                                                                    required_parameters_2,
                                                                                    required_parameters_3))

    config_data['ibm_cos']['ibm_iam'] = config_data['ibm_iam']
