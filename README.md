PyWren over IBM Cloud Functions and IBM Cloud Object Storage
==============================

### What is PyWren
[PyWren](https://github.com/pywren/pywren) is an open source project whose goals are massively scaling the execution of Python code and its dependencies on serverless computing platforms and monitoring the results. PyWren delivers the user’s code into the serverless platform without requiring knowledge of how functions are invoked and run. 

PyWren provides great value for the variety of uses cases, like processing data in object storage, running embarrassingly parallel compute jobs (e.g. Monte-Carlo simulations), enriching data with additional attributes and many more

### PyWren and IBM Cloud
This repository is based on [PyWren](https://github.com/pywren/pywren) main branch and adapted for IBM Cloud Functions and IBM Cloud Object Storage. 
PyWren for IBM Cloud is based on Docker images and we also extended PyWren to execute a reduce function, which now enables PyWren to run complete map reduce flows.  In extending PyWren to work with IBM Cloud Object Storage, we also added a partition discovery component that allows PyWren to process large amounts of data stored in the IBM Cloud Object Storage. See [changelog](changelog.md) for more details.

This is still a beta version and is rapidly changed so please keep yourself updated.

This document describes the steps to use PyWren-IBM-Cloud over IBM Cloud Functions and IBM Cloud Object Storage (COS)

### IBM Cloud for Academic institutions
[IBM Academic Initiative](https://developer.ibm.com/academic/) is a special program that allows free trial of IBM Cloud for Academic institutions. This program provided for students and faculty staff members and allow up to 12 month of free usage. Please follow [here](https://onthehub.com/ibm/), check if you eligible for this program and setup your account free of charge.

## Initial Requirements
* IBM Cloud Function account, as described [here](https://console.bluemix.net/openwhisk/). Make sure you can run end-to-end example with Python.
* IBM Cloud Object Storage [account](https://www.ibm.com/cloud/object-storage)
* Python 3.6 (preferable) or Python 3.5

## PyWren Setup

### Install PyWren 

Clone the repository and run the setup script:

    git clone https://github.com/pywren/pywren-ibm-cloud
    or
    git clone git@github.com:pywren/pywren-ibm-cloud.git

Navigate into `pywren-ibm-cloud` folder

    cd pywren-ibm-cloud/pywren

If you plan to develop code, stay in the master branch. Otherwise obtain the most recent stable release version from the `release` tab. For example, if release is `v1.0.0` then execute

	git checkout v1.0.0

Build and install 
	
    python3 setup.py install --force

or

    pip install -U .

### Deploy PyWren main runtime

You need to deploy the PyWren runtime to your IBM Cloud Functions namespace and create the main PyWren action. PyWren main action is responsible to execute Python functions inside PyWren runtime within IBM Cloud Functions. The strong requirement here is to match Python versions between the client and the runtime. The runtime may also contain additional packages which your code depends on.

PyWren-IBM-Cloud shipped with default runtime:

| Runtime name | Python version | Packages included |
| ----| ----| ---- |
| pywren_3.6 | 3.6 | [list of packages](https://console.bluemix.net/docs/openwhisk/openwhisk_reference.html#openwhisk_ref_python_environments_3.6) |

To deploy the default runtime, navigate into `runtime` folder and execute:

	./deploy_runtime

This script will automatically create a Python 3.6 action named `pywren_3.6` which is based on `python:3.6` IBM docker image (Debian Jessie). 
This action is the main runtime used to run functions within IBM Cloud Functions with PyWren. 

If your client uses different Python version or there is need to add additional packages to the runtime, then it is necessary to build a custom runtime. Detail instructions can be found [here](runtime/).

			
### Configuration keys

Configure PyWren client with access details to your Cloud Object Storage account and with your IBM Cloud Functions account.

Access details to IBM Cloud Functions can be obtained [here](https://console.bluemix.net/openwhisk/learn/api-key). Details on your COS account can be obtained from the "service credentials" page on the UI of your COS account. More details on "service credentials" can be obtained [here](docs/cos-info.md)

Summary of configuration keys

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|pywren|storage_bucket||yes|Any bucket that exists in your COS account. This will be used by PyWren for intermediate data |
|pywren|storage_prefix|pywren.jobs|no|Storage prefix is a virtual sub-directory in the bucket, to provide better control over location where PyWren writes temporary data. The COS location will be `storage_bucket/storage_prefix` |
|pywren|data_cleaner|False|no|If set to True, then cleaner will automatically delete temporary data that was written into `storage_bucket/storage_prefix`|
|pywren | storage_backend| ibm_cos | no | backend storage implementation. IBM COS is the default |
|pywren | invocation_retry| True | no | Retry invocation in case of failure |
|pywren | retry_sleeps | [1, 5, 10, 20, 30] | no | Number of seconds to wait before retry |
|pywren| retries | 5 | no | number of retries |
|ibm_cf| endpoint | | yes | IBM Cloud Functions hostname. Endpoint is the value of 'host' from [api-key](https://console.bluemix.net/openwhisk/learn/api-key). Make sure to use https:// prefix |
|ibm_cf| namespace | | yes | IBM Cloud Functions namespace. Value of CURRENT NAMESPACE from [api-key](https://console.bluemix.net/openwhisk/learn/api-key) |
|ibm_cf| api_key | | yes | IBM Cloud Functions api key. Value of api key from [api-key](https://console.bluemix.net/openwhisk/learn/api-key) |
|ibm_cf| action_timeout | 600000 |no |  Default timeout |
|ibm_cf| action_memory | 512 | no | Default memory |
|ibm_cos | endpoint | | yes | Endpoint to your COS account. Make sure to use full path. for example https://s3-api.us-geo.objectstorage.softlayer.net |
|ibm_cos | api_key | | yes | API Key to your COS account|

#####  Using in-memory storage for temporary data

You can configure PyWren to use in-memory storage to keep the temporary data. We support currently [CloudAMQP](https://console.bluemix.net/catalog/services/cloudamqp) and more other services will be supported at later stage. To enable PyWren to use this service please setup additional key

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
| rabbitmq |amqp_url | |no | Value of AMQP URL from the Management dashboard of CloudAMQP service |

In addition, activate service by

	pw = pywren.ibm_cf_executor(use_rabbitmq=True)


### Configuration

There are two options to configure PyWren:

#### Using configuration file
Copy the `pywren/ibmcf/default_config.yaml.template` into `~/.pywren_config`

Edit `~/.pywren_config` and configure the following entries:

```yaml
pywren: 
    storage_bucket: <BUCKET_NAME>
    storage_prefix: <pywren.jobs>
    data_cleaner : <True / False>

ibm_cf:
    # Obtain all values from https://console.bluemix.net/openwhisk/learn/api-key

    # endpoint is the value of 'host'
    # make sure to use https:// as prefix
    endpoint    : <CF_API_ENDPOINT>
    # namespace = value of CURRENT NAMESPACE
    namespace   : <CF_NAMESPACE>
    api_key     : <CF_API_KEY>
   
ibm_cos:
    # make sure to use full path.
    # for example https://s3-api.us-geo.objectstorage.softlayer.net
    endpoint   : <COS_API_ENDPOINT>
    # this is preferable authentication method for IBM COS
    api_key    : <COS_API_KEY>
    # alternatively you may use HMAC authentication method
    # access_key : <ACCESS_KEY>
    # secret_key : <SECRET_KEY>

```

You can choose different name for the config file or keep into different folder. If this is the case make sure you configure system variable 
	
	PYWREN_CONFIG_FILE=<LOCATION OF THE CONFIG FILE>

Using configuration file you can obtain PyWren executor with:

```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor()
```

#### Configuration in the runtime
This option allows you pass all the configuration details as part of the PyWren invocation in runtime. All you need is to configure a Python dictionary with keys and values, for example:

```python
config = {'pywren' : {'storage_bucket' : 'BUCKET_NAME'},

          'ibm_cf':  {'endpoint': 'CF_API_ENDPOINT', 
                      'namespace': 'CF_NAMESPACE', 
                      'api_key': 'CF_API_KEY'}, 

          'ibm_cos': {'endpoint': 'COS_API_ENDPOINT', 
                      'api_key': 'COS_API_KEY'}
         }
```

Having configuration allows you to provide it to the PyWren as follows:

```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor(config=config)
```


### Verify 

To test that all is working, run the [testpywren.py](test/testpywren.py) located in the `test` folder with the arguments listed below.

For initializing test files using IBM Cloud Object Storage service, execute once from the project root folder:

	python3 test/testpywren.py init
	
and then execute:

| Command | Explanation |
|---| ---| 
| `python3 test/testpywren.py` | test all PyWren's functionality |
| `python3 test/testpywren.py pywren` | test PyWren without Cloud Object Storage service |
| `python3 test/testpywren.py pywren_cos` | test PyWren using Cloud Object Storage service only |
| `python3 test/testpywren.py <FUNC_NAME>` | run a specific test function by its name as implemented in the test file |

To clean test files stored in Cloud Object Storage service, execute:

    python3 test/testpywren.py clean

_NOTE:_ The test script assumes that a local PyWren's config file was set correctly.

To edit tests' data, open the [data](test/data) file located in the `test` folder and simply add or remove text URL files.

## How to use PyWren for IBM Cloud Functions

	
1. **Single function execution example**.

    ```python
    import pywren_ibm_cloud as pywren
    
    def my_function(x):
        return x + 7
    
    pw = pywren.ibm_cf_executor()
    pw.call_async(my_function, 3)
    result = pw.get_result()
    ```

2. **Multiple function execution (Map).**

	To run multiple functions in parallel, the executor contains a method called **map()** which applies a function to a list of data in the cloud.
	The **map()** method will launch one function for each entry of the list. 
	To get the results of a **map()** call  **`get_result()`** method. The results are returned within an ordered list, where each element of the list is the result of one invocation.
	For example, in the next code PyWren will launch one function for each value within `iterdata`:

    ```python
    import pywren_ibm_cloud as pywren
    
    iterdata = [1, 2, 3, 4] 
    
    def my_map_function(x):
        return x + 7
    
    pw = pywren.ibm_cf_executor()
    pw.map(my_map_function, iterdata)
    result = pw.get_result()
    ```
    and `result` will be: `[8, 9, 10, 11]`

3. **Multiple function execution with reduce (map-reduce).**

	PyWren allows to run a *reduce* function over the results of the *map*. 
	The **`map_reduce()`** method waits until it gets the results from all the *map* functions, and then launches the *reduce* function. By default the *reduce* method waits locally to get all the results. This approach does not consumes CPU time in Cloud Functions, but it has the tradeoff of greater data transfers because it has to download all the results and then upload them again for processing with the *reduce* function.
	After call the **`map_reduce()`**, it is possible to get the result from it by calling the **`get_result()`** method.

    ```python
    import pywren_ibm_cloud as pywren
    
    iterdata = [1, 2, 3, 4] 
    
    def my_map_function(x):
        return x + 7
    
    def my_reduce_function(results):
        total = 0
        for map_result in results:
            total = total + map_result
        return total
    
    pw = pywren.ibm_cf_executor()
    pw.map_reduce(my_map_function, iterdata, my_reduce_function)
    result = pw.get_result()
    ```
	In this example the `result` will be `38`
	
	By default the reducer waits locally for the results, and then launches the **reduce()** function in the cloud.
	You can change this behaviour and make the reducer waits remotely for the results by setting the 
	`reducer_wait_local` parameter of the **map_reduce()** method to `False`.
	
	```python
    pw.map_reduce(my_map_function, iterdata, my_reduce_function, reducer_wait_local=False)
    ```
	
## Using PyWren to process data from IBM Cloud Object Storage


PyWren for IBM Cloud functions has a built-in method for processing data objects from the IBM Cloud Object Storage.
	
We designed a partitioner within the **map_reduce()** method which is configurable by specifying the size of the chunk.  The input to the partitioner may be either a list of data objects, a list of URLs or the entire bucket itself. The partitioner is activated inside PyWren and it responsible to split the objects into smaller chunks. It executes one *`my_map_function`* for each object chunk and when all executions are completed, the partitioner executes the *`my_reduce_function`*. The reduce function will wait for all the partial results before processing them. 

In the parameters of the `my_map_function` function you must specify a parameter called **data_stream**. This variable allows access to the data stream of the object.

`map_reduce` method has different signatures as shown in the following examples

#### `map_reduce` where partitioner get the list of objects

```python
import pywren_ibm_cloud as pywren

iterdata = ['bucket1/object1', 'bucket1/object2', 'bucket1/object3'] 

def my_map_function(key, data_stream):
    for line in data_stream:
        # Do some process
    return partial_intersting_data

def my_reduce_function(results):
    for partial_intersting_data in results:
        # Do some process
    return final_result

chunk_size = 4*1024**2  # 4MB

pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, iterdata, my_reduce_function, chunk_size)
result = pw.get_result()
```

| method | method signature |
|---| ---| 
| `pw.map_reduce`(`my_map_function`, `iterdata`, `my_reduce_function`, `chunk_size`)| `iterdata` contains list of objects in the format of `bucket_name/object_name` |
| `my_map_function`(`key`, `data_stream`) | `key` is an entry from `iterdata` that is assigned to the invocation|

#### `map_reduce` where partitioner gets entire bucket

Commonly, a dataset may contains hundreds or thousands of files, so the previous approach where you have to specify each object one by one is not well suited in this case. With this new **map_reduce()** method you can specify, instead, the bucket name which contains all the object of the dataset.
	
```python
import pywren_ibm_cloud as pywren

bucket_name = 'my_data_bucket'

def my_map_function(bucket, key, data_stream, ibm_cos):
    for line in data_stream:
        # Do some process
    return partial_intersting_data

def my_reduce_function(results):
    for partial_intersting_data in results:
        # Do some process
    return final_result

chunk_size = 4*1024**2  # 4MB

pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, bucket_name, my_reduce_function, chunk_size)
result = pw.get_result()
```

* If `chunk_size=None` then partitioner's granularity is a single object. 
	
| method | method signature |
|---| ---| 
| `pw.map_reduce`(`my_map_function`, `bucket_name`, `my_reduce_function`, `chunk_size`)| `bucket_name` contains the name of the bucket |
| `my_map_function`(`bucket`, `key`, `data_stream`, `ibm_cos`) | `key` is a data object from `bucket` that is assigned to the invocation. `ibm_cos` is an optional parameter which provides a `boto3_client` (see [here](#geting-boto3-client-from-any-map-function))|



#### `map_reduce` where partitioner gets the list of urls

```python
import pywren_ibm_cloud as pywren

iterdata = ['http://myurl/myobject1', 'http://myurl/myobject1'] 

def my_map_function(url, data_stream):
    for line in data_stream:
        # Do some process
    return partial_intersting_data

def my_reduce_function(results):
    for partial_intersting_data in results:
        # Do some process
    return final_result

chunk_size = 4*1024**2  # 4MB

pw = pywren.ibm_cf_executor()
pw.map_reduce(my_map_function, iterdata, my_reduce_function, chunk_size)
result = pw.get_result()
```

| method | method signature |
|---| ---| 
| `pw.map_reduce`(`my_map_function`, `iterdata`, `my_reduce_function`, `chunk_size`)| `iterdata` contains list of objects in the format of `http://myurl/myobject.data` |
| `my_map_function`(`url`, `data_stream`) | `url` is an entry from `iterdata` that is assigned to the invocation|

### Reducer granularity			
By default there will be one reducer for all the objects. If you need one reducer for each object, you must set the parameter
`reducer_one_per_object=True` into the **map_reduce()** method.

```python
pw.map_reduce(my_map_function, bucket_name, my_reduce_function, 
              chunk_size, reducer_one_per_object=True)
```

### Geting boto3 client from any map function
Any map function can get `ibm_cos` parameter which is [boto3_client](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#client). This allows you to access your IBM COS account from any map function, for example:
    
```python
import pywren_ibm_cloud as pywren

iterdata = [1, 2, 3, 4]

def my_map_function(x, ibm_cos):
    data_object = ibm_cos.get_object(Bucket='mybucket', Key='mydata.data')
    # Do some process over the object
    return x + 7

pw = pywren.ibm_cf_executor()
pw.map(my_map_function, iterdata)
result = pw.get_result()
```

## PyWren and IBM Watson Studio
You can use PyWren inside an **IBM Watson Studio** notebook in order to execute parallel data analytics by using **IBM Cloud functions**.

### How to install PyWren within IBM Watson Studio
It is possible to use PyWren inside an **IBM Watson Studio** notebook in order to execute parallel data analytics by using **IBM Cloud functions**.
As the current **IBM Watson Studio** runtimes does not contains the **PyWren** package, it is needed to install it. Add these lines at the beginning of the notebook:

```python
try:
    import pywren_ibm_cloud as pywren
except:
    !curl -fsSL "https://git.io/fhe9X" | sh
    import pywren_ibm_cloud as pywren
```
Installation script supports PyWren version as an input parameter, for example:

	curl -fsSL "https://git.io/fhe9X" | sh /dev/stdin 1.0.3

or

	curl -fsSL "https://git.io/fhe9X" | sh /dev/stdin master
	
If version is not provided then scipt fetch the latest release

### Deploy PyWren runtime to your IBM Cloud Functions
You can create PyWren runtime from the notebook itself:

```python
from pywren_ibm_cloud.deployutil import clone_runtime
clone_runtime('<dockerhub_space>/<name>:<version>', config, 'pywren-ibm-cloud')
```

## Additional resources

* [Ants, serverless computing, and simplified data processing](https://developer.ibm.com/blogs/2019/01/31/ants-serverless-computing-and-simplified-data-processing/)
* [Speed up data pre-processing with PyWren in deep learning](https://developer.ibm.com/patterns/speed-up-data-pre-processing-with-pywren-in-deep-learning/)
* [Predicting the future with Monte Carlo simulations over IBM Cloud Functions](https://www.ibm.com/blogs/bluemix/2019/01/monte-carlo-simulations-with-ibm-cloud-functions/)
* [Process large data sets at massive scale with PyWren over IBM Cloud Functions](https://www.ibm.com/blogs/bluemix/2018/04/process-large-data-sets-massive-scale-pywren-ibm-cloud-functions/)
* [PyWren for IBM Cloud on CODAIT](https://developer.ibm.com/code/open/centers/codait/projects/pywren/)
* [Industrial project in Technion on PyWren-IBM](http://www.cs.technion.ac.il/~cs234313/projects_sites/W19/04/site/)
* [Serverless data analytics in the IBM Cloud](https://dl.acm.org/citation.cfm?id=3284029) - Proceedings of the 19th International Middleware Conference (Industry)