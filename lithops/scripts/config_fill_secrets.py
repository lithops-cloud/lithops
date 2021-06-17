import os

import sys


def get_config_files():
    path = 'lithops/tests/config_files'
    for file in os.listdir(path):
        if file.endswith('yaml'):
            yield file


if __name__ == '__main__':
    iamapikey, cos_api_key, cf_api_key = sys.argv[1:]

    for config_file in get_config_files():

        with open(config_file, 'r') as file:
            filedata = file.read()

        filedata = filedata.replace('<iamapikey>', iamapikey).replace('<cos_api_key>', cos_api_key).\
            replace('<cf_api_key>', cf_api_key)

        with open(config_file, 'w') as file:
            file.write(filedata)

