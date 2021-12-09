import gcsfs
import os
import shutil
import logging
from lithops.storage.utils import StorageNoSuchKeyError
from lithops.constants import STORAGE_CLI_MSG

logger = logging.getLogger(__name__)


class GcsfsStorageBackend:
    """
    A wrapper around gcsfs APIs.
    """

    def __init__(self, gcfs_config):
        logger.debug("Creating gcsfs storage client")
        self.config = gcfs_config
        self.fs = gcsfs.GCSFileSystem(project=gcfs_config["project_id"])
        msg = STORAGE_CLI_MSG.format('gcfs')
        logger.info("{}".format(msg))

    def put_object(self, bucket_name, key, data):
        """
        Put an object in localhost filesystem.
        Override the object if the key already exists.
        :param key: key of the object.
        :param data: data of the object
        :type data: str/bytes
        :return: None
        """
        try:
            data_type = type(data)
            file_path = "{}/{}".format(bucket_name, key)
            if data_type == bytes:
                with self.fs.open(file_path, "wb") as f:
                    f.write(data)
            else:
                with self.fs.open(file_path, "w") as f:
                    f.write(data)
        except Exception as e:
            raise(e)

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        """
        Get object from localhost filesystem with a key.
        Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        try:
            file_path = "{}/{}".format(bucket_name, key)
            with self.fs.open(file_path, "rb") as f:
                if 'Range' in extra_get_args:
                    byte_range = extra_get_args['Range'].replace('bytes=', '')
                    first_byte, last_byte = map(int, byte_range.split('-'))
                    f.seek(first_byte)
                    return f.read(last_byte-first_byte+1)
                else:
                    return f.read()
        except Exception as e:
            raise StorageNoSuchKeyError(bucket_name, key)

    def upload_file(self, file_name, bucket, key=None, extra_args={}):
        """Upload a file

        :param file_name: File to upload
        :param bucket: Bucket to upload to
        :param key: S3 object name. If not specified then file_name is used
        :return: True if file was uploaded, else False
        """
        # If S3 key was not specified, use file_name
        if key is None:
            key = os.path.basename(file_name)

        # Upload the file
        try:
            with open(file_name, 'rb') as in_file:
                self.put_object(bucket, key, in_file)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def download_file(self, bucket, key, file_name=None, extra_args={}):
        """Download a file

        :param bucket: Bucket to download from
        :param key: S3 object name. If not specified then file_name is used
        :param file_name: File to upload
        :return: True if file was downloaded, else False
        """
        # If file_name was not specified, use S3 key
        if file_name is None:
            file_name = key

        # Download the file
        try:
            dirname = os.path.dirname(file_name)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname)
            with open(file_name, 'wb') as out:
                data_stream = self.get_object(bucket, key, stream=True)
                shutil.copyfileobj(data_stream, out)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def head_object(self, bucket_name, key):
        """
        Head object from local filesystem with a key.
        Throws StorageNoSuchKeyError if the given key does not exist.
        :param key: key of the object
        :return: Data of the object
        :rtype: str/bytes
        """
        pass

    def delete_object(self, bucket_name, key):
        """
        Delete an object from storage.
        :param bucket: bucket name
        :param key: data key
        """
        file_path = "{}/{}".format(bucket_name, key)
        if self.fs.exists(file_path):
            self.fs.rm(file_path, recursive=True)

    def delete_objects(self, bucket_name, key_list):
        """
        Delete a list of objects from storage.
        :param bucket: bucket name
        :param key_list: list of keys
        """
        for key in key_list:
            self.delete_object(bucket_name, key)

    def head_bucket(self, bucket_name):
        """
        Head localhost dir with a name.
        Throws StorageNoSuchKeyError if the given bucket does not exist.
        :param bucket_name: name of the bucket
        :return: Metadata of the bucket
        :rtype: str/bytes
        """
        raise NotImplementedError

    def list_objects(self, bucket_name, prefix=None):
        """
        Return a list of objects for the prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of objects in bucket that match the given prefix.
        :rtype: list of str
        """
        raise NotImplementedError

    def list_keys(self, bucket_name, prefix=None):
        """
        Return a list of keys for the given prefix.
        :param bucket_name: Name of the bucket.
        :param prefix: Prefix to filter object names.
        :return: List of keys in bucket that match the given prefix.
        :rtype: list of str
        """
        root = "{}/{}".format(bucket_name, prefix)
        # Important not to cache dir listings, since Lithops polls for changes
        self.fs.invalidate_cache(root) 
        try:
            return [key.replace("{}/".format(bucket_name), "") for key in self.fs.ls(root)]
        except FileNotFoundError:
            return []
