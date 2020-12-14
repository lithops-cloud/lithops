#
# (C) Copyright IBM Corp. 2020
# (C) Copyright Cloudlab URV 2020
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
import requests
from concurrent.futures import ThreadPoolExecutor

from lithops import utils
from lithops.storage import Storage
from lithops.storage.utils import CloudObject, CloudObjectUrl

logger = logging.getLogger(__name__)

CHUNK_SIZE_MIN = 0*1024  # 0MB
CHUNK_THRESHOLD = 128*1024  # 128KB


def create_partitions(config, internal_storage, map_iterdata, chunk_size, chunk_number):
    """
    Method that returns the function that will create the partitions of the objects in the Cloud
    """
    logger.debug('Starting partitioner')

    parts_per_object = None

    sbs = set()
    buckets = set()
    prefixes = set()
    obj_names = set()
    urls = set()

    logger.debug("Parsing input data")
    for elem in map_iterdata:
        if 'url' in elem:
            urls.add(elem['url'])
        elif 'obj' in elem:
            if type(elem['obj']) == CloudObject:
                elem['obj'] = '{}://{}/{}'.format(elem['obj'].backend,
                                                  elem['obj'].bucket,
                                                  elem['obj'].key)
            sb, bucket, prefix, obj_name = utils.split_object_url(elem['obj'])
            if sb is None:
                sb = internal_storage.backend
                elem['obj'] = '{}://{}'.format(sb, elem['obj'])
            if obj_name:
                obj_names.add((bucket, prefix))
            elif prefix:
                prefixes.add((bucket, prefix))
            else:
                buckets.add(bucket)
            sbs.add(sb)

    if len(sbs) > 1:
        raise Exception('Currently we only support to process one storage backend at a time. '
                        'Current storage backends: {}'.format(sbs))

    if [prefixes, obj_names, urls, buckets].count(True) > 1:
        raise Exception('You must provide as an input data a list of bucktes, '
                        'a list of buckets with object prefix, a list of keys '
                        'or a list of urls. Intermingled types are not allowed.')

    if not urls:
        # process objects from an object store. No url
        sb = sbs.pop()
        if sb == internal_storage.backend:
            storage = internal_storage.storage
        else:
            storage = Storage(config=config, backend=sb)
        objects = {}
        if obj_names:
            for bucket, prefix in obj_names:
                logger.debug("Listing objects in '{}://{}/'"
                             .format(sb, '/'.join([bucket, prefix])))
                if bucket not in objects:
                    objects[bucket] = []
                prefix = prefix + '/' if prefix else prefix
                objects[bucket].extend(storage.list_objects(bucket, prefix))
        elif prefixes:
            for bucket, prefix in prefixes:
                logger.debug("Listing objects in '{}://{}/'"
                             .format(sb, '/'.join([bucket, prefix])))
                if bucket not in objects:
                    objects[bucket] = []
                prefix = prefix + '/' if prefix else prefix
                objects[bucket].extend(storage.list_objects(bucket, prefix))
        elif buckets:
            for bucket in buckets:
                logger.debug("Listing objects in '{}://{}'".format(sb, bucket))
                objects[bucket] = storage.list_objects(bucket)

        keys_dict = {}
        for bucket in objects:
            keys_dict[bucket] = {}
            for obj in objects[bucket]:
                keys_dict[bucket][obj['Key']] = obj['Size']

    if buckets or prefixes:
        partitions, parts_per_object = _split_objects_from_buckets(map_iterdata, keys_dict, chunk_size, chunk_number)

    elif obj_names:
        partitions, parts_per_object = _split_objects_from_keys(map_iterdata, keys_dict, chunk_size, chunk_number)

    elif urls:
        partitions, parts_per_object = _split_objects_from_urls(map_iterdata, chunk_size, chunk_number)

    else:
        raise ValueError('You did not provide any bucket or object key/url')

    return partitions, parts_per_object


