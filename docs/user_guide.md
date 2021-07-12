# User Guide

1. [Lithops design overview](design.md)

2. [Supported Clouds](supported_clouds.md)

3. High-level Compute and Storage APIs
   - [Futures API](api_futures.md)
   - [Multiprocessing API](api_multiprocessing.md)
   - [Storage API](api_storage.md)
   - [Storage OS API](api_storage_os.md)

4. Execution Modes
   - [Localhost mode](mode_localhost.md)
   - [Serverless mode](mode_serverless.md)
   - [Standalone mode](mode_standalone.md)

5. [Functions design and parameters](functions.md)
   - [Reserved parameters](functions.md#reserved-parameters)
   - [Parameters format for a *single* call](functions.md#parameters-in-the-call_async-method)
   - [Parameters format for a *map* call](functions.md#parameters-in-the-map-and-map_reduce-methods)
   - [Common parameters across functions](functions.md#common-parameters-across-functions-invocations)

6. [Distributed shared objects across function activations](dso.md)

7. [Distributed Scikit-learn / Joblib](sklearn_joblib.md)

8. [Lithops for big data analytics](data_processing.md)
   - [Processing data from a cloud object store](data_processing.md#processing-data-from-a-cloud-object-storage-service)
   - [Processing data from public URLs](data_processing.md#processing-data-from-public-urls)
   - [Processing data from localhost files](data_processing.md#processing-data-from-localhost-files)

9. [Run Lithops on Jupyter notebooks](../examples/hello_world.ipynb)

10. [Execute Airflow workflows using Lithops](https://github.com/lithops-cloud/airflow-plugin)

11. [Lithops end-to-end Applications](https://github.com/lithops-cloud/applications)

12. [Build and manage custom runtimes to run the functions](../runtime/)
