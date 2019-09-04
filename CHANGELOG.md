# Changelog

* New runtime based on Docker images.
* Added IBM Cloud Functions API connector for function invocations.
* Added support for IBM Cloud Object Storage (COS) backend (or S3 API).
* Added support for OpenStack Swift backend (or Swift API).
* Added timeout while PyWren is getting the results. It prevents PyWren waits forever when some function fails and the results are not stored in COS.
* In the COS backend, the *boto3* library was changed to the *ibm_boto3* library.
* Created the ibmcf/default_config.yaml config file for storing the main PyWren configuration parameters such as Cloud Functions and COS access keys.
* Enabled to use PyWren within a PyWren function.
* Enabled redirections. Now it is possible to send a *Future* class as a response of a function. This means that the function has executed another function, and the local PyWren has to wait for another response from another invocation.
* Added a new **map_reduce()**-like method: Unlike the original **map** and **reduce** methods, this new one integrates an automatic data partitioning based on a chunk size provided by the user. Both the **map** and the **reduce** functions are orchestrated and executed within Cloud Functions and the user just waits for the final result provided by the reduce function.
* Automatic data discovering in the new **map_reduce()**-like method. With this method it is possible to specify a bucket name in order to process all the objects within it instead of specifying each object one by one.
* Increased function execution timeout to 600 seconds (10 minutes).
* Created a function which removes residual data from COS when the PyWren execution finishes.
* Changed and improved logging in order to log correctly within IBM Cloud Functions.
* Now the main **executor** is a *class* and not a *method* (see the usage manual for more details).
* All the methods available for the users are integrated within the main *executor class*. In previous versions the user has to import the methods they want to use.
* Added state in the main *executor class* in order to control the correct execution order of its methods (like a turing machine)
* When a new *executor class* is instantiated, it is created a new unique **executor_id** used to store all the objects in COS, and to retrieve the results.
* When a new *executor class* is instantiated, it is created a *storage_handler* used in the all PyWren execution. In previous versions it was created multiple *storage_handlers* for one PyWren execution.
* Now it is possible to specify the **runtime** when the user instantiates the *executor class* instead of changing the config file every time (In the config file is specified the default runtime).
* The **logging level** is now specified when the user instantiates the *executor class* instead of put it in the first line of the code within an env variable.
* The PyWren code which is executed remotely as a wrapper of the function, now uses the main storage handler as the rest of the PyWren code. In previous versions, PyWren creates a new storage client directly with *boto3* library instead of using pywren/storage/storage.py wrapper. 
* Added support for multiple parameters in the functions which are executed remotely as a cloud functions. Previous versions just allows one parameter.
* Eased the usage of the storage backend within a function. By simply specifying *storage_handler* as a parameter of the function, the user will get access to the storage backend.
* Added a new method for retrieving the results of an execution called **fetch_all_resuslts()**. Previous PyWren versions already includes a method called *get_all_results()*, but this is a sequential method and it takes long time to retrieve all the results. It was also included a *wait()* class which is more similar to *get_all_results()* method, the main difference is that the new method is all based on *list the available objects in a bucket*, and it returns when all the tasks are finished. The new method also has the possibility to activate a progress bar in order to track the current status of the execution (really useful for larger executions).
* Added support for libs not included in the IBM Cloud Functions native image (*python-jessie:3*). Some libraries necessary for executing PyWren (remote code) are not included in the native CFs docker image. Now PyWren has the *pywren/libs* dir which includes all of these libraries, so it is possible to use PyWren with the native Docker image instead of building a new one with the missing libraries.