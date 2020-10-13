
def load_config(config_data):
    section = 'vm'

    if 'host' not in config_data[section]:
        msg = 'host is mandatory in {} section of the configuration'.format(section)
        raise Exception(msg)

    if 'ssh_user' not in config_data[section]:
        msg = 'ssh_user is mandatory in {} section of the configuration'.format(section)
        raise Exception(msg)

    config_data['standalone']['auto_dismantle'] = False
