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

class OCIObjectStorageBackend:
    def __init__(self, config):
        logger.debug("Creating Oracle Object Storage Service client")

        self.config = config
        if 'key_file' in config and os.path.isfile(config['key_file']):
            print("Using Oracle Object Storage CLI")
            self.object_storage_client = ObjectStorageClient(config)
        else:
            signer = oci.auth.signers.get_resource_principals_signer()
            self.object_storage_client = ObjectStorageClient(config={}, signer=signer)
    
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
            response = self.object_storage_client.put_object(self.config['namespace_name'], bucket_name, key, data)
            status = 'OK' if response.status == 200 else 'Error'
            
            try:
                logger.debug('PUT Object {} - Size: {} - {}'.format(key, sizeof_fmt(len(data)), status))
            except Exception:
                logger.debug('PUT Object {} {}'.format(key, status))
        except oci.exceptions.ServiceError as e:
            logger.info("ServiceError in put_object: %s", str(e))
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
            logger.info("OCI_RESOURCE_PRINCIPAL_VERSION: %s", os.environ.get("OCI_RESOURCE_PRINCIPAL_VERSION"))
            logger.info("OCI_RESOURCE_PRINCIPAL_RPST: %s", os.environ.get("OCI_RESOURCE_PRINCIPAL_RPST"))
            logger.info("OCI_RESOURCE_PRINCIPAL_PRIVATE_PEM: %s", os.environ.get("OCI_RESOURCE_PRINCIPAL_PRIVATE_PEM"))
            print("Request get_object: %s %s", bucket_name, key)
            logger.info("Request get_object: %s %s", bucket_name, key)
            
            r = self.object_storage_client.get_object(self.config['namespace_name'], bucket_name, key, **extra_get_args)
            
            if stream:
                data = r.data
            else:
                data = r.data.content
            
            return data
        except oci.exceptions.ServiceError as e:
            logger.info("ServiceError in get_object: %s", str(e))
            logger.info("Listing objects in bucket {}:".format(bucket_name))
            logger.info(" - %s",self.list_objects(bucket_name))
            print("Listing objects in bucket {}:".format(self.list_objects(bucket_name)))
            raise StorageNoSuchKeyError(bucket_name, key)
           
        

    def upload_file(self, file_name, bucket, key=None, extra_args={}):
        if key is None:
            key = os.path.basename(file_name)

        try:
            with open(file_name, 'rb') as in_file:
                self.object_storage_client.put_object(self.config['namespace_name'], bucket, key, in_file)
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
                data_stream = self.object_storage_client.get_object(self.config['namespace_name'], bucket, key).data.content
                out.write(data_stream)
        except Exception as e:
            logging.error(e)
            return False
        return True

    def head_object(self, bucket_name, key):
        
        try:
            headobj = self.object_storage_client.head_object(self.config['namespace_name'], bucket_name, key).headers
            return headobj
        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name,key)

    
    def delete_object(self, bucket_name, key):
        self.object_storage_client.delete_object(self.config['namespace_name'], bucket_name, key)
    
    def delete_objects(self, bucket_name, keys_list):
        for key in keys_list:
            self.object_storage_client.delete_objects(self.config['namespace_name'], bucket_name, key)

    def head_bucket(self, bucket_name):
        try:
            metadata = self.object_storage_client.head_bucket(self.config['namespace_name'], bucket_name)
            return vars(metadata)
        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name,'')
    
    def list_objects(self, bucket_name, prefix=None):
        
        prefix = '' if prefix is None else prefix
        try:
            res = self.object_storage_client.list_objects(self.config['namespace_name'], bucket_name,prefix=prefix,limit=1000)
            obj_list = [obj.name for obj in res.data.objects]
            return obj_list

        except oci.exceptions.ServiceError as e:
            logger.info("ServiceError in list_objects: %s", str(e))

            raise StorageNoSuchKeyError(bucket_name,prefix)


    def list_keys(self, bucket_name, prefix=None):
    
        prefix = '' if prefix is None else prefix
        try:
            res = self.object_storage_client.list_objects(self.config['namespace_name'], bucket_name,prefix=prefix,limit=1000)
            obj_list = [{'Key': obj.name, 'Size': obj.size} for obj in res.data.objects]
            return obj_list

        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name,prefix)


if __name__ == "__main__":
    config = {
        
        "user": "ocid1.user.oc1..aaaaaaaa35yjlnfrox4km4cmwectgtclrgwvpmjrheuyqi3tj3biavqxkmiq",
        "key_file": "/home/ayman/ayman.bourramouss@urv.cat_2023-01-09T12_07_06.729Z.pem",
        "fingerprint": "cf:b9:a6:85:a5:6e:06:23:20:35:76:af:71:ff:a9:52",
        "tenancy": "ocid1.tenancy.oc1..aaaaaaaaedomxxeig7qoo5fmbbvsohbmp6nial74sh2so32zk3wxnc2erxta",
        "region": "eu-madrid-1",
        "compartment_id": "ocid1.compartment.oc1..aaaaaaaa6fwt7css3rvvryfi5gjrqvrdakkdlkizltk7c7dxy35bfkpms57q",
        "namespace_name":"axwup7ph7ej7"
    }
    from oci.config import validate_config

    validate_config(config)
    ociobj = OCIObjectStorageBackend(config)

    

    print(ociobj.get_object( "cloudlab-bucket", "tst.txt"))
    