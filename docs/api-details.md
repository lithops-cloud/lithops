
# PyWren API Details


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
|runtime_memory| 256 |Memory (in MB) to use to run the functions|
|timeout| 600 |Max time per function activation (seconds)|
|exclude_modules| None |Explicitly keep these modules from pickled dependencies |

* **Returns**: One future for each job (Futures are also internally stored by PyWren).

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
|map_function | |The function to map over the data |
|map_iterdata |  |An iterable of input data (e.g python list) |
|extra_params|  None | Additional parameters to pass to each map_function activation |
|extra_env| None |Additional environment variables for CF environment |
|runtime_memory| 256 |Memory (in MB) to use to run the functions |
|timeout| 600 |Max time per function activation (seconds) |
|exclude_modules| None |Explicitly keep these modules from pickled dependencies |


* **Returns**: A list with size  len(iterdata) of futures for each job (Futures are also internally stored by PyWren).

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
|map_function| |The function to map over the data |
|map_iterdata |  |An iterable of input data (e.g python list)|
|extra_params|  None | Additional parameters to pass to each map_function activation |
|reduce_function|  |The function to map over the results of map_func |
|reducer_wait_local| False |Wait locally for map results |
|extra_env| None | Additional environment variables for CF environment|
|map_runtime_memory| 256 | Memory (in MB) to use to run the map function|
|reduce_runtime_memory| 256| Memory (in MB) to use to run the reduce function|
|timeout| 600 | Max time per function activation (seconds)|
|exclude_modules| None| Explicitly keep these modules from pickled dependencies|


* **Returns**: A list with size  len(iterdata)  of futures for each job (Futures are also internally stored by PyWren).

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map_reduce(foo, iterdata, bar)
    ```
* **Code example**: [map_reduce.py](../examples/map_reduce.py)

By default, the *reduce_function* is immediately spawned, and then it waits remotely to get all the results from the map phase. It should be note that, although faster, this approach consumes CPU time in Cloud Functions. You can change this behavior and make *reduce_function* to wait locally for the results by setting the `reducer_wait_local` parameter to `True`. However, it has the tradeoff of greater data transfers, because it has to download all the results to the local machine and then upload them again to the cloud for processing with the *reduce_function*.

## Executor.monitor()
Waits for the function activations to finish.

ibm_cf_executor.**monitor**(\*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|futures| None | List of futures to monitor. If None, PyWren uses the internally stored futures |
|throw_except | True | Re-raise exception if call raised|
|return_when| 'ALL_COMPLETED' | One of 'ALL_COMPLETED', 'ANY_COMPLETED', 'ALWAYS' |
|download_results| False | Whether or not download the results results while monitoring activations |
|timeout| 600 | Timeout of waiting for results|
|THREADPOOL_SIZE|  128 | Number of threads to use waiting for results|
|WAIT_DUR_SEC| 1 |  Time interval between each check (seconds)|


* **Returns**: `(fs_done, fs_notdone)` where `fs_done` is a list of futures that have completed and `fs_notdone` is a list of futures that have not completed.

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    pw.monitor()
    ```
* **Code example**: [monitoring.py](../examples/monitoring.py)

## Executor.get_result()
Gets the results from all the function activations. It internally makes use of the `Executor.monitor()` method.

ibm_cf_executor.**get_result**(\*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|futures| None | List of futures to get the results. If None, PyWren uses the internally stored futures |
|throw_except | True | Re-raise exception if call raised|
|timeout| 600 | Timeout of waiting for results|
|THREADPOOL_SIZE|  128 | Number of threads to use waiting for results|
|WAIT_DUR_SEC| 1 |  Time interval between each check (seconds)|


* **Returns**: If `Executor.call_async()` is called, it returns one result.  If `Executor.map()` is called, it returns a list of results from all the `map_func` calls. The results are returned within an ordered list, where each element of the list is the result of one activation. If `Executor.map_reduce()` is called, it only returns the result of the `reduce_func`.

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    results = pw.get_result()
    ```
* **Code example**: [call_async.py](../examples/call_async.py), [map.py](../examples/map.py), [map_reduce.py](../examples/map_reduce.py)

## Executor.create_execution_plots()
Creates 2 execution plots: A timeline plot and a histogram plot.

ibm_cf_executor.**create_execution_plots**(dst_dir, dst_name, \*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|dst_dir|   | Destination directory to store the plots |
|dst_name |   | name-prefix of the plots|
|futures| None | List of futures to plot. If None, PyWren uses the internally stored futures|


* **Returns**: *Nothing*. It stores 2 different plots in the selected `dst_dir` location.


* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    results = pw.get_result()  # or pw.monitor()
    pw.create_execution_plots('/home/user/pywren_plots', 'test')
    ```
* **Example**:

![Execution Histogram](images/histogram.png?raw=true "Execution Histogram") ![Execution Timeline](images/timeline.png?raw=true "Execution Timeline")


## Executor.clean()
Cleans the temporary data generated by PyWren in IBM COS. This process runs asynchronously to the main execution since PyWren starts another process to do the task.

ibm_cf_executor.**clean**(\*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|local_execution| True | If False, it spawns a function to the cloud to do the clean process |
|delete_all | False | Deletes temporary data from all the executor (Completely cleans the bucket)|


* **Returns**: *Nothing*.

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    results = pw.get_result()
    pw.clean()
    ```
* **Code example**: [map.py](../examples/map.py)

