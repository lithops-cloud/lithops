import sys

if __name__ == '__main__':
    iamapikey, cos_api_key = sys.argv[1:]
    # print(iamapikey[2:8])
    # print(cos_api_key[2:8])

    with open('lithops/scripts/config_fill_secrets.py', 'r') as file:
        filedata = file.read()

    # Replace the target string
    filedata = filedata.replace('<iamapikey>', iamapikey)
    filedata = filedata.replace('<cos_api_key>', cos_api_key)

    with open('lithops/scripts/config_fill_secrets.py', 'w') as file:
        file.write(filedata)
        print(filedata)



# import argparse
#
# if __name__ == '__main__':
#     parser = argparse.ArgumentParser(description="Append secrets to lithops config file",
#                                      usage='python -m lithops.scripts.config_fill_secrets [-c CONFIG] [-t TESTNAME] ...')
#     parser.add_argument('-c', '--config', metavar='', default=None,
#                         help="'path to yaml config file")
#
#     args = parser.parse_args()
#
#     with open('lithops/scripts/config_fill_secrets.py', 'r') as file:
#         filedata = file.read()
#
#     # Replace the target string
#     filedata = filedata.replace('<iamapikey>', 'abcd')
#
#     # Write the file out again
#     with open('file.txt', 'w') as file:
#         file.write(filedata)
