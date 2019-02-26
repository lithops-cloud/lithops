import logging
import requests
from pywren_ibm_cloud import wrenutil

logger = logging.getLogger(__name__)

CHUNK_THRESHOLD = 64*1024  # 64KB


def create_partitions(arg_data, chunk_size, storage):
    """
    Method that returns the function that will create the partitions of the objects in the Cloud
    """
    logger.debug('Starting partitioner')
    map_func_keys = arg_data[0].keys()
    parts_per_object = None

    if 'bucket' in map_func_keys and 'key' not in map_func_keys:
        partitions, parts_per_object = split_objects_from_bucket(arg_data, chunk_size, storage)
        if not partitions:
            raise Exception('No objects available within bucket: {}'.format(arg_data[0]['bucket']))

    elif 'key' in map_func_keys:
        partitions, parts_per_object = split_object_from_key(arg_data, chunk_size, storage)

    elif 'url' in map_func_keys:
        partitions, parts_per_object = split_object_from_url(arg_data, chunk_size)

    else:
        raise ValueError('You did not provide any bucket or object key/url')

    return partitions, parts_per_object


def split_objects_from_bucket(map_func_args_list, chunk_size, storage):
    """
    Create partitions from bucket/s
    """
    logger.info('Creating dataset chunks from bucket/s ...')
    partitions = []
    parts_per_object = []

    for entry in map_func_args_list:
        # Each entry is a bucket
        if chunk_size:
            logger.info('Creating chunks from objects within: {}'.format(entry['bucket']))
        else:
            logger.info('Discovering objects within: {}'.format(entry['bucket']))
        bucket_name, prefix = wrenutil.split_path(entry['bucket'])
        objects = storage.list_objects(bucket_name, prefix)

        for obj in objects:
            key = obj['Key']
            obj_size = obj['Size']
            total_partitions = 0
            #logger.info("Extracted key {} size {}".format(key, obj_size))

            # full_key = '{}/{}'.format(bucket_name, key)
            size = 0
            if chunk_size is not None and obj_size > chunk_size:
                size = 0
                while size < obj_size:
                    brange = (size, size+chunk_size+CHUNK_THRESHOLD)
                    size += chunk_size
                    partition = {}
                    partition['map_func_args'] = entry.copy()
                    partition['map_func_args']['key'] = key
                    partition['map_func_args']['bucket'] = bucket_name
                    partition['data_byte_range'] = brange
                    partition['chunk_size'] = chunk_size
                    partitions.append(partition)
                    total_partitions = total_partitions + 1
            else:
                partition = {}
                partition['map_func_args'] = entry.copy()
                partition['map_func_args']['key'] = key
                partition['map_func_args']['bucket'] = bucket_name
                partition['data_byte_range'] = None
                partition['chunk_size'] = obj_size
                partitions.append(partition)
                total_partitions = total_partitions + 1

            parts_per_object.append(total_partitions)

    return partitions, parts_per_object


def split_object_from_key(map_func_args_list, chunk_size, storage):
    """
    Create partitions from a list of COS objects keys
    """
    if chunk_size:
        logger.info('Creating chunks from object keys...')
    partitions = []
    parts_per_object = []

    for entry in map_func_args_list:
        total_partitions = 0
        object_key = entry['key']
        logger.info(object_key)
        bucket, object_name = object_key.split('/', 1)
        metadata = storage.head_object(bucket, object_name)
        obj_size = int(metadata['content-length'])

        if chunk_size is not None and obj_size > chunk_size:
            size = 0
            while size < obj_size:
                brange = (size, size+chunk_size+CHUNK_THRESHOLD)
                size += chunk_size
                partition = {}
                partition['map_func_args'] = entry
                partition['data_byte_range'] = brange
                partition['chunk_size'] = chunk_size
                partitions.append(partition)
                total_partitions = total_partitions + 1
        else:
            partition = {}
            partition['map_func_args'] = entry
            partition['data_byte_range'] = None
            partition['chunk_size'] = obj_size
            partitions.append(partition)
            total_partitions = total_partitions + 1

        parts_per_object.append(total_partitions)

    return partitions, parts_per_object


def split_object_from_url(map_func_args_list, chunk_size):
    """
    Create partitions from a list of objects urls
    """
    if chunk_size:
        logger.info('Creating chunks from urls...')
    partitions = []
    parts_per_object = []

    for entry in map_func_args_list:
        obj_size = None
        total_partitions = 0
        object_url = entry['url']
        metadata = requests.head(object_url)

        logger.info(object_url)
        #logger.debug(metadata.headers)

        if 'content-length' in metadata.headers:
            obj_size = int(metadata.headers['content-length'])

        if 'accept-ranges' in metadata.headers and chunk_size is not None \
           and obj_size is not None and obj_size > chunk_size:
            size = 0
            while size < obj_size:
                brange = (size, size+chunk_size+CHUNK_THRESHOLD)
                size += chunk_size
                partition = {}
                partition['map_func_args'] = entry
                partition['data_byte_range'] = brange
                partition['chunk_size'] = chunk_size
                partitions.append(partition)
                total_partitions = total_partitions + 1
        else:
            # Only one partition
            partition = {}
            partition['map_func_args'] = entry
            partition['data_byte_range'] = None
            partition['chunk_size'] = obj_size
            partitions.append(partition)
            total_partitions = total_partitions + 1

        parts_per_object.append(total_partitions)

    return partitions, parts_per_object
