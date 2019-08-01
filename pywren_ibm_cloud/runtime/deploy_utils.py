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
import shutil
import logging
from pywren_ibm_cloud.config import default_config, extract_storage_config, extract_compute_config
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.compute import Compute


logger = logging.getLogger(__name__)


def create_runtime(name, memory=None, config=None):
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_compute_config(config)
    internal_compute = Compute(compute_config)

    memory = config['pywren']['runtime_memory'] if not memory else memory
    timeout = config['pywren']['runtime_timeout']
    logger.info('Creating runtime: {}, memory: {}'.format(name, memory))

    runtime_meta = internal_compute.generate_runtime_meta(name)
    internal_compute.create_runtime(name, memory, timeout=timeout)

    try:
        runtime_key = internal_compute.get_runtime_key(name, memory)
        internal_storage.put_runtime_meta(runtime_key, runtime_meta)
    except Exception:
        raise("Unable to upload 'preinstalled modules' file into {}".format(internal_storage.backend))


def update_runtime(name, config=None):
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_compute_config(config)
    internal_compute = Compute(compute_config)

    timeout = config['pywren']['runtime_timeout']
    logger.info('Updating runtime: {}'.format(name))

    if name != 'all':
        runtime_meta = internal_compute.generate_runtime_meta(name)
    else:
        runtime_meta = None

    runtimes = internal_compute.list_runtimes(name)

    for runtime in runtimes:
        internal_compute.create_runtime(runtime[0], runtime[1], timeout)
        if runtime_meta:
            try:
                runtime_key = internal_compute.get_runtime_key(runtime[0], runtime[1])
                internal_storage.put_runtime_meta(runtime_key, runtime_meta)
            except Exception:
                raise("Unable to upload 'preinstalled modules' file into {}".format(internal_storage.backend))


def build_runtime(name, file, config=None):
    config = default_config(config)
    compute_config = extract_compute_config(config)
    internal_compute = Compute(compute_config)
    internal_compute.build_runtime(name, file)

    create_runtime(name, config=config)
    update_runtime(name, config=config)


def delete_runtime(name, config=None):
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_compute_config(config)
    internal_compute = Compute(compute_config)

    runtimes = internal_compute.list_runtimes(name)
    for runtime in runtimes:
        internal_compute.delete_runtime(runtime[0], runtime[1])
        runtime_key = internal_compute.get_runtime_key(runtime[0], runtime[1])
        internal_storage.delete_runtime_meta(runtime_key)


def clean_runtimes(config=None):
    logger.info('Cleaning all runtimes')
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_compute_config(config)
    internal_compute = Compute(compute_config)

    # Clean local runtime_meta cache
    cache_dir = os.path.join(os.path.expanduser('~'), '.cloudbutton')
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)

    sh = internal_storage.storage_handler
    runtimes = sh.list_keys_with_prefix(storage_config['bucket'], 'runtime')
    if runtimes:
        sh.delete_objects(storage_config['bucket'], runtimes)

    internal_compute.delete_all_runtimes()
