def load_config(config_data):
    if 'gcsfs' not in config_data:
        raise Exception("gcsfs section is mandatory in the configuration")

    required_parameters = ('project_id',)

    if set(required_parameters) <= set(config_data['gcsfs']):
        pass
    else:
        raise Exception('You must provide {} to access to gcsfs'.format(required_parameters))
