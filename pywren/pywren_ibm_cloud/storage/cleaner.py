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

from pywren_ibm_cloud.storage import storage
import logging
import sys
import os

logger = logging.getLogger(__name__)

def clean_bucket(bucket, prefix, storage_config):
    storage_handler = storage.Storage(storage_config)
    sys.stdout = open(os.devnull, 'w')
    clean_os_bucket(bucket, prefix, storage_handler)
    sys.stdout = sys.__stdout__

def clean_os_bucket(bucket, prefix, storage_handler):
    logger.info("Going to delete all objects from bucket '{}' and prefix '{}'".format(bucket, prefix))
    total_objects = 0
    objects_to_delete = storage_handler.list_objects(bucket, prefix)
    
    while objects_to_delete:
        if 'Key' in objects_to_delete[0]:
            # S3 API
            delete_keys = [obj['Key'] for obj in objects_to_delete]
        elif 'name' in objects_to_delete[0]:
            # Swift API
            delete_keys = [obj['name'] for obj in objects_to_delete]
        logger.debug('{} objects found'.format(len(delete_keys)))
        total_objects = total_objects + len(delete_keys)
        storage_handler.delete_objects(bucket, delete_keys)
        objects_to_delete = storage_handler.list_objects(bucket, prefix)
    logger.info('Finished deleting objects, total found: {}'.format(total_objects))
