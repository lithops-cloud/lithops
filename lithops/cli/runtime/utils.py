#
# (C) Copyright IBM Corp. 2020
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

import logging
from lithops.storage import InternalStorage
from lithops.serverless import ServerlessHandler
from lithops.config import default_config, extract_storage_config, extract_serverless_config


logger = logging.getLogger(__name__)


def create_runtime(name, memory=None, config=None):
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, storage_config)

    memory = config['lithops']['runtime_memory'] if not memory else memory
    timeout = config['lithops']['runtime_timeout']

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
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, storage_config)

    timeout = config['lithops']['runtime_timeout']
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
    storage_config = extract_storage_config(config)
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, storage_config)
    compute_handler.build_runtime(name, file)


def delete_runtime(name, config=None):
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, storage_config)

    runtimes = compute_handler.list_runtimes(name)
    for runtime in runtimes:
        compute_handler.delete_runtime(runtime[0], runtime[1])
        runtime_key = compute_handler.get_runtime_key(runtime[0], runtime[1])
        internal_storage.delete_runtime_meta(runtime_key)
