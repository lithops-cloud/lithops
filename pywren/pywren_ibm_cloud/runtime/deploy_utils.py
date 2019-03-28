#
# (C) Copyright IBM Corp. 2018
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import sys
from shutil import copyfile
from pywren_ibm_cloud import wrenconfig
from pywren_ibm_cloud.storage import storage
from pywren_ibm_cloud.cf_connector import CloudFunctions
from pywren_ibm_cloud.wrenconfig import CF_ACTION_NAME_DEFAULT


ZIP_LOCATION = os.getcwd()+'/ibmcf_pywren.zip'


def _get_pywren_location():
    my_location = os.path.dirname(os.path.abspath(__file__))
    pw_location = os.path.join(my_location, '..')
    return pw_location


def _create_zip_action():
    pywren_location = _get_pywren_location()

    if not os.path.isfile(pywren_location + '/../__main__.py'):
        copyfile(pywren_location + '/action/__main__.py', pywren_location + '/../__main__.py')
    cmd = 'cd ' + pywren_location + '/..; zip -FSr ' + ZIP_LOCATION + ' __main__.py pywren_ibm_cloud/ -x "*__pycache__*"'
    try:
        res = os.system(cmd)
        if res != 0:
            exit()
    except Exception as e:
        print(e)


def _extract_modules(image_name, cf_client, config):
    # Extract installed Python modules from docker image
    # And store them into storage

    # Create runtime_name from image_name
    username, appname = image_name.split('/')
    runtime_name = appname.replace(':', '_')

    # Create storage_handler to upload modules file
    storage_config = wrenconfig.extract_storage_config(config)
    internal_storage = storage.InternalStorage(storage_config)

    pywren_location = _get_pywren_location()
    action_location = os.path.join(pywren_location, "runtime", "extract_modules.py")

    with open(action_location, "r") as action_py:
        action_code = action_py.read()
    action_name = runtime_name + '_modules'

    old_stdout = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    cf_client.create_action(action_name, code=action_code, kind='blackbox',
                            image=image_name, is_binary=False)
    sys.stdout = old_stdout

    runtime_meta = cf_client.invoke_with_result(action_name)
    internal_storage.put_runtime_info(runtime_name, runtime_meta)
    cf_client.delete_action(action_name)


def _create_blackbox_runtime(image_name, cf_client):
    # Create runtime_name from image_name
    username, appname = image_name.split('/')
    runtime_name = appname.replace(':', '_')

    # Upload zipped PyWren action
    with open(ZIP_LOCATION, "rb") as action_zip:
        action_bin = action_zip.read()
    cf_client.create_action(runtime_name, code=action_bin, kind='blackbox', image=image_name)


def create_runtime(image_name, config=None):
    print('Creating a new docker image from the Dockerfile')
    print('Docker image name: {}'.format(image_name))

    cmd = 'docker build -t {} .'.format(image_name)
    res = os.system(cmd)
    if res != 0:
        exit()

    cmd = 'docker push {}'.format(image_name)
    res = os.system(cmd)
    if res != 0:
        exit()

    if config is None:
        config = wrenconfig.default()
    else:
        config = wrenconfig.default(config)

    cf_client = CloudFunctions(config['ibm_cf'])
    _create_zip_action()
    _extract_modules(image_name, cf_client, config)
    _create_blackbox_runtime(image_name, cf_client)

    print('All done!')


def clone_runtime(image_name, config=None):
    print('Cloning docker image {}'.format(image_name))

    if config is None:
        config = wrenconfig.default()
    else:
        config = wrenconfig.default(config)

    cf_client = CloudFunctions(config['ibm_cf'])
    _create_zip_action()
    _extract_modules(image_name, cf_client, config)
    _create_blackbox_runtime(image_name, cf_client)

    print('All done!')


def update_runtime(image_name, config=None):
    print('Updating runtime {}'.format(image_name))
    if config is None:
        config = wrenconfig.default()
    else:
        config = wrenconfig.default(config)
    cf_client = CloudFunctions(config['ibm_cf'])
    _create_zip_action()
    _create_blackbox_runtime(image_name, cf_client)

    print('All done!')


def deploy_default_rutime(config=None):
    print('Updating runtime {}'.format(CF_ACTION_NAME_DEFAULT))
    if config is None:
        config = wrenconfig.default()
    else:
        config = wrenconfig.default(config)

    # Create zipped PyWren action
    _create_zip_action()

    with open(ZIP_LOCATION, "rb") as action_zip:
        action_bin = action_zip.read()
        cf_client = CloudFunctions(config['ibm_cf'])
        runtime_name = CF_ACTION_NAME_DEFAULT
        cf_client.create_action(runtime_name, code=action_bin)
