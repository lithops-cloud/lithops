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
import shutil
import logging
import zipfile
from pywren_ibm_cloud import wrenconfig
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.compute import Compute
from pywren_ibm_cloud.utils import version_str

logger = logging.getLogger(__name__)

ZIP_LOCATION = os.path.join(os.getcwd(), 'ibmcf_pywren.zip')


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


def _extract_modules(docker_image_name, internal_compute):
    # Extract installed Python modules from docker image
    pywren_location = _get_pywren_location()
    action_location = os.path.join(pywren_location, "runtime", "extract_preinstalls_fn.py")

    with open(action_location, "r") as action_py:
        action_code = action_py.read()

    memory = 192

    # old_stdout = sys.stdout
    # sys.stdout = open(os.devnull, 'w')
    internal_compute.create_runtime(docker_image_name, memory, code=action_code, is_binary=False)
    # sys.stdout = old_stdout
    logger.debug("Extracting Python modules list from: {}".format(docker_image_name))
    try:
        runtime_meta = internal_compute.invoke_with_result(docker_image_name, memory)
    except Exception:
        raise("Unable to invoke 'modules' action")
    try:
        internal_compute.delete_runtime(docker_image_name, memory)
    except Exception:
        raise("Unable to delete 'modules' action")

    if 'preinstalls' not in runtime_meta:
        raise Exception(runtime_meta)

    return runtime_meta


def _create_blackbox_runtime(docker_image_name, memory, timeout, runtime_meta, internal_compute, internal_storage):
    # Create runtime_name from runtime_name docker image
    # Upload zipped PyWren action
    with open(ZIP_LOCATION, "rb") as action_zip:
        action_bin = action_zip.read()

    internal_compute.create_runtime(docker_image_name, memory, code=action_bin, timeout=timeout)

    if runtime_meta is not None:
        try:
            runtime_key = internal_compute.get_runtime_key(docker_image_name, memory)
            internal_storage.put_runtime_info(runtime_key, runtime_meta)
        except Exception:
            raise("Unable to upload 'preinstalled modules' file into {}".format(internal_storage.storage_backend))


def create_runtime(docker_image_name, memory=None, config=None):
    if docker_image_name == 'default':
        docker_image_name = _get_default_image_name()
    logger.info('Creating new PyWren runtime based on Docker image {}'.format(docker_image_name))

    config = wrenconfig.default(config)
    storage_config = wrenconfig.extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = wrenconfig.extract_compute_config(config)
    internal_compute = Compute(compute_config)

    _create_zip_action()

    runtime_meta = _extract_modules(docker_image_name, internal_compute)
    memory = config['pywren']['runtime_memory'] if not memory else memory
    timeout = config['pywren']['runtime_timeout']
    _create_blackbox_runtime(docker_image_name, memory, timeout, runtime_meta,
                             internal_compute, internal_storage)


def update_runtime(docker_image_name, config=None):
    if docker_image_name == 'default':
        docker_image_name = _get_default_image_name()

    logger.info('Updating runtime: {}'.format(docker_image_name))

    config = wrenconfig.default(config)
    storage_config = wrenconfig.extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = wrenconfig.extract_compute_config(config)
    internal_compute = Compute(compute_config)
    _create_zip_action()

    timeout = config['pywren']['runtime_timeout']

    if docker_image_name != 'all':
        runtime_meta = _extract_modules(docker_image_name, internal_compute)
    else:
        runtime_meta = None

    runtimes = internal_compute.list_runtimes(docker_image_name)

    for runtime in runtimes:
        _create_blackbox_runtime(runtime[0], runtime[1], timeout, runtime_meta,
                                 internal_compute, internal_storage)


def build_runtime(docker_image_name, config=None):
    logger.info('Creating a new docker image from Dockerfile')
    logger.info('Docker image name: {}'.format(docker_image_name))

    cmd = 'docker build -t {} .'.format(docker_image_name)
    res = os.system(cmd)
    if res != 0:
        exit()

    cmd = 'docker push {}'.format(docker_image_name)
    res = os.system(cmd)
    if res != 0:
        exit()

    create_runtime(docker_image_name, config=config)
    update_runtime(docker_image_name, config=config)


def delete_runtime(docker_image_name, config=None):
    if docker_image_name == 'default':
        docker_image_name = _get_default_image_name()
    logger.info('Deleting runtimes based on Docker image: {}'.format(docker_image_name))

    config = wrenconfig.default(config)
    storage_config = wrenconfig.extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = wrenconfig.extract_compute_config(config)
    internal_compute = Compute(compute_config)

    runtimes = internal_compute.list_runtimes(docker_image_name)
    for runtime in runtimes:
        internal_compute.delete_runtime(runtime[0], runtime[1])
        runtime_key = internal_compute.get_runtime_key(runtime[0], runtime[1])
        internal_storage.delete_runtime_info(runtime_key)


def clean_runtimes(config=None):
    logger.info('Cleaning all runtimes')
    config = wrenconfig.default(config)
    storage_config = wrenconfig.extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = wrenconfig.extract_compute_config(config)
    internal_compute = Compute(compute_config)

    # Clean local runtime_meta cache
    LOCAL_HOME_DIR = os.path.expanduser('~')
    cache_dir = os.path.join(LOCAL_HOME_DIR, '.pywren')
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)

    sh = internal_storage.storage_handler
    runtimes = sh.list_keys_with_prefix(storage_config['storage_bucket'], 'runtime')
    if runtimes:
        sh.delete_objects(storage_config['storage_bucket'], runtimes)

    internal_compute.delete_all_runtimes()
