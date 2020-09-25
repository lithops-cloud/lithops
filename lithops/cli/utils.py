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
from lithops.config import CACHE_DIR, STORAGE_FOLDER, \
    default_config, extract_storage_config, extract_compute_config, \
    RUNTIMES_PREFIX, JOBS_PREFIX, DOCKER_FOLDER
from lithops.storage import InternalStorage
from lithops.compute import Compute
from lithops.storage.utils import clean_bucket

logger = logging.getLogger(__name__)


def clean_all(config=None):
    logger.info('Cleaning all Lithops information')
    config = default_config(config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_compute_config(config)
    compute_handler = Compute(compute_config, storage_config)

    # Clean localhost executor temp dirs
    shutil.rmtree(STORAGE_FOLDER, ignore_errors=True)
    shutil.rmtree(DOCKER_FOLDER, ignore_errors=True)

    # Clean object storage temp dirs
    compute_handler.delete_all_runtimes()
    storage = internal_storage.storage
    clean_bucket(storage, storage_config['bucket'], RUNTIMES_PREFIX, sleep=1)
    clean_bucket(storage, storage_config['bucket'], JOBS_PREFIX, sleep=1)

    # Clean local lithops cache
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
