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

import os
import logging
import requests
from concurrent.futures import ThreadPoolExecutor

from lithops import utils
from lithops.storage import Storage
from lithops.storage.utils import CloudObject, CloudObjectUrl, CloudObjectLocal
from lithops.utils import sizeof_fmt

logger = logging.getLogger(__name__)

CHUNK_SIZE_MIN = 0*1024  # 0MB
CHUNK_THRESHOLD = 128*1024  # 128KB


def create_partitions(config, internal_storage, map_iterdata, obj_chunk_size, obj_chunk_number):
    """
    Method that returns the function that will create the partitions of the objects in the Cloud
    """
    ppo = None  # parts per object

    sbs = set()
    buckets = set()
    prefixes = set()
    obj_names = set()
    urls = set()
    paths = set()

    logger.debug("Parsing input data")

    for elem in map_iterdata:
        if elem['obj'].startswith('http'):
            urls.add(elem['obj'])

        elif elem['obj'].startswith('/'):
            paths.add(elem['obj'])

        else:
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

    if urls:
        # process objects from urls.
        partitions, ppo = _split_objects_from_urls(
                                map_iterdata,
                                obj_chunk_size,
                                obj_chunk_number)

    elif paths:
        # process objects from localhost paths.
        partitions, ppo = _split_objects_from_paths(
                                map_iterdata,
                                obj_chunk_size,
                                obj_chunk_number)

    else:
        # process objects from an object store.
        sb = sbs.pop()
        if sb == internal_storage.backend:
            storage = internal_storage.storage
        else:
            storage = Storage(config=config, backend=sb)
        objects = {}
        if obj_names:
            for bucket, prefix in obj_names:
                logger.debug("Listing objects in '{}://{}'"
                             .format(sb, '/'.join([bucket, prefix])))
                if bucket not in objects:
                    objects[bucket] = []
                prefix = prefix + '/' if prefix else prefix
                objects[bucket].extend(storage.list_objects(bucket, prefix))
            logger.debug("Total objects found: {}".format(len(objects[bucket])))
        elif prefixes:
            for bucket, prefix in prefixes:
                logger.debug("Listing objects in '{}://{}'"
                             .format(sb, '/'.join([bucket, prefix])))
                if bucket not in objects:
                    objects[bucket] = []
                prefix = prefix + '/' if prefix else prefix
                objects[bucket].extend(storage.list_objects(bucket, prefix))
            logger.debug("Total objects found: {}".format(len(objects[bucket])))
        elif buckets:
            for bucket in buckets:
                logger.debug("Listing objects in '{}://{}'".format(sb, bucket))
                objects[bucket] = storage.list_objects(bucket)
            logger.debug("Total objects found: {}".format(len(objects[bucket])))

        keys_dict = {}
        for bucket in objects:
            keys_dict[bucket] = {}
            for obj in objects[bucket]:
                keys_dict[bucket][obj['Key']] = obj['Size']

        if buckets or prefixes:
            partitions, ppo = _split_objects_from_buckets(
                                    map_iterdata,
                                    keys_dict,
                                    obj_chunk_size,
                                    obj_chunk_number)

        elif obj_names:
            partitions, ppo = _split_objects_from_keys(
                                    map_iterdata,
                                    keys_dict,
                                    obj_chunk_size,
                                    obj_chunk_number)

    return partitions, ppo


