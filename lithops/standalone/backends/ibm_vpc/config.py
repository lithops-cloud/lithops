import datetime


MANDATORY_PARAMETERS_1 = ['endpoint',
                          'vpc_name',
                          'resource_group_id',
                          'key_id']

MANDATORY_PARAMETERS_2 = ['endpoint',
                          'vpc_id',
                          'resource_group_id',
                          'key_id',
                          'subnet_id',
                          'security_group_id']


MANDATORY_PARAMETERS_3 = ['endpoint',
                          'instance_id',
                          'ip_address']


IMAGE_ID_DEFAULT = 'r014-b7da49af-b46a-4099-99a4-c183d2d40ea8'  # ubuntu 20.04
PROFILE_NAME_DEFAULT = 'cx2-2x4'
VOLUME_TIER_NAME_DEFAULT = 'general-purpose'

SSH_USER = 'root'
SSH_PASSWD = 'lithops'

CLOUD_CONFIG = """
#cloud-config
bootcmd:
    - echo '{0}:{1}' | chpasswd
    - sed -i '/PasswordAuthentication no/c\PasswordAuthentication yes' /etc/ssh/sshd_config
    - echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
runcmd:
    - echo '{0}:{1}' | chpasswd
    - sed -i '/PasswordAuthentication no/c\PasswordAuthentication yes' /etc/ssh/sshd_config
    - echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
    - systemctl restart sshd
""".format(SSH_USER, SSH_PASSWD)


def load_config(config_data):
    section = 'ibm_vpc'

    if 'ibm' in config_data and config_data['ibm'] is not None:
        config_data[section].update(config_data['ibm'])
    else:
        msg = 'IBM IAM api key is mandatory in ibm section of the configuration'
        raise Exception(msg)

    if 'exec_mode' in config_data['standalone'] \
       and config_data['standalone']['exec_mode'] == 'create':
        params_to_check = MANDATORY_PARAMETERS_2
    else:
        params_to_check = MANDATORY_PARAMETERS_3

    for param in params_to_check:
        if param not in config_data[section]:
            msg = '{} is mandatory in {} section of the configuration'.format(param, section)
            raise Exception(msg)

    if 'version' not in config_data:
        # it is not safe to use version as today() due to timezone differences. may fail at midnight. better use yesterday
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        config_data[section]['version'] = yesterday.strftime('%Y-%m-%d')

    if 'ssh_user' not in config_data[section]:
        config_data[section]['ssh_user'] = SSH_USER

    if 'volume_tier_name' not in config_data[section]:
        config_data[section]['volume_tier_name'] = VOLUME_TIER_NAME_DEFAULT

    if 'profile_name' not in config_data[section]:
        config_data[section]['profile_name'] = PROFILE_NAME_DEFAULT

    if 'master_profile_name' not in config_data[section]:
        config_data[section]['master_profile_name'] = PROFILE_NAME_DEFAULT

    if 'image_id' not in config_data[section]:
        config_data[section]['image_id'] = IMAGE_ID_DEFAULT

    region = config_data[section]['endpoint'].split('//')[1].split('.')[0]
    if 'zone_name' not in config_data[section]:
        config_data[section]['zone_name'] = '{}-2'.format(region)

    if 'delete_on_dismantle' not in config_data[section]:
        config_data[section]['delete_on_dismantle'] = True
