def load_config(config_data=None):
    if 'redis' not in config_data:
        raise Exception("redis section is mandatory in the configuration")

    # required_parameters = ('host', 'internal_endpoint', 'access_key_id', 'access_key_secret')

    # if set(required_parameters) > set(config_data['aliyun_oss']):
    #     raise Exception('You must provide {} to access to Aliyun Object Storage Service'.format(required_parameters))

