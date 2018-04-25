PyWren over IBM Cloud Functions and IBM Cloud Object Storage
==============================

### What is PyWren
[PyWren](https://github.com/pywren/pywren) is an open source project whos goals are massively scaling the execution of Python code and its dependencies on serverless computing platforms and monitoring the results. PyWren delivers the user’s code into the serverless platform without requiring knowledge of how functions are invoked and run. 

PyWren provides great value for the variety of uses cases, like processing data in object storage, running embarrassingly parallel compute jobs (e.g. Monte-Carlo simulations), enriching data with additional attributes and many more

### PyWren and IBM Cloud
This repository is based on [PyWren](https://github.com/pywren/pywren) main branch and adapted for IBM Cloud Functions and IBM Cloud Object Storage. 
PyWren for IBM Cloud is based on the Docker images and we also extended PyWren to execute a reduce function, which now enables PyWren to run complete map reduce flows.  In extending PyWren to work with IBM Cloud Object Storage, we also added a partition discovery component that allows PyWren to process large amounts of data stored in the IBM Cloud Object Storage. See [changelog](changelog.md) for more details.

This is still a beta version and is rapidly changed so please keep yourself updated.

This documents describes the steps to use PyWren-IBM-Cloud over IBM Cloud Functions and IBM Cloud Object Storage (COS)

## Initial Requirements
* An active IBM Cloud Function account, as described [here](https://console.bluemix.net/openwhisk/)
* IBM Cloud Object Storage [account](https://www.ibm.com/cloud/object-storage)
* `bx` and `wsk` command line tools [installed](https://console.bluemix.net/openwhisk/learn/cli)
* Python 3.6 (preferable) or Python 3.5

## PyWren Setup

### Install PyWren 

To install PyWren you can use the provided installation script or install it manually. This will install PyWren package into your local Python libraries.

#### Install PyWren using the installation script

Run in a terminal:
    
    curl -fsSL "https://raw.githubusercontent.com/pywren/pywren-ibm-cloud/master/install_pywren.sh" | sh

#### Install PyWren manually

Clone the repository and run the setup script:

    git clone https://github.com/pywren/pywren-ibm-cloud
    cd pywren-ibm-cloud/pywren
	python3 setup.py install 

### Deploy PyWren main runtime

You need to deploy PyWren runtime to your IBM Cloud Functions name space and create a main Pywren action. PyWren main action responsible to execute Python functions inside PyWren runtime within IBM Cloud Functions. The strong requirement here is to match Python versions between the client and the runtime. Runtime may also contain additional packages which your code depends on.

PyWren-IBM-Cloud shipped with default runtime

| Runtime name | Python version | Packages included |
| ----| ----| ---- |
| python-jessie:3 | 3.6 | [list of packages](https://console.bluemix.net/docs/openwhisk/openwhisk_reference.html#openwhisk_ref_python_environments_jessie) |

To deploy default runtime, navigate into `pywren-ibm-cloud` folder and execute

	./deploy_pywren.sh

This script will automatically create a Python 3.6 action named `pywren_3.6` which is based on `python-jessie:3` IBM docker image. 
This action is the main runtime used to run functions within IBM Cloud Functions with PyWren. 
Notice also that script make uses of `bx wsk` command line tool, so previously to run the deploy script, login to your desired region where you want to run PyWren `bx login`, and target to the Cloud Foundry org/space by running `bx target --cf`.

If your client uses different Python version or there is need to add aditional packages to the runtime, then there is need to build custom runtime. Detail instructions can be found [here](docs/pywren-ibm-cloud-runtime.md)

			
### Configuration

Configure PyWren client with access details to your Cloud Object Storage account and with your IBM Cloud Functions account.

Access details to IBM Cloud Functions can be obtained [here](https://console.bluemix.net/openwhisk/learn/api-key). Details on your COS account can be obtained from the "service credentials" page on the UI of your COS account. More details on "service credentials" can be obtained [here](docs/cos-info.md)

There are two options to configure PyWren

#### Using configuration file
Copy the `pywren/ibmcf/default_config.yaml.template` into `~/.pywren_config`.

Edit `~/.pywren_config` and configure the following entries:

```yaml
pywren: 
    storage_bucket: <BUCKET_NAME>

ibm_cf:
    endpoint    : <CF_API_ENDPOINT>
    namespace   : <CF_NAMESPACE>
    api_key     : <CF_API_KEY>

ibm_cos:
    endpoint   : <COS_API_ENDPOINT>
    api_key    : <COS_API_KEY>
```

Using configuration file you can obtain PyWren executor with:

```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor()
```

#### Configuration in the runtime
This option allows you pass all the configuration details as part of the PyWren invokation in runtime. All you need is to configure a Python dictionary:

```python
config = {'pywren' : {'storage_bucket' : 'BUCKET_NAME'}

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


#### Configuration keys
The following summarizes the keys that need to be configured.

| Group | Key | Value |
|---|  --- | --- |	    
| pywren | storage_bucket |  Any bucket that exists in your COS account. This will be used by PyWren for intermidate data |
| ibm_cf | endpoint | IBM Cloud Functions hostname|
| ibm_cf | namespace | IBM Cloud Functions namespace|
| ibm_cf | api_key | IBM Cloud Functions api key|
| ibm_cos | endpoint | Endpoint to your COS account |
| ibm_cos | api_key | API Key to your COS account |


### Verify 

To test that all is working, run the [pywrentest](https://github.ibm.com/cloud-platforms/pywren-ibm-cloud/blob/master/examples/pywrentest.py) located in the `examples` folder.

	python3 pywrentest.py

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
	`reducer_wait_local` paramreter of the **map_reduce()** method to `False`.
	
	```python
    pw.map_reduce(my_map_function, iterdata, my_reduce_function, reducer_wait_local=False)
    ```
	
## Using PyWren to process data from IBM Cloud Object Storage


PyWren for IBM Cloud functions has a built-in method for processing data objects from the IBM Cloud Object Storage.
	
We designed a partitioner within the **map_reduce()** method which is configurable by specifying the size of the chunk.  The input to the partitioner may be either list of data objects, list of URLs or the entire bucket itself. Partitioners activated inside PyWren and it responsible to split the objects into smaller chunks. It executes one *`my_map_function`* for each object chunk and when all executions are completed,  partitioner executes the *`my_reduce_function`*. This method will wait for all the partial results before processing them. 

In the parameters of the `my_map_function` function you must specify a parameter called **data_stream**. This variable allows an access to the data stream of the object.

`map_reduce` method has different signatures as shown in the following examples

#### `map_reduce` where patititoner get the list of objects

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
| `my_map_function(key, data_stream)` | `key` is an entry from `iterdata` that is assigned to the invocation|

#### `map_reduce` where partitioner gets entire bucket

Commonly, a dataset may contains hundreds or thousands of files, so the previous approach where you have to specify each object one by one is not well suited in this case. With this new **map_reduce()** method you can specify, instead, the bucket name which contains all the object of the dataset.
	
```python
import pywren_ibm_cloud as pywren

bucket_name = 'my_data_bucket'

def my_map_function(bucket, key, data_stream):
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
	
| method | method signature |
|---| ---| 
| `pw.map_reduce`(`my_map_function`, `bucket_name `, `my_reduce_function`, `chunk_size`)| `bucket_name ` contains the name of the bucket |
| `my_map_function(bucket, key, data_stream)` | `key` is a data object from bucket `bucket` that is assigned to the invocation|



#### `map_reduce` where patititoner get the list of urls

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
| `my_map_function(url, data_stream)` | `url` is an entry from `iterdata` that is assigned to the invocation|

### Reducer granularity			
By default there will be one reducer for all the objects. If you need one reducer for each object, you must set the parameter
`reducer_one_per_object=True` into the **map_reduce()** method.

```python
pw.map_reduce(my_map_function, bucket_name, my_reduce_function, 
              chunk_size, reducer_one_per_object=True)
```

## How to install PyWren within IBM Watson Studio
It is possible to use PyWren inside an **IBM Watson Studio** notebook in order to execute parallel data analytics by using **IBM Cloud functions**.
As the current **IBM Watson Studio** runtimes does not contains the **PyWren** package, it is needed to install it. Add this line at the beginning of the notebook:

```python
try:
    import pywren_ibm_cloud as pywren
except:
    !curl -fsSL "https://raw.githubusercontent.com/pywren/pywren-ibm-cloud/master/install_pywren.sh" | sh
    import pywren_ibm_cloud as pywren
```
