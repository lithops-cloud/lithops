# Lithops Storage API Details

Lithops allows to create a **Storage** instance and abstract away the backend implementation details. The standard way to get a Storage object set up is to import the lithops `Storage` class and create an instance.


**Storage(\*\*kwargs)**

Initialize and return a Storage object.

|Parameter | Default | Description|
|---|---|---|
|config |  None | Lithops configuration dictionary |
|backend | None | Name of the backend |



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

In case you have multiple storage set in your configuration, you can force the storage backend by using the `backend` parameter:

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
storage = Storage(config=config, backend='redis')  # this will create a redis Storage instance
```

## Storage API Calls

### `Storage.put_object()`

Adds an object to a bucket of the storage backend.

**put_object**(bucket, key, data)

|Parameter | Description|
|---|---|
|bucket | Name of the bucket (String)|
|key |  Name of the object (String)|
|data| Object data (bytes/string or seekable file-like object)|

* **Usage**:

    ```python
    storage = Storage()
    # Bytes/string data
    storage.put_object('my_bucket', 'test.txt', 'Hello World')
    ```
        
    ```python
    storage = Storage()
    # Seekable file-like object
    with open('/tmp/my_big_file.csv', 'rb') as fl:
        storage.put_object('my_bucket', 'my_big_file.csv', fl)
    ```


### `Storage.get_object()`

Retrieves objects from the storage backend.

**get_object**(bucket, key, \*\*kwargs)

|Parameter | Description|
|---|---|
|bucket | Name of the bucket (String)|
|key |  Name of the object (String)|
|stream | Get the object data or a file-like object (True/False) |
|extra_get_args | Extra get arguments to be passed to the underlying backend implementation (dict). For example, to specify the byte-range to read: `extra_get_args={'Range': 'bytes=0-100'}`|

* **Usage**:

    ```python
    storage = Storage()
    data = storage.get_object('my_bucket', 'test.txt')
    ```


### `Storage.head_object()`
The HEAD operation retrieves metadata from an object without returning the object itself. This operation is useful if you're only interested in an object's metadata. 

**head_object**(bucket, key)

|Parameter | Description|
|---|---|
|bucket | Name of the bucket (String)|
|key |  Name of the object (String)|

* **Usage**:

    ```python
    storage = Storage()
    obj_metadata = storage.head_object('my_bucket', 'test.txt')
    ```


### `Storage.delete_object()`

Removes objects from the storage backend

**delete_object**(bucket, key)

|Parameter | Description|
|---|---|
|bucket | Name of the bucket (String)|
|key |  Name of the object (String)|

* **Usage**:

    ```python
    storage = Storage()
    storage.delete_object('my_bucket', 'test.txt')
    ```

### `Storage.delete_objects()`

This operation enables you to delete multiple objects from a bucket using a single HTTP request. If you know the object keys that you want to delete, then this operation provides a suitable alternative to sending individual delete requests, reducing per-request overhead.

**delete_objects**(bucket, key_list)

|Parameter | Description|
|---|---|
|bucket | Name of the bucket (String)|
|key_list |  Name of the objects (list)|

* **Usage**:

    ```python
    storage = Storage()
    storage.delete_objects('my_bucket', ['test1.txt', 'test2.txt'])
    ```


### `Storage.head_bucket()`

This operation is useful to determine if a bucket exists and you have permission to access it. The operation returns a 200 OK if the bucket exists and you have permission to access it. Otherwise, the operation might return responses such as 404 Not Found and 403 Forbidden .

**head_bucket**(bucket)

|Parameter | Description|
|---|---|
|bucket | Name of the bucket (String)|

* **Usage**:

    ```python
    storage = Storage()
    storage.head_bucket('my_bucket')
    ```


### `Storage.list_objects()`

Returns all of the objects in a bucket. For each object, the list contains the name of the object (key) and the size.

**list_objects**(bucket, \*\*kwargs)

|Parameter | Description|
|---|---|
|bucket | Name of the bucket (String)|
|prefix | key prefix for filtering (String)|

* **Usage**:

    ```python
    storage = Storage()
    storage.list_objects('my_bucket', prefix='temp/')
    ```


### `Storage.list_keys()`

Similar to list_objects(), it returns all of the objects in a bucket. For each object, the list contains only the names of the objects (keys).

**list_keys**(bucket, \*\*kwargs)

|Parameter | Description|
|---|---|
|bucket | Name of the bucket (String)|
|prefix | key prefix for filtering (String)|

* **Usage**:

    ```python
    storage = Storage()
    storage.list_keys('my_bucket')
    ```


### `Storage.get_client()`
Returns the underlying storage backend client. For example, if `Storage` is an instance built on top of AWS S3, it returns a boto3 client.

**get_client**()

* **Usage**:

    ```python
    storage = Storage()
    boto3_client = storage.get_client()
    ```

### `Storage.put_cloudobject()`

Adds objects to a bucket of the storage backend. Returns a **cloudobject** that is a reference to the object.

**put_cloudobject**(body, \*\*kwargs)

|Parameter | Description|
|---|---|
|body| Object data (bytes/string or seekable file-like object)|
|bucket | Name of the bucket (String). By default it uses the `storage_bucket`|
|key |  Name of the object (String). By default it creates a random key|

If `bucket` paramter is not provided, it will use the `storage_bucket` set in the lithops config. If `key` is not provided, it will create a random temporary key.

* **Usage**:

    ```python
    storage = Storage()
    # Bytes/string
    cobj = storage.put_cloudobject('Hello World!')
    ```
    
    ```python
    storage = Storage()
    # Seekable file-like object
    with open('/tmp/my_big_file.csv', 'rb') as fl:
        cobj = storage.put_cloudobject(fl)
    ```


### `Storage.get_cloudobject()`

Retrieves CloudObjects from a bucket of the storage backend.

**get_cloudobject**(cloudobject, \*\*kwargs)


|Parameter | Description|
|---|---|
|cloudobject| CloudObject Instance|
|stream | Get the object data or a file-like object (True/False) |


* **Usage**:

    ```python
    storage = Storage()
    cobj = storage.put_cloudobject('Hello World!', 'my-bucket', 'test.txt')
    data = storage.get_cloudobject(cobj)
    ```


### `Storage.delete_cloudobject()`

Removes CloudObjects from a bucket of the storage backend.

**delete_cloudobject**(cloudobject)


|Parameter | Description|
|---|---|
|cloudobject| CloudObject Instance|


* **Usage**:

    ```python
    storage = Storage()
    cobj = storage.put_cloudobject('Hello World!', 'test.txt')
    storage.delete_cloudobject(cobj)
    ```

### `Storage.delete_cloudobjects()`

This operation enables you to delete multiple objects from a bucket using a single HTTP request. If you know the object keys that you want to delete, then this operation provides a suitable alternative to sending individual delete requests, reducing per-request overhead.

**delete_cloudobject**(cloudobjects, \*\*kwargs)


|Parameter | Description|
|---|---|
|cloudobjects| CloudObject Instances (list)|


* **Usage**:

    ```python
    storage = Storage()
    cobj1 = storage.put_cloudobject('Hello World!', 'test1.txt')
    cobj2 = storage.put_cloudobject('Hello World!', 'test2.txt')
    storage.delete_cloudobjects([cobj1, cobj2])