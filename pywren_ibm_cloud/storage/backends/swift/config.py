def load_config(config_data):
    if 'swift' not in config_data:
        raise Exception("swift section is mandatory in the configuration")

    required_parameters = ('auth_url', 'user_id', 'project_id', 'password', 'region')

    if set(required_parameters) <= set(config_data['swift']):
        pass
    else:
        raise Exception('You must provide {} to access to Swift'.format(required_parameters))
