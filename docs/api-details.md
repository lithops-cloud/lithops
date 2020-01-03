# PyWren API Details

## Executor
The primary object in PyWren is the executor. The standard way to get everything set up is to import pywren_ibm_cloud, and call on of the available methods to get a ready-to-use executor. The available executors are: `ibm_cf_executor()`, `knative_executor()`, `function_executor()`, `local_executor()` and `docker_executor()`

**ibm_cf_executor(\*\*kwargs)**

Initialize and return an IBM Cloud Functions executor object. All the parameters set in the executor will overwrite those set in the configuration.

|Parameter | Default | Description|
|---|---|---|
|config | None | Settings passed in here will override those in pywren_config|
|runtime |  None | Name of the docker image to run the functions |
|runtime_memory | 256 | Memory (in MB) to use to run the functions |
|storage_backend | ibm_cos | Storage backend to store temp data|
|rabbitmq_monitor | False | Activate RabbitMQ monitoring |
|log_level | None | Log level printing (INFO, DEBUG, ...) |
|remote_invoker | False | Spawn a function that will perform the actual job invocation (True/False) |

Usage:
```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor()
```

**knative_executor(\*\*kwargs)**

Initialize and return a Knative executor object. All the parameters set in the executor will overwrite those set in the configuration.

|Parameter | Default | Description|
|---|---|---|
|config | None | Settings passed in here will override those in pywren_config|
|runtime |  None | Name of the docker image to run the functions |
|runtime_memory | 256 | Memory (in MB) to use to run the functions |
|storage_backend | ibm_cos | Storage backend to store temp data|
|rabbitmq_monitor | False | Activate RabbitMQ monitoring |
|log_level | None | Log level printing (INFO, DEBUG, ...) |
|remote_invoker | False | Spawn a function that will perform the actual job invocation (True/False) |

Usage:
```python
import pywren_ibm_cloud as pywren
pw = pywren.knative_executor()
```

**openwhisk_executor(\*\*kwargs)**

Initialize and return an OpenWhisk executor object. All the parameters set in the executor will overwrite those set in the configuration.

|Parameter | Default | Description|
|---|---|---|
|config | None | Settings passed in here will override those in pywren_config|
|runtime |  None | Name of the docker image to run the functions |
|runtime_memory | 256 | Memory (in MB) to use to run the functions |
|storage_backend | ibm_cos | Storage backend to store temp data|
|rabbitmq_monitor | False | Activate RabbitMQ monitoring |
|log_level | None | Log level printing (INFO, DEBUG, ...) |
|remote_invoker | False | Spawn a function that will perform the actual job invocation (True/False) |

Usage:
```python
import pywren_ibm_cloud as pywren
pw = pywren.openwhisk_executor()
```

**function_executor(\*\*kwargs)**

Initialize and return a generic executor object. All the parameters set in the executor will overwrite those set in the configuration.

|Parameter | Default | Description|
|---|---|---|
|config | None | Settings passed in here will override those in pywren_config|
|runtime |  None | Name of the docker image to run the functions |
|runtime_memory | 256 | Memory (in MB) to use to run the functions |
|backend | ibm_cf | name of the compute backend to run the functions |
|storage_backend | ibm_cos | Storage backend to store temp data|
|rabbitmq_monitor | False | Activate RabbitMQ monitoring |
|log_level | None | Log level printing (INFO, DEBUG, ...) |
|remote_invoker | False | Spawn a function that will perform the actual job invocation (True/False) |

Usage:
```python
import pywren_ibm_cloud as pywren
pw = pywren.function_executor()
```

**local_executor(\*\*kwargs)**

Initialize and return a Localhost executor object. This executor runs the functions in local processes. All the parameters set in the executor will overwrite those set in the configuration.


|Parameter | Default | Description|
|---|---|---|
|config | None | Settings passed in here will override those in pywren_config|
|storage_backend | localhost | Storage backend to store temp data |
|rabbitmq_monitor | False | Activate RabbitMQ monitoring |
|log_level | None | Log level printing (INFO, DEBUG, ...) |

