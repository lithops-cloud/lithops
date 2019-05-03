PyWren over IBM Cloud Functions and IBM Cloud Object Storage
==============================

### What is PyWren
[PyWren](https://github.com/pywren/pywren) is an open source project whose goals are massively scaling the execution of Python code and its dependencies on serverless computing platforms and monitoring the results. PyWren delivers the user’s code into the serverless platform without requiring knowledge of how functions are invoked and run. 

PyWren provides great value for the variety of uses cases, like processing data in object storage, running embarrassingly parallel compute jobs (e.g. Monte-Carlo simulations), enriching data with additional attributes and many more

### PyWren and IBM Cloud
This repository is based on [PyWren](https://github.com/pywren/pywren) main branch and adapted for IBM Cloud Functions and IBM Cloud Object Storage. 
PyWren for IBM Cloud is based on Docker images and we also extended PyWren to execute a reduce function, which now enables PyWren to run complete map reduce flows.  In extending PyWren to work with IBM Cloud Object Storage, we also added a partition discovery component that allows PyWren to process large amounts of data stored in the IBM Cloud Object Storage. See [changelog](changelog.md) for more details.

This document describes the steps to use PyWren-IBM-Cloud over IBM Cloud Functions and IBM Cloud Object Storage (IBM COS)

### IBM Cloud for Academic institutions
[IBM Academic Initiative](https://developer.ibm.com/academic/) is a special program that allows free trial of IBM Cloud for Academic institutions. This program provided for students and faculty staff members and allow up to 12 month of free usage. Please follow [here](https://ibm.onthehub.com/), check if you eligible for this program and setup your account free of charge.


# Getting Started
1. [Initial requirements](#initial-requirements)
2. [PyWren setup](#pywren-setup)
3. [Configuration](#configuration)
4. [Verify installation](#verify)
5. [How to use PyWren for IBM Cloud](#how-to-use-pywren-for-ibm-cloud-functions)
6. [Using PyWren to process data from IBM Cloud Object Storage](#using-pywren-to-process-data-from-ibm-cloud-object-storage)
7. [PyWren on IBM Watson Studio and Jupyter notebooks](#pywren-on-ibm-watson-studio-and-jupyter-notebooks)
8. [Additional resources](#additional-resources)


## Initial Requirements
* IBM Cloud Functions account, as described [here](https://cloud.ibm.com/openwhisk/). Make sure you can run end-to-end example with Python.
* IBM Cloud Object Storage [account](https://www.ibm.com/cloud/object-storage)
* Python 3.5, Python 3.6 or Python 3.7


## PyWren Setup

Install PyWren from the PyPi repository:

	pip3 install pywren-ibm-cloud

Installation for developers can be found [here](docs/dev-installation.md).


## Configuration

Configure PyWren client with access details to your IBM Cloud Object Storage (COS) account, and with your IBM Cloud Functions account.

Access details to IBM Cloud Functions can be obtained [here](https://cloud.ibm.com/openwhisk/learn/api-key). Details on your IBM Cloud Object Storage account can be obtained from the "service credentials" page on the UI of your COS account. More details on "service credentials" can be obtained [here](docs/cos-info.md).

There are two options to configure PyWren:

### Using configuration file
Copy the `config/default_config.yaml.template` into `~/.pywren_config`

Edit `~/.pywren_config` and configure the following entries:

```yaml
pywren: 
    storage_bucket: <BUCKET_NAME>

ibm_cf:
    # Obtain all values from https://cloud.ibm.com/openwhisk/learn/api-key
    endpoint    : <HOST>  # make sure to use https:// as prefix
    namespace   : <NAMESPACE>
    api_key     : <API_KEY>
   
ibm_cos:
    # Region endpoint example: https://s3.us-east.cloud-object-storage.appdomain.cloud
    endpoint   : <REGION_ENDPOINT>  # make sure to use https:// as prefix
    # this is preferable authentication method for IBM COS
    api_key    : <API_KEY>
    # alternatively you may use HMAC authentication method
    # access_key : <ACCESS_KEY>
    # secret_key : <SECRET_KEY>

```

You can choose different name for the config file or keep it into different folder. If this is the case make sure you configure system variable 
	
	PYWREN_CONFIG_FILE=<LOCATION OF THE CONFIG FILE>


### Configuration in the runtime
This option allows you pass all the configuration details as part of the PyWren invocation in runtime. All you need is to configure a Python dictionary with keys and values, for example:

```python
config = {'pywren' : {'storage_bucket' : 'BUCKET_NAME'},

          'ibm_cf':  {'endpoint': 'HOST', 
                      'namespace': 'NAMESPACE', 
                      'api_key': 'API_KEY'}, 

          'ibm_cos': {'endpoint': 'REGION_ENDPOINT', 
                      'api_key': 'API_KEY'}}
```

You can find more configuration keys [here](docs/configuration.md).


###  Obtain PyWren executor

Using configuration file you can obtain PyWren executor with:

```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor()
```
Having a Python dictionary configuration allows you to provide it to the PyWren as follows:

```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor(config=config)
```

###  Runtime
The runtime is the place where your functions will be executed. In IBM-PyWren, runtimes are based on docker images. It includes by default three different runtimes that allow to run the functions in Python 3.5, Python 3.6 and Python 3.7 environments.

| Runtime name | Python version | Packages included |
| ----| ----| ---- |
| ibmfunctions/pywren:3.5 | 3.5 |  |
| ibmfunctions/action-python-v3.6 | 3.6 | [list of packages](https://github.com/ibm-functions/runtime-python/blob/master/python3.6/CHANGELOG.md) |
| ibmfunctions/action-python-v3.7 | 3.7 | [list of packages](https://github.com/ibm-functions/runtime-python/blob/master/python3.7/CHANGELOG.md) |

IBM-PyWren automatically deploys the default runtime in the first execution, based on the Python version that you are using.
By default, it uses 256MB as runtime memory size. However, you can change it in the `config` or when you obtain the executor, for example:

```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor(runtime_memory=128)
```

You can also build custom runtimes with libraries that your functions depends on. Check more information about runtimes [here](runtime/).

## Verify 

To test that all is working, execute:
```python
from pywren_ibm_cloud import testpywren
testpywren.run()
```
Notice that if you didn't set a local PyWren's config file, you need to provide it as a dictionary by the `config` parameter of `run()` method which uses the default local config file if this parameter is `None`. 

Alternatively, for debugging purposes, you can also run [testpywren.py](pywren_ibm_cloud/testpywren.py) directly which located in the `pywren_ibm_cloud` folder with the arguments listed below.

| Command | Explanation |
|---| ---| 
| `python3 pywren_ibm_cloud/testpywren.py` | test all PyWren's functionality |
| `python3 pywren_ibm_cloud/testpywren.py pywren` | test PyWren without Cloud Object Storage service |
| `python3 pywren_ibm_cloud/testpywren.py pywren_cos` | test PyWren using Cloud Object Storage service only |
| `python3 pywren_ibm_cloud/testpywren.py <FUNC_NAME>` | run a specific test function by its name as implemented in the test file |

The test script assumes that a local PyWren's config file was set correctly.

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

## PyWren on IBM Watson Studio and Jupyter notebooks
You can use IBM-PyWren inside an **IBM Watson Studio** or Jupyter notebooks in order to execute parallel data analytics by using **IBM Cloud functions**.

### How to install PyWren within IBM Watson Studio
As the current **IBM Watson Studio** runtimes does not contains the **PyWren** package, it is needed to install it. Add these lines at the beginning of the notebook:

```python
try:
    import pywren_ibm_cloud as pywren
except:
    !{sys.executable} -m pip install pywren-ibm-cloud
    import pywren_ibm_cloud as pywren
```
Installation supports PyWren version as an input parameter, for example:

	!{sys.executable} -m pip install -U pywren-ibm-cloud==1.0.7

### Usage in notebooks
Once installed, you can use IBM-PyWren as usual inside a notebook:

```python
import pywren_ibm_cloud as pywren

iterdata = [1, 2, 3, 4]

def my_map_function(x):
    return x + 7

pw = pywren.ibm_cf_executor()
pw.map(my_map_function, iterdata)
result = pw.get_result()
```

## Additional resources

* [Ants, serverless computing, and simplified data processing](https://developer.ibm.com/blogs/2019/01/31/ants-serverless-computing-and-simplified-data-processing/)
* [Speed up data pre-processing with PyWren in deep learning](https://developer.ibm.com/patterns/speed-up-data-pre-processing-with-pywren-in-deep-learning/)
* [Predicting the future with Monte Carlo simulations over IBM Cloud Functions](https://www.ibm.com/blogs/bluemix/2019/01/monte-carlo-simulations-with-ibm-cloud-functions/)
* [Process large data sets at massive scale with PyWren over IBM Cloud Functions](https://www.ibm.com/blogs/bluemix/2018/04/process-large-data-sets-massive-scale-pywren-ibm-cloud-functions/)
* [PyWren for IBM Cloud on CODAIT](https://developer.ibm.com/code/open/centers/codait/projects/pywren/)
* [Industrial project in Technion on PyWren-IBM](http://www.cs.technion.ac.il/~cs234313/projects_sites/W19/04/site/)
* [Serverless data analytics in the IBM Cloud](https://dl.acm.org/citation.cfm?id=3284029) - Proceedings of the 19th International Middleware Conference (Industry)