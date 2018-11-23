import logging
import requests
import pywren_ibm_cloud as pywren
from pywren_ibm_cloud import wrenutil

logger = logging.getLogger(__name__)

CHUNK_THRESHOLD = 4*1024  # 4KB


def object_partitioner(map_function_wrapper, reduce_function, extra_env, extra_meta):
    """
    Method that returns the function that will create the partitions of the objects in the Cloud
    """
    def object_partitioner_function(map_func_args, chunk_size, storage):
        """
        Partitioner is a function executed in the Cloud to create partitions from objects
        """
        logger.info('Starting partitioner() function')
        map_func_keys = map_func_args[0].keys()
    
        if 'bucket' in map_func_keys and 'key' not in map_func_keys:
            partitions = split_objects_from_bucket(map_func_args, chunk_size, storage)
        
        elif 'key' in map_func_keys:
            partitions = split_object_from_key(map_func_args, chunk_size, storage)
        
        elif 'url' in map_func_keys:
            partitions = split_object_from_url(map_func_args, chunk_size)
        
        else:
            raise ValueError('You did not provide any bucket or object key/url')
    
        # logger.info(partitions)
    
        pw = pywren.ibm_cf_executor()
        futures = pw.map_reduce(map_function_wrapper, partitions,
                                reduce_function,
                                reducer_wait_local=False,
                                extra_env=extra_env,
                                extra_meta=extra_meta)
    
        return futures
        
    
    return object_partitioner_function


def split_objects_from_bucket(map_func_args_list, chunk_size, storage):
    """
    Create partitions from bucket/s
    """
    logger.info('Creating dataset chunks from bucket/s ...')
    partitions = list()

    for entry in map_func_args_list:
        # Each entry is a bucket
        bucket_name, prefix = wrenutil.split_path(entry['bucket'])
        objects = storage.list_objects(bucket_name, prefix)

        logger.info('Creating dataset chunks from objects within "{}" '
                    'bucket ...'.format(bucket_name))

        for obj in objects:
            key = obj['Key']
            obj_size = obj['Size']
            logger.info("Extracted key {} size {}".format(key, obj_size))

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
                    partitions.append(partition)
            else:
                partition = {}
                partition['map_func_args'] = entry.copy()
                partition['map_func_args']['key'] = key
                partition['map_func_args']['bucket'] = bucket_name
                partition['data_byte_range'] = None
                partitions.append(partition)
    return partitions


def split_object_from_key(map_func_args_list, chunk_size, storage):
    """
    Create partitions from a list of COS objects keys
    """
    logger.info('Creating dataset chunks from object keys ...')
    partitions = list()

    for entry in map_func_args_list:
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
                partitions.append(partition)
        else:
            partition = {}
            partition['map_func_args'] = entry
            partition['data_byte_range'] = None
            partitions.append(partition)

    return partitions


def split_object_from_url(map_func_args_list, chunk_size):
    """
    Create partitions from a list of objects urls
    """
    logger.info('Creating dataset chunks from urls ...')
    partitions = list()

    for entry in map_func_args_list:
        obj_size = None
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
                partitions.append(partition)
        else:
            # Only one partition
            partition = {}
            partition['map_func_args'] = entry
            partition['data_byte_range'] = None
            partitions.append(partition)

    return partitions