Usage:
```python
import pywren_ibm_cloud as pywren
pw = pywren.local_executor()
```

**docker_executor(\*\*kwargs)**

Initialize and return a Docker executor object. This executor runs the functions in local Dockers. All the parameters set in the executor will overwrite those set in the configuration.


|Parameter | Default | Description|
|---|---|---|
|config | None | Settings passed in here will override those in pywren_config|
|runtime |  None | Name of the docker image to run the functions |
|storage_backend | localhost | Storage backend to store temp data |
|rabbitmq_monitor | False | Activate RabbitMQ monitoring |
|log_level | None | Log level printing (INFO, DEBUG, ...) |

Usage:
```python
import pywren_ibm_cloud as pywren
pw = pywren.docker_executor()
```

## Executor.call_async()
Spawn only one function activation.

**call_async**(func, data, \*\*kwargs)

|Parameter | Default |Description|
|---|---|---|
|func | |The function to map over the data |
|data |  |A single value of data |
|extra_env| None |Additional environment variables for CF environment|
|runtime_memory| 256 |Memory (in MB) to use to run the functions|
|timeout| 600 |Max time per function activation (seconds)|
|include_modules| [] |Explicitly pickle these dependencies. All required dependencies are pickled if default empty list. No one dependency is pickled if it is explicitly set to None |
|exclude_modules| [] |Explicitly keep these modules from pickled dependencies. It is not taken into account if you set include_modules |

* **Returns**: One future for each job (Futures are also internally stored by PyWren).

* **Usage**:
    ```python
    futures = pw.call_async(foo, data)
    ```
* **Code example**: [call_async.py](../examples/call_async.py)

## Executor.map()
Spawn multiple function activations based on the items of an input list.

