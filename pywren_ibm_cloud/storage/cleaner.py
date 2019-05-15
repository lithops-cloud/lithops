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

import logging
import sys
import os
import json
from . import storage

logger = logging.getLogger(__name__)


def clean_bucket(bucket, prefix, storage_config):
    """
    Wrapper of clean_os_bucket(). Use this method only when storage_config is
    in JSON format. In any other case, call directly clean_os_bucket() method.
    """
    internal_storage = storage.InternalStorage(json.loads(storage_config))
    # sys.stdout = open(os.devnull, 'w')
    clean_os_bucket(bucket, prefix, internal_storage)
    # sys.stdout = sys.__stdout__


def clean_os_bucket(bucket, prefix, internal_storage):
    """
    Deletes all the files from COS. These files include the function,
    the data serialization and the function invocation results.
    """
    msg = "Going to delete all objects from bucket '{}' and prefix '{}'".format(bucket, prefix)
    logger.debug(msg)
    total_objects = 0
    objects_to_delete = internal_storage.list_temporal_data(prefix)

    while objects_to_delete:
        logger.debug('{} objects found'.format(len(objects_to_delete)))
        total_objects = total_objects + len(objects_to_delete)
        internal_storage.delete_temporal_data(objects_to_delete)
        objects_to_delete = internal_storage.list_temporal_data(prefix)
    logger.info('Finished deleting objects, total found: {}'.format(total_objects))
