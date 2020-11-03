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

import shutil
import logging
from lithops.config import CACHE_DIR, STORAGE_DIR, \
    default_config, extract_storage_config, extract_serverless_config, \
    RUNTIMES_PREFIX, JOBS_PREFIX, extract_standalone_config,\
    extract_localhost_config, LOCALHOST, SERVERLESS, STANDALONE
from lithops.storage import InternalStorage
from lithops.serverless import ServerlessHandler
from lithops.storage.utils import clean_bucket
from lithops.standalone.standalone import StandaloneHandler
from lithops.localhost.localhost import LocalhostHandler

logger = logging.getLogger(__name__)


def clean_all(config=None):
    logger.info('Cleaning all Lithops information')
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)

    mode = config['lithops']['mode']
    if mode == LOCALHOST:
        compute_config = extract_localhost_config(config)
        compute_handler = LocalhostHandler(compute_config)
    elif mode == SERVERLESS:
        compute_config = extract_serverless_config(config)
        compute_handler = ServerlessHandler(compute_config, storage_config)
    elif mode == STANDALONE:
        compute_config = extract_standalone_config(config)
        compute_handler = StandaloneHandler(compute_config)

    compute_handler.clean()

    # Clean object storage temp dirs
    storage = internal_storage.storage
    clean_bucket(storage, storage_config['bucket'], RUNTIMES_PREFIX, sleep=1)
    clean_bucket(storage, storage_config['bucket'], JOBS_PREFIX, sleep=1)

    # Clean localhost executor temp dirs
    shutil.rmtree(STORAGE_DIR, ignore_errors=True)
    # Clean local lithops cache
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