def _split_objects_from_buckets(map_func_args_list, keys_dict, chunk_size, chunk_number):
    """
    Create partitions from bucket/s
    """
    logger.debug('Creating dataset chunks from bucket/s ...')
    partitions = []
    parts_per_object = []

    for entry in map_func_args_list:
        # Each entry is a bucket
        sb, bucket, prefix, obj_name = utils.split_object_url(entry['obj'])

        if chunk_size or chunk_number:
            logger.debug('Creating chunks from objects within: {}'.format(bucket))
        else:
            logger.debug('Discovering objects within: {}'.format(bucket))

        for key, obj_size in keys_dict[bucket].items():
            if prefix in key and obj_size > 0:
                logger.debug('Creating partitions from object {} size {}'.format(key, obj_size))

                if chunk_number:
                    chunk_rest = obj_size % chunk_number
                    obj_chunk_size = (obj_size // chunk_number) + \
                        round((chunk_rest / chunk_number) + 0.5)
                elif chunk_size:
                    obj_chunk_size = chunk_size
                else:
                    obj_chunk_size = obj_size

                size = total_partitions = 0

                while size < obj_size:
                    brange = (size, size+obj_chunk_size+CHUNK_THRESHOLD)
                    brange = None if obj_size == obj_chunk_size else brange

                    partition = entry.copy()
                    partition['obj'] = CloudObject(sb, bucket, key)
                    partition['obj'].data_byte_range = brange
                    partition['obj'].chunk_size = obj_chunk_size
                    partition['obj'].part = total_partitions
                    partitions.append(partition)

                    total_partitions += 1
                    size += obj_chunk_size

                parts_per_object.append(total_partitions)

    return partitions, parts_per_object


def _split_objects_from_keys(map_func_args_list, keys_dict, chunk_size, chunk_number):
    """
    Create partitions from a list of objects keys
    """
    if chunk_size or chunk_number:
        logger.debug('Creating chunks from object keys')

    partitions = []
    parts_per_object = []

    for entry in map_func_args_list:
        # each entry is a key
        sb, bucket, prefix, obj_name = utils.split_object_url(entry['obj'])
        key = '/'.join([prefix, obj_name]) if prefix else obj_name

        try:
            obj_size = keys_dict[bucket][key]
        except Exception:
            raise Exception('Object key "{}" does not exist in "{}" bucket'.format(key, bucket))

        if chunk_number:
            chunk_rest = obj_size % chunk_number
            obj_chunk_size = (obj_size // chunk_number) + \
                round((chunk_rest / chunk_number) + 0.5)
        elif chunk_size:
            obj_chunk_size = chunk_size
        else:
            obj_chunk_size = obj_size

        size = total_partitions = 0

        while size < obj_size:
            brange = (size, size+obj_chunk_size+CHUNK_THRESHOLD)
            brange = None if obj_size == obj_chunk_size else brange

            partition = entry.copy()
            partition['obj'] = CloudObject(sb, bucket, key)
            partition['obj'].data_byte_range = brange
            partition['obj'].chunk_size = obj_chunk_size
            partition['obj'].part = total_partitions
            partitions.append(partition)

            total_partitions += 1
            size += obj_chunk_size

        parts_per_object.append(total_partitions)

    return partitions, parts_per_object


def _split_objects_from_urls(map_func_args_list, chunk_size, chunk_number):
    """
    Create partitions from a list of objects urls
    """
    if chunk_size or chunk_number:
        logger.debug('Creating chunks from urls')
    partitions = []
    parts_per_object = []

    def _split(entry):
        obj_size = None
        object_url = entry['url']
        metadata = requests.head(object_url)

        logger.debug(object_url)

        if 'content-length' in metadata.headers:
            obj_size = int(metadata.headers['content-length'])

        if chunk_number and obj_size:
            chunk_rest = obj_size % chunk_number
            obj_chunk_size = (obj_size // chunk_number) + \
                round((chunk_rest / chunk_number) + 0.5)
        elif chunk_size and obj_size:
            obj_chunk_size = chunk_size
        elif obj_size:
            obj_chunk_size = obj_size
        else:
            obj_chunk_size = obj_size = 1

        if 'accept-ranges' not in metadata.headers:
            obj_chunk_size = obj_size

        size = total_partitions = 0

        while size < obj_size:
            brange = (size, size+obj_chunk_size+CHUNK_THRESHOLD)
            brange = None if obj_size == obj_chunk_size else brange

            partition = entry.copy()
            partition['url'] = CloudObjectUrl(object_url)
            partition['url'].data_byte_range = brange
            partition['url'].chunk_size = obj_chunk_size
            partition['url'].part = total_partitions
            partitions.append(partition)

            total_partitions += 1
            size += obj_chunk_size

        parts_per_object.append(total_partitions)

    with ThreadPoolExecutor(128) as ex:
        ex.map(_split, map_func_args_list)

    return partitions, parts_per_object
