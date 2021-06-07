import sys


if __name__ == '__main__':
    iamapikey, cos_api_key = sys.argv[1:]
    config_file = 'lithops/tests/lithops_config.yaml'

    with open(config_file, 'r') as file:
        filedata = file.read()

    filedata = filedata.replace('<iamapikey>', iamapikey).replace('<cos_api_key>', cos_api_key)

    with open(config_file, 'w') as file:
        file.write(filedata)