def _split_objects_from_buckets(map_func_args_list, keys_dict, chunk_size, chunk_number):
    """
    Create partitions from bucket/s
    """
    partitions = []
    parts_per_object = []

    if chunk_number:
        logger.debug('Chunk size set to {}'.format(chunk_size))
    elif chunk_size:
        logger.debug('Chunk number set to {}'.format(chunk_number))
    else:
        logger.debug('Chunk size and chunk number not set ')

    for entry in map_func_args_list:
        # Each entry is a bucket
        sb, bucket, prefix, obj_name = utils.split_object_url(entry['obj'])

        for key, obj_size in keys_dict[bucket].items():
            if prefix in key and obj_size > 0:

                if chunk_number:
                    chunk_rest = obj_size % chunk_number
                    obj_chunk_size = (obj_size // chunk_number) + \
                        round((chunk_rest / chunk_number) + 0.5)
                elif chunk_size:
                    obj_chunk_size = chunk_size
                else:
                    obj_chunk_size = obj_size

                size = total_partitions = 0

                ci = obj_size
                cz = obj_chunk_size
                parts = ci // cz + (ci % cz > 0)
                logger.debug('Creating {} partitions from object {} ({})'.format(parts, key, sizeof_fmt(obj_size)))

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
    if chunk_number:
        logger.debug('Chunk size set to {}'.format(chunk_size))
    elif chunk_size:
        logger.debug('Chunk number set to {}'.format(chunk_number))
    else:
        logger.debug('Chunk size and chunk number not set ')

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

        ci = obj_size
        cz = obj_chunk_size
        parts = ci // cz + (ci % cz > 0)
        logger.debug('Creating {} partitions from object {} ({})'
                     .format(parts, key, sizeof_fmt(obj_size)))

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
    if chunk_number:
        logger.debug('Chunk size set to {}'.format(chunk_size))
    elif chunk_size:
        logger.debug('Chunk number set to {}'.format(chunk_number))
    else:
        logger.debug('Chunk size and chunk number not set ')

    partitions = []
    parts_per_object = []

    def _split(entry):
        obj_size = None
        object_url = entry['obj']
        metadata = requests.head(object_url)

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

        ci = obj_size
        cz = obj_chunk_size
        parts = ci // cz + (ci % cz > 0)
        logger.debug('Creating {} partitions from url {} ({})'
                     .format(parts, object_url, sizeof_fmt(obj_size)))

        while size < obj_size:
            brange = (size, size+obj_chunk_size+CHUNK_THRESHOLD)
            brange = None if obj_size == obj_chunk_size else brange

            partition = entry.copy()
            partition['obj'] = CloudObjectUrl(object_url)
            partition['obj'].data_byte_range = brange
            partition['obj'].chunk_size = obj_chunk_size
            partition['obj'].part = total_partitions
            partitions.append(partition)

            total_partitions += 1
            size += obj_chunk_size

        parts_per_object.append(total_partitions)

    with ThreadPoolExecutor(64) as ex:
        ex.map(_split, map_func_args_list)

    return partitions, parts_per_object


def _split_objects_from_paths(map_func_args_list, chunk_size, chunk_number):
    """
    Create partitions from a list of objects urls
    """
    if chunk_number:
        logger.debug('Chunk size set to {}'.format(chunk_size))
    elif chunk_size:
        logger.debug('Chunk number set to {}'.format(chunk_number))
    else:
        logger.debug('Chunk size and chunk number not set ')

    partitions = []
    parts_per_object = []

    def _split(entry):
        path = entry['obj']
        file_stats = os.stat(entry['obj'])
        obj_size = int(file_stats.st_size)

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

        size = total_partitions = 0

        ci = obj_size
        cz = obj_chunk_size
        parts = ci // cz + (ci % cz > 0)
        logger.debug('Creating {} partitions from path {} ({})'
                     .format(parts, path, sizeof_fmt(obj_size)))

        while size < obj_size:
            brange = (size, size+obj_chunk_size+CHUNK_THRESHOLD)
            brange = None if obj_size == obj_chunk_size else brange

            partition = entry.copy()
            partition['obj'] = CloudObjectLocal(path)
            partition['obj'].data_byte_range = brange
            partition['obj'].chunk_size = obj_chunk_size
            partition['obj'].part = total_partitions
            partitions.append(partition)

            total_partitions += 1
            size += obj_chunk_size

        parts_per_object.append(total_partitions)

    with ThreadPoolExecutor(64) as ex:
        ex.map(_split, map_func_args_list)

    return partitions, parts_per_object
