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
from pywren_ibm_cloud.utils import version_str, create_action_name, create_runtime_name
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


def _extract_modules(image_name, memory, cf_client, config):
    # Extract installed Python modules from docker image
    # And store them into storage
    # Create storage_handler to upload modules file
    storage_config = wrenconfig.extract_storage_config(config)
    internal_storage = storage.InternalStorage(storage_config)

    pywren_location = _get_pywren_location()
    action_location = os.path.join(pywren_location, "runtime", "extract_modules.py")

    with open(action_location, "r") as action_py:
        action_code = action_py.read()

    modules_action_name = '{}-modules'.format(create_action_name(image_name))

    # old_stdout = sys.stdout
    # sys.stdout = open(os.devnull, 'w')
    logger.debug("Creating action for extracting Python modules list: {}".format(modules_action_name))
    cf_client.create_action(modules_action_name, image_name, code=action_code, is_binary=False)
    # sys.stdout = old_stdout

    region = cf_client.endpoint.split('//')[1].split('.')[0]
    namespace = cf_client.namespace
    memory = cf_client.default_runtime_memory if not memory else memory
    runtime_name = create_runtime_name(image_name, memory)
    logger.debug("Going to extract Python modules list from: {}".format(image_name))
    runtime_meta = cf_client.invoke_with_result(modules_action_name)
    internal_storage.put_runtime_info(region, namespace, runtime_name, runtime_meta)
    cf_client.delete_action(modules_action_name)


def _create_blackbox_runtime(image_name, memory, cf_client):
    # Create runtime_name from image_name
    memory = cf_client.default_runtime_memory if not memory else memory
    runtime_name = create_runtime_name(image_name, memory)
    action_name = create_action_name(runtime_name)

    # Upload zipped PyWren action
    with open(ZIP_LOCATION, "rb") as action_zip:
        action_bin = action_zip.read()
    logger.debug("Creating blackbox action: {}".format(action_name))
    cf_client.create_action(action_name, image_name, code=action_bin, memory=memory)


def create_runtime(image_name, memory=None, config=None):
    logger.info('Creating new PyWren runtime based on image {}'.format(image_name))

    if config is None:
        config = wrenconfig.default()
    else:
        config = wrenconfig.default(config)

    cf_config = wrenconfig.extract_cf_config(config)
    cf_client = CloudFunctions(cf_config)
    cf_client.create_package(PACKAGE)
    _create_zip_action()

    if image_name == 'default':
        image_name = _get_default_image_name()

    if not memory:
        # if not memory, this means that the method was called from deploy_runtime script
        for memory in [wrenconfig.RUNTIME_MEMORY_DEFAULT, wrenconfig.RUNTIME_RI_MEMORY_DEFAULT]:
            _extract_modules(image_name,  memory, cf_client, config)
            _create_blackbox_runtime(image_name, memory, cf_client)
    else:
        ri_runtime_deployed = False
        image_name_formated = create_action_name(image_name)
        actions = cf_client.list_actions(PACKAGE)
        for action in actions:
            action_name, r_memory = action['name'].rsplit('-', 1)
            if image_name_formated == action_name:
                r_memory = int(r_memory.replace('MB', ''))
                if r_memory == wrenconfig.RUNTIME_RI_MEMORY_DEFAULT:
                    ri_runtime_deployed = True
                    break
        if not ri_runtime_deployed:
            _extract_modules(image_name,  wrenconfig.RUNTIME_RI_MEMORY_DEFAULT, cf_client, config)
            _create_blackbox_runtime(image_name, wrenconfig.RUNTIME_RI_MEMORY_DEFAULT, cf_client)
        _extract_modules(image_name,  memory, cf_client, config)
        _create_blackbox_runtime(image_name, memory, cf_client)


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
    logger.info('Updating runtime: {}'.format(image_name))
    if config is None:
        config = wrenconfig.default()
    else:
        config = wrenconfig.default(config)

    cf_config = wrenconfig.extract_cf_config(config)
    cf_client = CloudFunctions(cf_config)
    cf_client.create_package(PACKAGE)
    _create_zip_action()

    if image_name == 'default':
        image_name = _get_default_image_name()

    image_name_formated = create_action_name(image_name)
    actions = cf_client.list_actions(PACKAGE)

    for action in actions:
        action_name, memory = action['name'].rsplit('-', 1)
        if image_name_formated == action_name:
            memory = int(memory.replace('MB', ''))
            _extract_modules(image_name, memory, cf_client, config)
            _create_blackbox_runtime(image_name, memory, cf_client)


def delete_runtime(image_name, config=None):
    logger.info('Deleting runtime: {}'.format(image_name))

    if config is None:
        config = wrenconfig.default()
    else:
        config = wrenconfig.default(config)

    storage_config = wrenconfig.extract_storage_config(config)
    storage_client = storage.InternalStorage(storage_config)
    cf_config = wrenconfig.extract_cf_config(config)
    cf_client = CloudFunctions(cf_config)

    if image_name == 'default':
        image_name = _get_default_image_name()

    image_name_formated = create_action_name(image_name)
    actions = cf_client.list_actions(PACKAGE)
    region = cf_client.endpoint.split('//')[1].split('.')[0]
    namespace = cf_client.namespace

    for action in actions:
        action_name, memory = action['name'].rsplit('-', 1)
        if image_name_formated == action_name:
            memory = int(memory.replace('MB', ''))
            runtime_name = create_runtime_name(image_name, memory)
            storage_client.delete_runtime_info(region, namespace, runtime_name)
            action_name = create_action_name(runtime_name)
            cf_client.delete_action(action_name)
