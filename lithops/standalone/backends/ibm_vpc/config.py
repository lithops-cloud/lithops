import datetime


def load_config(config_data):
    section = 'ibm_vpc'

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data[section].update(config_data['ibm'])
    else:
        msg = 'IBM IAM api key is mandatory in ibm section of the configuration'
        raise Exception(msg)

    if 'endpoint' not in config_data[section]:
        msg = 'endpoint is mandatory in {} section of the configuration'.format(section)
        raise Exception(msg)

    if 'instance_id' not in config_data[section]:
        msg = 'instance_id is mandatory in {} section of the configuration'.format(section)
        raise Exception(msg)

    if 'version' not in config_data:
        # it is not safe to use version as today() due to timezone differences. may fail at midnight. better use yesterday
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        config_data[section]['version'] = yesterday.strftime('%Y-%m-%d')

    if 'generation' not in config_data:
        config_data[section]['generation'] = 2