**map**(func, iterdata, \*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|map_function | |The function to map over the data |
|map_iterdata |  |An iterable of input data (e.g python list) |
|extra_params|  None | Additional parameters to pass to each map_function activation |
|extra_env| None |Additional environment variables for CF environment |
|runtime_memory| 256 |Memory (in MB) to use to run the functions |
|timeout| 600 |Max time per function activation (seconds) |
|include_modules| [] |Explicitly pickle these dependencies. All required dependencies are pickled if default empty list. No one dependency is pickled if it is explicitly set to None |
|exclude_modules| [] |Explicitly keep these modules from pickled dependencies. It is not taken into account if you set include_modules |
|chunk_size| None | Used for data_processing. Chunk size to split each object in bytes. Must be >= 1MiB. 'None' for processing the whole file in one function activation|
|chunk_n| None | Used for data_processing. Number of chunks to split each object. 'None' for processing the whole file in one function activation. chunk_n has prevalence over chunk_size if both parameters are set|
|invoke_pool_threads| 500 | Number of threads to use to invoke the functions |



* **Returns**: A list with size  len(iterdata) of futures for each job (Futures are also internally stored by PyWren).

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    ```
* **Code example**: [map.py](../examples/map.py)

## Executor.map_reduce()
Spawn multiple *map_function* activations,  based on the items of an input list,  eventually spawning one (or multiple) *reduce_function* activations over the results of the map phase.

**map_reduce**(map_func, iterdata, reduce_func, \*\*kwargs)

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
|include_modules| [] |Explicitly pickle these dependencies. All required dependencies are pickled if default empty list. No one dependency is pickled if it is explicitly set to None |
|exclude_modules| [] |Explicitly keep these modules from pickled dependencies. It is not taken into account if you set include_modules |
|chunk_size| None | Used for data_processing. Chunk size to split each object in bytes. Must be >= 1MiB. 'None' for processing the whole file in one function activation|
|chunk_n| None | Used for data_processing. Number of chunks to split each object. 'None' for processing the whole file in one function activation. chunk_n has prevalence over chunk_size if both parameters are set|
|reducer_one_per_object| False| Used for data_processing. Set one reducer per object after running the partitioner (reduce-by-key) |
|invoke_pool_threads| 500 | Number of threads to use to invoke the functions |


* **Returns**: A list with size  len(iterdata)  of futures for each job (Futures are also internally stored by PyWren).

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map_reduce(foo, iterdata, bar)
    ```
* **Code example**: [map_reduce.py](../examples/map_reduce.py)

By default, the *reduce_function* is immediately spawned, and then it waits remotely to get all the results from the map phase. It should be note that, although faster, this approach consumes CPU time in Cloud Functions. You can change this behavior and make *reduce_function* to wait locally for the results by setting the `reducer_wait_local` parameter to `True`. However, it has the tradeoff of greater data transfers, because it has to download all the results to the local machine and then upload them again to the cloud for processing with the *reduce_function*.

## Executor.wait()
Waits for the function activations to finish.

**wait**(\*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|fs| None | List of futures to wait. If None, PyWren uses the internally stored futures |
|throw_except | True | Re-raise exception if call raised|
|return_when| 'ALL_COMPLETED' | One of 'ALL_COMPLETED', 'ANY_COMPLETED', 'ALWAYS' |
|download_results| False | Whether or not download the results results while monitoring activations |
|timeout| None | Timeout of waiting for results (in seconds)|
|THREADPOOL_SIZE|  128 | Number of threads to use waiting for results|
|WAIT_DUR_SEC| 1 |  Time interval between each check (seconds) if no rabbitmq_monitor activated |


* **Returns**: `(fs_done, fs_notdone)` where `fs_done` is a list of futures that have completed and `fs_notdone` is a list of futures that have not completed.

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    pw.wait()
    ```
* **Code example**: [wait.py](../examples/wait.py)

## Executor.get_result()
Gets the results from all the function activations. It internally makes use of the `Executor.wait()` method.

**get_result**(\*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|fs| None | List of futures to get the results. If None, PyWren uses the internally stored futures |
|throw_except | True | Re-raise exception if call raised|
|timeout| None | Timeout of waiting for results (in seconds)|
|THREADPOOL_SIZE|  128 | Number of threads to use waiting for results|
|WAIT_DUR_SEC| 1 |  Time interval between each check (seconds) if no rabbitmq_monitor activated |


* **Returns**: If `Executor.call_async()` is called, it returns one result.  If `Executor.map()` is called, it returns a list of results from all the `map_func` calls. The results are returned within an ordered list, where each element of the list is the result of one activation. If `Executor.map_reduce()` is called, it only returns the result of the `reduce_func`.

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    results = pw.get_result()
    ```
* **Code example**: [call_async.py](../examples/call_async.py), [map.py](../examples/map.py), [map_reduce.py](../examples/map_reduce.py)

## Executor.create_execution_plots()
Creates 2 detailed execution plots: A timeline plot and a histogram plot.

**create_execution_plots**(dst_dir, dst_name, \*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|dst_dir|   | Destination directory to store the plots |
|dst_name |   | name-prefix of the plots|
|fs| None | List of futures to plot. If None, PyWren uses the internally stored futures|


* **Returns**: *Nothing*. It stores 2 different plots in the selected `dst_dir` location.


* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    pw.map(foo, iterdata)
    results = pw.get_result()  # or pw.wait()
    pw.create_execution_plots('/home/user/pywren_plots', 'test')
    ```
* **Example**:

![Execution Histogram](images/histogram.png?raw=true "Execution Histogram") ![Execution Timeline](images/timeline.png?raw=true "Execution Timeline")


## Executor.clean()
Cleans the temporary data generated by PyWren in IBM COS. This process runs asynchronously to the main execution since PyWren starts another process to do the task. If `data_cleaner=True` (default), this method is executed automatically after calling `get_result()`.

**clean**(\*\*kwargs)

|Parameter| Default |Description|
|---|---|---|
|fs| None | List of futures to clean temp data. If None, PyWren uses the internally stored futures |
|local_execution| True | If False, it spawns a function to the cloud to do the clean process |

* **Returns**: *Nothing*.

* **Usage**:
    ```python
    iterdata = [1, 2, 3, 4]
    futures = pw.map(foo, iterdata)
    results = pw.get_result()
    pw.clean()
    ```
* **Code example**: [map.py](../examples/map.py)

