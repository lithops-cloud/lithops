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
import logging
import zipfile
from pywren_ibm_cloud import wrenconfig
from pywren_ibm_cloud.version import __version__
from pywren_ibm_cloud.utils import version_str, format_action_name, unformat_action_name
from pywren_ibm_cloud.storage import storage
from pywren_ibm_cloud.libs.ibm_cf.cf_connector import CloudFunctions

logger = logging.getLogger(__name__)

ZIP_LOCATION = os.path.join(os.getcwd(), 'ibmcf_pywren.zip')
PACKAGE = 'pywren_v'+__version__


def _get_default_image_name():
    this_version_str = version_str(sys.version_info)
    if this_version_str == '3.5':
        image_name = wrenconfig.RUNTIME_DEFAULT_35
    elif this_version_str == '3.6':
        image_name = wrenconfig.RUNTIME_DEFAULT_36
    elif this_version_str == '3.7':
        image_name = wrenconfig.RUNTIME_DEFAULT_37
    return image_name


def _get_pywren_location():
    my_location = os.path.dirname(os.path.abspath(__file__))
    pw_location = os.path.join(my_location, '..')
    return pw_location


def _create_zip_action():
    logger.debug("Creating zip action in {}".format(ZIP_LOCATION))

    def add_folder_to_zip(zip_file, full_dir_path, sub_dir=''):
        for file in os.listdir(full_dir_path):
            full_path = os.path.join(full_dir_path, file)
            if os.path.isfile(full_path):
                zip_file.write(full_path, os.path.join('pywren_ibm_cloud', sub_dir, file), zipfile.ZIP_DEFLATED)
            elif os.path.isdir(full_path) and '__pycache__' not in full_path:
                add_folder_to_zip(zip_file, full_path, os.path.join(sub_dir, file))

    try:
        pywren_location = _get_pywren_location()

        with zipfile.ZipFile(ZIP_LOCATION, 'w') as ibmcf_pywren_zip:
            main_file = os.path.join(pywren_location, 'action', '__main__.py')
            ibmcf_pywren_zip.write(main_file, '__main__.py', zipfile.ZIP_DEFLATED)
            add_folder_to_zip(ibmcf_pywren_zip, pywren_location)
    except Exception:
        raise Exception('Unable to create the {} action package'.format(ZIP_LOCATION))


def _extract_modules(image_name, cf_client):
    # Extract installed Python modules from docker image
    pywren_location = _get_pywren_location()
    action_location = os.path.join(pywren_location, "runtime", "extract_modules.py")

    with open(action_location, "r") as action_py:
        action_code = action_py.read()

    modules_action_name = format_action_name(image_name, 'modules').replace('MB', '')

    # old_stdout = sys.stdout
    # sys.stdout = open(os.devnull, 'w')
    cf_client.create_action(PACKAGE, modules_action_name, image_name,
                            code=action_code, is_binary=False)
    # sys.stdout = old_stdout
    logger.debug("Extracting Python modules list from: {}".format(image_name))
    try:
        runtime_meta = cf_client.invoke_with_result(modules_action_name)
    except Exception:
        raise("Unable to invoke 'modules' action")
    try:
        cf_client.delete_action(PACKAGE, modules_action_name)
    except Exception:
        raise("Unable to delete 'modules' action")

    if 'preinstalls' not in runtime_meta:
        raise Exception(runtime_meta)

    return runtime_meta


def _create_blackbox_runtime(image_name, memory, runtime_meta, cf_client, internal_storage):
    # Create runtime_name from image_name
    action_name = format_action_name(image_name, memory)

    # Upload zipped PyWren action
    with open(ZIP_LOCATION, "rb") as action_zip:
        action_bin = action_zip.read()

    cf_client.create_action(PACKAGE, action_name, image_name, code=action_bin, memory=memory)

    if runtime_meta:
        region = cf_client.endpoint.split('//')[1].split('.')[0]
        namespace = cf_client.namespace
        try:
            internal_storage.put_runtime_info(region, namespace, action_name, runtime_meta)
        except Exception:
            raise("Unable to upload 'pre-installed modules' file to COS")


