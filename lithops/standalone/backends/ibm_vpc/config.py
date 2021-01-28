import datetime


MANDATORY_PARAMETERS_1 = ['endpoint',
                          'vpc_name',
                          'resource_group_id',
                          'key_id']

MANDATORY_PARAMETERS_2 = ['endpoint',
                          'vpc_id',
                          'resource_group_id',
                          'key_id',
                          'subnet_id'
                          'security_group_id']


MANDATORY_PARAMETERS_3 = ['endpoint',
                          'instance_id',
                          'floating_ip']

CLOUD_CONFIG = """
#cloud-config
runcmd:
    - echo 'root:lithops' | chpasswd
    - sed -i '/#PermitRootLogin without-password/c\PermitRootLogin yes' /etc/ssh/sshd_config
    - systemctl restart sshd
"""


def load_config(config_data):
    section = 'ibm_vpc'

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data[section].update(config_data['ibm'])
    else:
        msg = 'IBM IAM api key is mandatory in ibm section of the configuration'
        raise Exception(msg)

    if 'exec_mode' in config_data['standalone'] \
       and config_data['standalone'] == 'create':
        params_to_check = MANDATORY_PARAMETERS_2
    else:
        params_to_check = MANDATORY_PARAMETERS_3

    """
    for param in params_to_check:
        if param not in config_data[section]:
            msg = '{} is mandatory in {} section of the configuration'.format(param, section)
            raise Exception(msg)
    """

    if 'version' not in config_data:
        # it is not safe to use version as today() due to timezone differences. may fail at midnight. better use yesterday
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        config_data[section]['version'] = yesterday.strftime('%Y-%m-%d')

    if 'generation' not in config_data:
        config_data[section]['generation'] = 2

    if 'volume_tier_name' not in config_data[section]:
        config_data[section]['volume_tier_name'] = 'general-purpose'

    if 'profile_name' not in config_data[section]:
        config_data[section]['profile_name'] = 'cx2-2x4'

    if 'image_id' not in config_data[section]:
        config_data[section]['image_id'] = 'r014-b7da49af-b46a-4099-99a4-c183d2d40ea8'

    region = config_data[section]['endpoint'].split('//')[1].split('.')[0]
    if 'zone_name' not in config_data[section]:
        config_data[section]['zone_name'] = '{}-2'.format(region)

    if 'delete_on_dismantle' not in config_data[section]:
        config_data[section]['delete_on_dismantle'] = True

    if 'custom_lithops_image' not in config_data[section]:
        config_data[section]['custom_lithops_image'] = False
