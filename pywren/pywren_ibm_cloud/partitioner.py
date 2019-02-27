import logging
import requests
import inspect
import struct
import io
from pywren_ibm_cloud import wrenutil

logger = logging.getLogger(__name__)

CHUNK_THRESHOLD = 128*1024  # 128KB


def partition_processor(map_function, data_type):
    """
    Method that returns the function to process objects in the Cloud.
    It creates a ready-to-use data_stream parameter
    """
    def object_processing_wrapper(map_func_args, data_byte_range, chunk_size, storage, ibm_cos):
        extra_get_args = {}
        if data_byte_range is not None:
            range_str = 'bytes={}-{}'.format(*data_byte_range)
            extra_get_args['Range'] = range_str
            print(extra_get_args)

        logger.info('Getting dataset')
        if 'url' in map_func_args:
            # it is a public url
            resp = requests.get(map_func_args['url'], headers=extra_get_args, stream=True)
            map_func_args['data_stream'] = resp.raw

        elif 'key' in map_func_args:
            # it is a COS key
            if 'bucket' not in map_func_args or ('bucket' in map_func_args and not map_func_args['bucket']):
                bucket, key = map_func_args['key'].split('/', 1)
            else:
                bucket = map_func_args['bucket']
                key = map_func_args['key']

            sb = storage.get_object(bucket, key, stream=True, extra_get_args=extra_get_args)
            wsb = WrappedStreamingBody(sb, chunk_size)
            map_func_args['data_stream'] = wsb

        func_sig = inspect.signature(map_function)
        if 'storage' in func_sig.parameters:
            map_func_args['storage'] = storage

        if 'ibm_cos' in func_sig.parameters:
            map_func_args['ibm_cos'] = ibm_cos

        return map_function(**map_func_args)

    return object_processing_wrapper


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


def object_processing(map_function):
    """
    Method that returns the function to process objects in the Cloud.
    It creates a ready-to-use data_stream parameter
    """
    def object_processing_function_wrapper(map_func_args, data_byte_range, chunk_size, storage, ibm_cos):
        extra_get_args = {}
        if data_byte_range is not None:
            range_str = 'bytes={}-{}'.format(*data_byte_range)
            extra_get_args['Range'] = range_str
            print(extra_get_args)

        logger.info('Getting dataset')
        if 'url' in map_func_args:
            # it is a public url
            resp = requests.get(map_func_args['url'], headers=extra_get_args, stream=True)
            map_func_args['data_stream'] = resp.raw

        elif 'key' in map_func_args:
            # it is a COS key
            if 'bucket' not in map_func_args or ('bucket' in map_func_args and not map_func_args['bucket']):
                bucket, key = map_func_args['key'].split('/', 1)
            else:
                bucket = map_func_args['bucket']
                key = map_func_args['key']

            sb = storage.get_object(bucket, key, stream=True, extra_get_args=extra_get_args)
            wsb = wrenutil.WrappedStreamingBody(sb, chunk_size)
            map_func_args['data_stream'] = wsb

        func_sig = inspect.signature(map_function)
        if 'storage' in func_sig.parameters:
            map_func_args['storage'] = storage

        if 'ibm_cos' in func_sig.parameters:
            map_func_args['ibm_cos'] = ibm_cos

        return map_function(**map_func_args)

    return object_processing_function_wrapper


class WrappedStreamingBody:
    """
    Wrap boto3's StreamingBody object to provide enough Python fileobj functionality,
    and to discard data added by partitioner and cut lines.

    from https://gist.github.com/debedb/2e5cbeb54e43f031eaf0

    """
    def __init__(self, sb, size):
        # The StreamingBody we're wrapping
        self.sb = sb
        # Initial position
        self.pos = 0
        # Size of the object
        self.size = size
        # Mark for the end of the file
        self.eof = False

    def tell(self):
        # print("In tell()")
        return self.pos

    def read(self, n=None):
        retval = self.sb.read()

        if retval == "":
            raise EOFError()

        self.pos += len(retval)

        # Find end of the line in threshold
        if self.pos > self.size:
            buf = io.BytesIO(retval)
            while not self.eof:
                buf.readline()
                if buf.tell() > self.size:
                    retval = retval[:buf.tell()]
                    self.eof = True

        return retval

    def readline(self):
        if self.eof:
            raise EOFError()
        try:
            retval = self.sb._raw_stream.readline()
        except struct.error:
            raise EOFError()
        self.pos += len(retval)

        if self.pos >= self.size:
            self.eof = True

        return retval

    def seek(self, offset, whence=0):
        # print("Calling seek()")
        retval = self.pos
        if whence == 2:
            if offset == 0:
                retval = self.size
            else:
                raise Exception("Unsupported")
        else:
            if whence == 1:
                offset = self.pos + offset
                if offset > self.size:
                    retval = self.size
                else:
                    retval = offset
        # print("In seek(%s, %s): %s, size is %s" % (offset, whence, retval, self.size))

        self.pos = retval
        return retval

    def __str__(self):
        return "WrappedBody"

    def __getattr__(self, attr):
        # print("Calling %s"  % attr)

        if attr == 'tell':
            return self.tell
        elif attr == 'seek':
            return self.seek
        elif attr == 'read':
            return self.read
        elif attr == 'readline':
            return self.readline
        elif attr == '__str__':
            return self.__str__
        else:
            return getattr(self.sb, attr)
