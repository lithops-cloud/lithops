
# How to use PyWren for IBM Cloud Functions


## Executor
The primary object in IBM-PyWren is an executor. The standard way to get everything set up is to import pywren_ibm_cloud, and call the ibm_cf_executor() function.

**ibm_cf_executor(\*\*kwargs)**

Initialize and return an executor object.

|Parameters| Description|
|---|---|
|config | Settings passed in here will override those in pywren_config. Default None. |
|runtime |  Name of the runtime to run the functions. |
|runtime_memory | Memory (in MB) to use to run the functions. Default 256. |
|log_level |  Log level printing (INFO, DEBUG, ...). Default None. |
|rabbitmq_monitor | Activate RabbitMQ monitoring. Default False. |

Usage:
```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor()
```

## Executor.call_async()
This method is used to spawn only one function activation that will run asynchronously in the cloud.

ibm_cf_executor.**call_async**(func, data, \*\*kwargs)

|Parameters| Description|
|---|---|
|func | The function to map over the data. |
|data |  A single value of data. |
|extra_env| Additional environment variables for CF environment. Default None. |
|extra_meta|  Additional metadata to pass to CF. Default None. |
|runtime_memory| Memory (in MB) to use to run the functions. Default 256 |
|timeout| Max time per function activation. Default 600. |
|exclude_modules| Explicitly keep these modules from pickled dependencies. Default None. |

* **Returns**: A list with size  len(data)  of futures for each job

* **Usage**:
    ```python
    futures = pw.call_async(foo, data)
    ```
* **Code example**: [call_async.py](examples/call_async.py)

## Executor.map()
This method is used to spawn multiple function activations, based on the items of an input list,  that will run asynchronously .

ibm_cf_executor.**map**(func, iterdata, \*\*kwargs)

|Parameters| Description|
|---|---|
|func | The function to map over the data. |
|iterdata |  An iterable of input data. |
|extra_env| Additional environment variables for CF environment. Default None. |
|extra_meta|  Additional metadata to pass to CF. Default None. |
|runtime_memory| Memory (in MB) to use to run the functions. Default 256 |
|timeout| Max time per function activation. Default 600. |
|exclude_modules| Explicitly keep these modules from pickled dependencies. Default None. |


* **Returns**: A list with size  len(iterdata)  of futures for each job

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    ```
* **Code example**: [map.py](call_async/map.py)

## Executor.map_reduce()
This method is used to spawn multiple *map_function* activations,  based on the items of an input list,  and then spawn one (or multiple) *reduce_function* activations over the results of the map phase.

ibm_cf_executor.**map_reduce**(map_func, iterdata, reduce_func, \*\*kwargs)

|Parameters| Description|
|---|---|
|map_func| The function to map over the data. |
|iterdata |  An iterable of input data. |
|reduce_func|  The function to map over the results of map_func. |
|reducer_wait_local|  Wait locally for map results. Default False. |
|extra_env| Additional environment variables for CF environment. Default None. |
|extra_meta|  Additional metadata to pass to CF. Default None. |
|map_runtime_memory| Memory (in MB) to use to run the map function. Default 256 |
|reduce_runtime_memory| Memory (in MB) to use to run the reduce function. Default 256 |
|timeout| Max time per function activation. Default 600. |
|exclude_modules| Explicitly keep these modules from pickled dependencies. Default None. |


* **Returns**: A list with size  len(iterdata)  of futures for each job

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map_reduce(foo, iterdata, bar)
    ```
* **Code example**: [map_reduce.py](call_async/map_reduce.py)

By default, the *reduce_function* is immediately spawned, and then it waits remotely to get all the results from the map phase. It should be note that, although faster, this approach consumes CPU time in Cloud Functions. You can change this behavior and make *reduce_function* to wait locally for the results by setting the `reducer_wait_local` parameter to `True`. However, it has the tradeoff of greater data transfers, because it has to download all the results to the local machine and then upload them again to the cloud for processing with the *reduce_function*.
