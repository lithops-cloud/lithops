import oci
import shutil
import os
import logging
from oci.object_storage import ObjectStorageClient
from lithops.storage.utils import StorageNoSuchKeyError
from lithops.utils import is_lithops_worker
from lithops.constants import STORAGE_CLI_MSG
from lithops.utils import sizeof_fmt


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class OCIObjectStorageBackend:
    def __init__(self, config):
        
        logger.info("Creating Oracle Object Storage Service client")
        self.config = config
        self.namespace = config['namespace_name']
        self.region_name = config['region']
        
        if 'key_file' in config and os.path.isfile(config['key_file']):
            self.object_storage_client = ObjectStorageClient(config)
        else:
            signer = oci.auth.signers.get_resource_principals_signer()
            self.object_storage_client = ObjectStorageClient(config={}, signer=signer)

        msg = STORAGE_CLI_MSG.format('Oracle Object Storage')
        logger.info(f"{msg} - Region: {self.region_name}")
    
    def get_client(self):
        return self

    def put_object(self, bucket_name, key, data):
        '''
        Put an object in OCI Object Storage. Override the object if the key already exists.
        :param bucket_name: name of the bucket.
        :param key: key of the object.
        :param data: data of the object
        :type data: str/bytes
        :return: None
        '''
        
        if isinstance(data, str):
            data = data.encode()

        try:
            self.object_storage_client.put_object(self.namespace, bucket_name, key, data)
            
        except oci.exceptions.ServiceError as e:
            logger.debug("ServiceError in put_object: %s", str(e))
            raise StorageNoSuchKeyError(bucket_name, key)
           

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        '''
        Get object from OCI Object Storage with a key. Throws NoSuchKey if the given key does not exist.
        :param config: OCI config object
        :param namespace: Object storage namespace
        :param bucket_name: Bucket name
        :param key: Key of the object
        :param stream: Whether to return a stream or read the data
        :param extra_get_args: Additional arguments for get_object
        :return: Data of the object
        :rtype: str/bytes
        '''
        
        try:
            logger.debug("OCI_RESOURCE_PRINCIPAL_VERSION: %s", os.environ.get("OCI_RESOURCE_PRINCIPAL_VERSION"))
            logger.debug("OCI_RESOURCE_PRINCIPAL_RPST: %s", os.environ.get("OCI_RESOURCE_PRINCIPAL_RPST"))
            logger.debug("OCI_RESOURCE_PRINCIPAL_PRIVATE_PEM: %s", os.environ.get("OCI_RESOURCE_PRINCIPAL_PRIVATE_PEM"))
            
            
            r = self.object_storage_client.get_object(self.namespace, bucket_name, key, **extra_get_args)
            
            if stream:
                data = r.data
            else:
                data = r.data.content
            
            return data
        except oci.exceptions.ServiceError as e:
            raise StorageNoSuchKeyError(bucket_name, key)
           
        

    def upload_file(self, file_name, bucket, key=None, extra_args={}):
        if key is None:
            key = os.path.basename(file_name)

        try:
            with open(file_name, 'rb') as in_file:
                self.object_storage_client.put_object(self.namespace, bucket, key, in_file)
        except Exception as e:
            logging.error(e)
            return False
        return True
    

    def download_file(self, bucket, key, file_name=None, extra_args={}):
        if file_name is None:
            file_name = key

        # Download the file
        try:
            dirname = os.path.dirname(file_name)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname)
            with open(file_name, 'wb') as out:
                data_stream = self.object_storage_client.get_object(self.namespace, bucket, key).data.content
                out.write(data_stream)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def head_object(self, bucket_name, key):
        
        try:
            headobj = self.object_storage_client.head_object(self.namespace, bucket_name, key).headers
            return headobj
        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name,key)

    
    def delete_object(self, bucket_name, key):
        self.object_storage_client.delete_object(self.namespace, bucket_name, key)
    
    def delete_objects(self, bucket_name, keys_list):
        for key in keys_list:
            self.object_storage_client.delete_objects(self.namespace, bucket_name, key)

    def head_bucket(self, bucket_name):
        try:
            metadata = self.object_storage_client.head_bucket(self.namespace, bucket_name)
            return vars(metadata)
        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name,'')
    
    def list_objects(self, bucket_name, prefix=None):
        
        prefix = '' if prefix is None else prefix
        try:
            res = self.object_storage_client.list_objects(self.namespace, bucket_name,prefix=prefix,limit=1000)
            obj_list = [obj.name for obj in res.data.objects]
            return obj_list

        except oci.exceptions.ServiceError as e:
            logger.debug("ServiceError in list_objects: %s", str(e))
            raise StorageNoSuchKeyError(bucket_name,prefix)


    def list_keys(self, bucket_name, prefix=None):
    
        prefix = '' if prefix is None else prefix
        try:
            res = self.object_storage_client.list_objects(self.namespace, bucket_name,prefix=prefix,limit=1000)
            obj_list = [{'Key': obj.name, 'Size': obj.size} for obj in res.data.objects]
            return obj_list

        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name,prefix)



    