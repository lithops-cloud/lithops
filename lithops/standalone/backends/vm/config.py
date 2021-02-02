
def load_config(config_data):
    section = 'vm'

    if 'ip_address' not in config_data[section]:
        msg = 'ip_address is mandatory in {} section of the configuration'.format(section)
        raise Exception(msg)

    if 'ssh_user' not in config_data[section]:
        msg = 'ssh_user is mandatory in {} section of the configuration'.format(section)
        raise Exception(msg)

    config_data['standalone']['auto_dismantle'] = False
