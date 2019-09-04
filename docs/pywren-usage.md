
# How to use PyWren for IBM Cloud Functions


## Executor
The primary object in IBM-PyWren is an executor. The standard way to get everything set up is to import pywren_ibm_cloud, and call the ibm_cf_executor() function.

**ibm_cf_executor(\*\*kwargs)**

Initialize and return an executor object. All the parameters set in the executor will overwrite those set in the configuration.

|Parameter | Default | Description|
|---|---|---|
|config | None | Settings passed in here will override those in pywren_config|
|runtime |  None | Name of the runtime to run the functions |
|runtime_memory | 256 | Memory (in MB) to use to run the functions |
|log_level | None | Log level printing (INFO, DEBUG, ...) |
|rabbitmq_monitor | False | Activate RabbitMQ monitoring |

Usage:
```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor()
```

## Executor.call_async()
Spawn only one function activation.

ibm_cf_executor.**call_async**(func, data, \*\*kwargs)

|Parameter | Default |Description|
|---|---|---|
|func | |The function to map over the data |
|data |  |A single value of data |
|extra_env| None |Additional environment variables for CF environment|
|extra_meta|  None |Additional metadata to pass to CF |
|runtime_memory| 256 |Memory (in MB) to use to run the functions|
|timeout| 600 |Max time per function activation (seconds)|
|exclude_modules| None |Explicitly keep these modules from pickled dependencies |

* **Returns**: A list with size  len(data)  of futures for each job

* **Usage**:
    ```python
    futures = pw.call_async(foo, data)
    ```
* **Code example**: [call_async.py](../examples/call_async.py)

## Executor.map()
Spawn multiple function activations based on the items of an input list.

ibm_cf_executor.**map**(func, iterdata, \*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|func | |The function to map over the data |
|iterdata |  |An iterable of input data (e.g python list) |
|extra_env| None |Additional environment variables for CF environment |
|extra_meta|  None |Additional metadata to pass to CF |
|runtime_memory| 256 |Memory (in MB) to use to run the functions |
|timeout| 600 |Max time per function activation (seconds) |
|exclude_modules| None |Explicitly keep these modules from pickled dependencies |


* **Returns**: A list with size  len(iterdata)  of futures for each job

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    ```
* **Code example**: [map.py](../examples/map.py)

## Executor.map_reduce()
Spawn multiple *map_function* activations,  based on the items of an input list,  eventually spawning one (or multiple) *reduce_function* activations over the results of the map phase.

ibm_cf_executor.**map_reduce**(map_func, iterdata, reduce_func, \*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|map_func| |The function to map over the data |
|iterdata |  |An iterable of input data (e.g python list)|
|reduce_func|  |The function to map over the results of map_func |
|reducer_wait_local| False |Wait locally for map results |
|extra_env| None | Additional environment variables for CF environment|
|extra_meta|  None | Additional metadata to pass to CF|
|map_runtime_memory| 256 | Memory (in MB) to use to run the map function|
|reduce_runtime_memory| 256| Memory (in MB) to use to run the reduce function|
|timeout| 600 | Max time per function activation (seconds)|
|exclude_modules| None| Explicitly keep these modules from pickled dependencies|


* **Returns**: A list with size  len(iterdata)  of futures for each job

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map_reduce(foo, iterdata, bar)
    ```
* **Code example**: [map_reduce.py](../examples/map_reduce.py)

By default, the *reduce_function* is immediately spawned, and then it waits remotely to get all the results from the map phase. It should be note that, although faster, this approach consumes CPU time in Cloud Functions. You can change this behavior and make *reduce_function* to wait locally for the results by setting the `reducer_wait_local` parameter to `True`. However, it has the tradeoff of greater data transfers, because it has to download all the results to the local machine and then upload them again to the cloud for processing with the *reduce_function*.
