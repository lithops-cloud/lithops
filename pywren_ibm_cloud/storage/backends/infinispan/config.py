def load_config(config_data):
    if 'infinispan' not in config_data:
        raise Exception("infinispan section is mandatory in the configuration")

    required_keys_1 = ('endpoint', 'username', 'password')

    if not set(required_keys_1) <= set(config_data['infinispan']):
        raise Exception('You must provide {} to access to Infinispan'
                        .format(required_keys_1))
