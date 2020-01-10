#
# (C) Copyright IBM Corp. 2019
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
import shutil
import tempfile
import logging
from pywren_ibm_cloud.config import CACHE_DIR, RUNTIMES_PREFIX, \
    JOBS_PREFIX, default_config, extract_storage_config, extract_compute_config
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.compute import Compute
from pywren_ibm_cloud.storage.utils import clean_os_bucket

TEMP = tempfile.gettempdir()
logger = logging.getLogger(__name__)


def create_runtime(name, memory=None, config=None):
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_compute_config(config)
    compute_handler = Compute(compute_config)

    memory = config['pywren']['runtime_memory'] if not memory else memory
    timeout = config['pywren']['runtime_timeout']

    logger.info('Creating runtime: {}, memory: {}'.format(name, memory))

    runtime_key = compute_handler.get_runtime_key(name, memory)
    runtime_meta = compute_handler.create_runtime(name, memory, timeout=timeout)

    try:
        internal_storage.put_runtime_meta(runtime_key, runtime_meta)
    except Exception:
        raise("Unable to upload 'preinstalled-modules' file into {}".format(internal_storage.backend))


def update_runtime(name, config=None):
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_compute_config(config)
    compute_handler = Compute(compute_config)

    timeout = config['pywren']['runtime_timeout']
    logger.info('Updating runtime: {}'.format(name))

    runtimes = compute_handler.list_runtimes(name)

    for runtime in runtimes:
        runtime_key = compute_handler.get_runtime_key(runtime[0], runtime[1])
        runtime_meta = compute_handler.create_runtime(runtime[0], runtime[1], timeout)

        try:
            internal_storage.put_runtime_meta(runtime_key, runtime_meta)
        except Exception:
            raise("Unable to upload 'preinstalled-modules' file into {}".format(internal_storage.backend))


def build_runtime(name, file, config=None):
    config = default_config(config)
    compute_config = extract_compute_config(config)
    compute_handler = Compute(compute_config)
    compute_handler.build_runtime(name, file)

    create_runtime(name, config=config)
    update_runtime(name, config=config)


def delete_runtime(name, config=None):
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_compute_config(config)
    compute_handler = Compute(compute_config)

    runtimes = compute_handler.list_runtimes(name)
    for runtime in runtimes:
        compute_handler.delete_runtime(runtime[0], runtime[1])
        runtime_key = compute_handler.get_runtime_key(runtime[0], runtime[1])
        internal_storage.delete_runtime_meta(runtime_key)


def clean_all(config=None):
    logger.info('Cleaning all PyWren information')
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_compute_config(config)
    compute_handler = Compute(compute_config)

    # Clean object storage temp dirs
    sh = internal_storage.storage_handler
    runtimes = sh.list_keys(storage_config['bucket'], RUNTIMES_PREFIX)
    if runtimes:
        sh.delete_objects(storage_config['bucket'], runtimes)
    compute_handler.delete_all_runtimes()
    clean_os_bucket(storage_config['bucket'], JOBS_PREFIX, internal_storage, sleep=1)

    # Clean local runtime_meta cache
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)

    # Clean localhost temp dirs
    localhost_jobs_path = os.path.join(TEMP, JOBS_PREFIX)
    if os.path.exists(localhost_jobs_path):
        shutil.rmtree(localhost_jobs_path)
    localhost_runtimes_path = os.path.join(TEMP, RUNTIMES_PREFIX)
    if os.path.exists(localhost_runtimes_path):
        shutil.rmtree(localhost_runtimes_path)