def create_runtime(image_name, memory=None, config=None):
    if image_name == 'default':
        image_name = _get_default_image_name()
    logger.info('Creating new PyWren runtime based on image {}'.format(image_name))
    config = wrenconfig.default(config)
    storage_config = wrenconfig.extract_storage_config(config)
    internal_storage = storage.InternalStorage(storage_config)

    cf_config = wrenconfig.extract_cf_config(config)
    cf_client = CloudFunctions(cf_config)
    cf_client.create_package(PACKAGE)
    _create_zip_action()

    runtime_meta = _extract_modules(image_name, cf_client)
    memory = wrenconfig.RUNTIME_MEMORY_DEFAULT if not memory else memory
    _create_blackbox_runtime(image_name, memory, runtime_meta,
                             cf_client, internal_storage)


def build_runtime(image_name, config=None):
    logger.info('Creating a new docker image from the Dockerfile')
    logger.info('Docker image name: {}'.format(image_name))

    cmd = 'docker build -t {} .'.format(image_name)
    res = os.system(cmd)
    if res != 0:
        exit()

    cmd = 'docker push {}'.format(image_name)
    res = os.system(cmd)
    if res != 0:
        exit()

    create_runtime(image_name, config=config)
    update_runtime(image_name, config=config)


def update_runtime(image_name, config=None):
    if image_name == 'default':
        image_name = _get_default_image_name()

    logger.info('Updating runtime: {}'.format(image_name))

    config = wrenconfig.default(config)
    storage_config = wrenconfig.extract_storage_config(config)
    internal_storage = storage.InternalStorage(storage_config)
    cf_config = wrenconfig.extract_cf_config(config)
    cf_client = CloudFunctions(cf_config)
    cf_client.create_package(PACKAGE)
    _create_zip_action()

    if image_name != 'all':
        runtime_meta = _extract_modules(image_name, cf_client)
    else:
        runtime_meta = None

    actions = cf_client.list_actions(PACKAGE)

    for action in actions:
        if 'modules' in action['name']:
            cf_client.delete_action(PACKAGE, action['name'])
            continue
        action_image_name, memory = unformat_action_name(action['name'])
        if image_name == action_image_name or image_name == 'all':
            _create_blackbox_runtime(action_image_name, memory, runtime_meta,
                                     cf_client, internal_storage)


def delete_runtime(image_name, config=None):
    if image_name == 'default':
        image_name = _get_default_image_name()
    logger.info('Deleting runtime: {}'.format(image_name))

    config = wrenconfig.default(config)
    storage_config = wrenconfig.extract_storage_config(config)
    storage_client = storage.InternalStorage(storage_config)
    cf_config = wrenconfig.extract_cf_config(config)
    cf_client = CloudFunctions(cf_config)

    actions = cf_client.list_actions(PACKAGE)
    region = cf_client.endpoint.split('//')[1].split('.')[0]
    namespace = cf_client.namespace

    for action in actions:
        action_image_name, memory = unformat_action_name(action['name'])
        if image_name == action_image_name or image_name == 'all':
            storage_client.delete_runtime_info(region, namespace, action['name'])
            cf_client.delete_action(PACKAGE, action['name'])


def clean_runtimes(config=None):
    logger.info('Cleaning runtimes')
    config = wrenconfig.default(config)
    storage_config = wrenconfig.extract_storage_config(config)
    storage_client = storage.InternalStorage(storage_config)
    cf_config = wrenconfig.extract_cf_config(config)
    cf_client = CloudFunctions(cf_config)

    bh = storage_client.backend_handler
    runtimes = bh.list_keys_with_prefix(storage_config['storage_bucket'], 'runtime')
    if runtimes:
        bh.delete_objects(storage_config['storage_bucket'], runtimes)

    packages = cf_client.list_packages()
    for pkg in packages:
        if 'pywren_v' in pkg['name']:
            actions = cf_client.list_actions(pkg['name'])
            while actions:
                for action in actions:
                    cf_client.delete_action(pkg['name'], action['name'])
                actions = cf_client.list_actions(pkg['name'])
            cf_client.delete_package(pkg['name'])
