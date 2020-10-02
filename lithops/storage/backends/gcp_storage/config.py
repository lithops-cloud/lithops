
def load_config(config_data=None):
    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    required_parameters_0 = (
        'project_name', 
        'service_account',
        'credentials_path')
    if not set(required_parameters_0) <= set(config_data['gcp']):
        raise Exception("'project_name', 'service_account' and 'credentials_path' "
        "are mandatory under 'gcp' section")

    if 'region' not in config_data['gcp']:
        config_data['gcp']['region'] = config_data['lithops']['compute_backend_region']

    config_data['gcp_storage'] = config_data['gcp'].copy()
