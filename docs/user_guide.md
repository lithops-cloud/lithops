# User Guide

1. [Lithops design overview](source/design.rst)

1. [Supported Clouds](source/supported_clouds.rst)

1. [Execution Modes](source/execution_modes.rst)

1. High-level Compute and Storage APIs
   - [Futures API](api_futures.md)
   - [Multiprocessing API](source/api_multiprocessing.rst)
   - [Storage API](api_storage.md)
   - [Storage OS API](source/api_storage_os.rst)

1. [Lithops Monitoring](source/monitoring.rst)

1. [Functions design and parameters](source/functions.md)
   - [Reserved parameters](source/functions.md#reserved-parameters)
   - [Parameters format for a *single* call](source/functions.md#parameters-in-the-call_async-method)
   - [Parameters format for a *map* call](source/functions.md#parameters-in-the-map-and-map_reduce-methods)
   - [Common parameters across functions](source/functions.md#common-parameters-across-functions-invocations)

1. [Distributed shared objects across function activations](source/dso.rst)

1. [Distributed Scikit-learn / Joblib](source/sklearn_joblib.rst)

1. [Lithops for big data analytics](source/data_processing.rst)
   - [Processing data from a cloud object store](source/data_processing.rst#processing-data-from-a-cloud-object-storage-service)
   - [Processing data from public URLs](source/data_processing.rst#processing-data-from-public-urls)
   - [Processing data from localhost files](source/data_processing.rst#processing-data-from-localhost-files)

1. [Run Lithops on Jupyter notebooks](../examples/hello_world.ipynb)

1. [Execute Airflow workflows using Lithops](https://github.com/lithops-cloud/airflow-plugin)

1. [Lithops end-to-end Applications](https://github.com/lithops-cloud/applications)

1. [Build and manage custom runtimes to run the functions](../runtime/)

1. [Command Line Tool](source/cli.rst)