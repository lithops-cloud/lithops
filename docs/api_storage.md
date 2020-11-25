# Lithops Storage API Details

Lithops allows to create a Storage instance and abstract away the backend implementation details. The standard way to get everything set up is to import the lithops `Storage` class and create an instance.


**Storage(\*\*kwargs)**

Initialize and return a Storage object.

|Parameter | Default | Description|
|---|---|---|
|lithops_config |  None | Lithops configuration dictionary |
|backend | cpu_count | Name of the backend |



By default, the configuration is loaded from the lithops config file, so there is no need to provide any parameter to create a Storage instance:

```python
from lithops import Storage
storage = Storage()
```

Alternatively, you can pass the lithops configuration through a dictionary. In this case, it will load the storage backend set in the `storage` key of the `lithops` section:

```python
from lithops import Storage

config = {'lithops' : {'storage' : 'ibm_cos'},
          'ibm_cos': {'region': 'REGION', 'api_key': 'API_KEY'}}

storage = Storage(config=config)
```

In such a case you have multiple storage set in your configuration, you can force the storage backend by using the `backend` parameter:

```python
from lithops import Storage
storage = Storage(backend='redis') # this will create a redis Storage instance
```

or:

```python
from lithops import Storage

config = {'lithops' : {'storage' : 'ibm_cos'},
          'ibm_cos': {'region': 'REGION', 'api_key': 'API_KEY'}}
          'redis': {'host': 'HOST', 'port':'PORT'}}


storage = Storage(config=config)  # this will create an ibm_cos Storage instance
storage = Storage(config=config, backend='redis)  # this will create a redis Storage instance
```

## Storage API Calls

### Storage.put_object(bucket_name, key, data)
Adds an object to a bucket of the storage backend.

|Parameter | Description|
|---|---|
|bucket_name | Name of the bucket (String)|
|key |  Name of the object (String)|
|data| Object data (bytes or seekable file-like object)|


### Storage.get_object(bucket_name, key, \*\*kwargs)
Retrieves objects from the storage backend.

|Parameter | Description|
|---|---|
|bucket_name | Name of the bucket (String)|
|key |  Name of the object (String)|
|stream | Get the object data or a file-like object (True/False) |
|extra_get_args | Extra get arguments to be passed to the underlying backend implementation (dict). For example, to specify the byte-range to read.|


### Storage.head_object(bucket_name, key)
The HEAD operation retrieves metadata from an object without returning the object itself. This operation is useful if you're only interested in an object's metadata. 

|Parameter | Description|
|---|---|
|bucket_name | Name of the bucket (String)|
|key |  Name of the object (String)|


### Storage.delete_object(bucket_name, key)
Removes objects from the storage backend

|Parameter | Description|
|---|---|
|bucket_name | Name of the bucket (String)|
|key |  Name of the object (String)|


### Storage.delete_objects(bucket_name, key_list)
This operation enables you to delete multiple objects from a bucket using a single HTTP request. If you know the object keys that you want to delete, then this operation provides a suitable alternative to sending individual delete requests, reducing per-request overhead.

|Parameter | Description|
|---|---|
|bucket_name | Name of the bucket (String)|
|key_list |  Name of the objects (list)|


### Storage.head_bucket(bucket_name)
This operation is useful to determine if a bucket exists and you have permission to access it. The operation returns a 200 OK if the bucket exists and you have permission to access it. Otherwise, the operation might return responses such as 404 Not Found and 403 Forbidden .

|Parameter | Description|
|---|---|
|bucket_name | Name of the bucket (String)|


### Storage.list_objects(bucket_name, \*\*kwargs)
Returns all of the objects in a bucket. For each object, the list contains the name of the object (key) and the size.

|Parameter | Description|
|---|---|
|bucket_name | Name of the bucket (String)|
|prefix | key prefix for filtering (String)|


### Storage.list_keys(bucket_name, \*\*kwargs)
Similar to lit_objects(), it returns all of the objects in a bucket. For each object, the list contains only the names of the objects (keys).

|Parameter | Description|
|---|---|
|bucket_name | Name of the bucket (String)|
|prefix | key prefix for filtering (String)|


### Storage.get_client()
Returns the underlying storage backend client. For example, if `Storage` is an instance built on top of AWS S3, it returns a boto3 client.


### Storage.put_cloudobject()

### Storage.get_cloudobject()

### Storage.delete_cloudobject()

### Storage.delete_cloudobjects()

