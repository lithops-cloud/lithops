import os
import sys


def get_config_file(backends_name):
    """returns the lithops config file the contains given backends"""

    path = 'lithops/tests/config_files/'
    for file in os.listdir(path):
        if file.endswith('yaml') and backends_name in file:
            return path + file


if __name__ == '__main__':
    secrets_to_fill = ['<git-actor>','<iamapikey>', '<cos_api_key>', '<cf_api_key>']
    config_file = get_config_file(sys.argv[1])
    args = sys.argv[2:]

    with open(config_file, 'r') as file:
        filedata = file.read()

    for i, arg in enumerate(args):
        filedata = filedata.replace(secrets_to_fill[i], arg)

    with open(config_file, 'w') as file:
        file.write(filedata)

