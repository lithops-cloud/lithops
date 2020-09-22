def load_config(config_data):
    if 'ceph' not in config_data:
        raise Exception("ceph section is mandatory in the configuration")

    required_keys = ('endpoint', 'secret_key', 'access_key')

    if not set(required_keys) <= set(config_data['ceph']):
        raise Exception('You must provide {} to access to Ceph'.format(required_keys))

    if not config_data['ceph']['endpoint'].startswith('http'):
        raise Exception('Ceph endpoint must start with http:// or https://')
