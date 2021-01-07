import datetime

MANDATORY_PARAMETERS_CREATE = ['endpoint', 'security_group_id', 'subnet_id', 'key_id', 'resource_group_id', 'vpc_id', 'image_id', 'zone_name']

MANDATORY_PARAMETERS_OPERATE = ['endpoint', 'instance_id', 'ip_address']

def _is_auto_create_mode(config_data):
    if 'exec_mode' in config_data['standalone'] and config_data['standalone']['exec_mode'] == 'create':
        return True
    return False

def load_config(config_data):
    section = 'ibm_vpc'

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data[section].update(config_data['ibm'])
    else:
        msg = 'IBM IAM api key is mandatory in ibm section of the configuration'
        raise Exception(msg)
    if _is_auto_create_mode(config_data):
        for param in MANDATORY_PARAMETERS_CREATE:
            if param not in config_data[section]:
                msg = '{} is mandatory in {} section of the configuration'.format(param, section)
                raise Exception(msg)
    else:
        for param in MANDATORY_PARAMETERS_OPERATE:
            if param not in config_data[section]:
                msg = '{} is mandatory in {} section of the configuration'.format(param, section)
                raise Exception(msg)

    if 'version' not in config_data:
        # it is not safe to use version as today() due to timezone differences. may fail at midnight. better use yesterday
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        config_data[section]['version'] = yesterday.strftime('%Y-%m-%d')

    if 'generation' not in config_data:
        config_data[section]['generation'] = 2

    if 'volume_tier_name' not in config_data[section]:
        config_data[section]['volume_tier_name'] = '10iops-tier'

    if 'profile_name' not in config_data[section]:
        config_data[section]['profile_name'] = 'bx2-8x32'

    if _is_auto_create_mode(config_data) and 'delete_on_dismantle' not in config_data[section]:
        config_data[section]['delete_on_dismantle'] = True
    elif 'delete_on_dismantle' not in config_data[section]:
        config_data[section]['delete_on_dismantle'] = False

    if 'custom_lithops_image' not in config_data[section]:
        config_data[section]['custom_lithops_image'] = False
