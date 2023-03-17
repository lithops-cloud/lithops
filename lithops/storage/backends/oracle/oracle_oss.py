import oci
import shutil
import os
import logging
from oci.object_storage import ObjectStorageClient
from lithops.storage.utils import StorageNoSuchKeyError
from lithops.utils import is_lithops_worker
from lithops.constants import STORAGE_CLI_MSG


logger = logging.getLogger(__name__)

class OCIObjectStorageBackend:
    def __init__(self, config):
        logger.debug("Creating Oracle Object Storage Service client")

        self.config = config
        self.object_storage_client = ObjectStorageClient(config)
     
    def get_client(self):
        return self

    def put_object(self, bucket_name, key, data):
        if isinstance(data, str):
            data = data.encode()

        try:
            print(self.config)

            self.object_storage_client.put_object(self.config['namespace_name'] ,bucket_name, key, data)    
        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name, key)

    def get_object(self, bucket_name, key, stream=False, extra_get_args={}):
        try:
            if 'Range' in extra_get_args:
                byte_range = extra_get_args.pop('Range')
                if isinstance(byte_range, str):
                    byte_range = byte_range.replace('bytes=', '')
                    start, end = byte_range.split('-')
                
                if int(start) != 0:
                    object_length = self.head_object(self.config['namespace_name'], bucket_name, key)['content-length']
                    if int(end) >= object_length:
                        end = object_length - 1
                extra_get_args['byte_range'] = (int(start), int(end))
            data = self.object_storage_client.get_object(self.config['namespace_name'], bucket_name, key)

            if stream:
                return data
            else:
                return data.data.raw.read()
        
        except (oci.exceptions.ServiceError, oci.exceptions.ClientError):
            raise StorageNoSuchKeyError(bucket_name,key)

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

        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name,prefix)


    def list_keys(self, bucket_name, prefix=None):
    
        prefix = '' if prefix is None else prefix
        try:
            res = self.object_storage_client.list_objects(self.config['namespace_name'], bucket_name,prefix=prefix,limit=1000)
            obj_list = [{'Key': obj.name, 'Size': obj.size} for obj in res.data.objects]
            return obj_list

        except oci.exceptions.ServiceError:
            raise StorageNoSuchKeyError(bucket_name,prefix)


"""
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

    

    print(ociobj.list_objects( "cloudlab-bucket"))
    print(ociobj.download_file( "cloudlab-bucket", "test.txt"))
    print(ociobj.upload_file("cloudlab-bucket", "oracle_oss.py"))

"""