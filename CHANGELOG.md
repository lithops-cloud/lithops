# Changelog

## [v3.5.2.dev0]

### Added
- [Core] Added support for python 3.13
- [AWS EC2] Add support for configuring EBS volumes in EC2 lithops workers
- [AWS EC2] Add support for specifying CIDR block in EC2 public subnet

### Changed
- 

### Fixed
- [Standalone] Fixed an issue causing workers to stop prematurely in Consume mode
- [Invoker] Reduced the number of threads used in the async FaaS Invoker
- [Monitoring] Fixed token bucket issue that prevented generating the correct number of tokens
- [Code Engine] Allow to build the default runtime with Python 3.13


## [v3.5.1]

### Fixed
- [Core] Fix issue in "if self._call_output in future.py" for objects with ambiguous truth values
- [Standalone] Consume execution mode failing to run the installation script thus failing all the jobs
- [Azure VMs] Consume execution mode failing to execute jobs


## [v3.5.0]

### Added
- [Singularity] Added new singularity compute backend
- [Oracle Functions] Added support for python 3.11
- [k8s] Added 'master_timeout' parameter to k8s backend
- [AWS Lambda] Added user_tags to the runtime deployment

### Fixed
- [Storage] Fixed "KeyError: 'monitoring_interval'" error when instantiating Storage() class
- [k8s] Fixed bug between threads when there are multiple executions
- [OpenWhisk] Fixed issue in the list_runtimes method
- [OpenWhisk] Fixed runtime name formatting for self hosted container registries


## [v3.4.1]

### Added
- [Localhost] Added error capturing and logging for job/task process failures

### Fixed
- [Worker] Fixed potential issue that can appear during 'func_obj' loading from cache


## [v3.4.0]

### Added
- [CLI] Allow to pass a name in the "lithops runtime list" command
- [Ceph] Added extra region parameter to Ceph backend

### Changed
- [Setup] Moved IBM and AWS deps to lithops[ibm] and lithops[aws] extra
- [Setup] Moved kubernetes and knative deps to lithops[kubernetes] and lithops[knative] extra
- [Setup] Moved minio, ceph and redis deps to lithops[minio], lithops[ceph] and lithops[redis] extra
- [Setup] Moved matplotlib, seaborn, numpy and pandas dependencies to lithops[plotting] extra
- [Setup] Removed unused 'lxml', 'docker' and 'python-dateutil' packages from the setup.py
- [Core] Detached progress bar from INFO logs
- [Future] Exposed 'wait_dur_sec' and 'retries' in future.wait() and future.get_result() methods
- [Localhost] Upgraded localhost backend v2 and set it as the default localhost backend
- [Localhost] Set monitoring_interval to 0.1 in the localhost storage backend
- [AWS Batch] Updated CPU and Memory resource limits

### Fixed
- [AWS Lambda] Fixed wrong AWS Lambda delete runtime_name match semantics 
- [Worker] Fixed potential issue that can appear during 'func_obj' loading from cache
- [Monitor] Fixed potential 'keyerror' exceptions
- [Swift] Fixed OpenStack Swift parameters and authentication by adding domain information
- [AWS Batch] Fixed missing ecsTaskJobRole


## [v3.3.0]

### Added
- [Core] Added a mechanism to automatically retry failed tasks
- [Azure Containers] Automatically login to the container registry if the credentials are in the config

### Changed
- [AWS] Eliminated the need for access and secret keys in the configuration
- [Tests] Moved tests from unittest to pytest

### Fixed
- [AWS Lambda] Fixed runtime deletion with "lithops runtime delete"
- [Localhost] Fixed issue with the job manager
- [Serializer] Fix serialization bug which triggers side effects on dynamic attributes
- [Worker] Removed "distutils" lib imports as it is deprecated in python 3.12
- [Serverless] Allow to build container runtimes with the MacBook Mx chip
- [K8s] Fixed task granularity calculation and memory units issue (RabbitMQ version)
- [AWS Lambda] Fixed AWS Lambda function Name for SSO users
- [AWS] Fixed generated user-key for SSO users
- [Azure VMs] Fixed worker creation and communication


## [v3.2.0]

### Added
- [Lithops] Added support for Python 3.12
- [CLI] Added "--include" parameter in "lithops image build" to allow users upload local files to the VM image

### Changed
- [Standalone] Use redis in the master VM to store all the relevant data about jobs and workers
- [Standalone] Use redis to store the work queues
- [Standalone] Improved resiliency and worker granularity
- [CLI] Show the timestamp in the local timezone format on "lithops job list"
- [CLI] Show worker creation timestamp and time-to-dismantle on "lithops worker list"

### Fixed
- [SSH Cli] Fixed minor error with the "err" variable
- [Cli] Fixed job status on "lithops job list" for standalone backends
- [Standalone] Fixed issue in the "lithops image build" that appears when the vpc is already created
- [Future] Fixed issue with missing 'worker_end_tstamp' variable


## [v3.1.2]

### Added
- [Plots] Allow to set the figure size of the plots
- [Stats] Added new CPU, Memory and Network statistics in the function results
- [IBM VPC] Added a new parameter to enable/disable resource existence check in the platform

### Changed
- [Config] Renamed 'customized_runtime' to 'runtime_include_function'
- [IBM VPC] Increased the total number of available IPs in the private network
- [Standalone] Do not stop the VM immediately after a job in the Consume mode

### Fixed
- [Standalone] Fixed issue that appears when the invocation payload is too big
- [Invoker] Fixed "runtime_include_function" function/modules path
- [AWS EC2] Reset the public IP address of the master VM on stop


## [v3.1.1]

### Added
- [k8s] Added a new way of invoking functions using a RabbitMQ work queue
- [IBM VPC] Added "zone" config parameter
- [IBM Code Engine] Get and print an error message in case of container execution failure 

### Changed
- [OpenWhisk] Updated default runtimes

### Fixed
- [Standalone] Fixed issue with a wrong value of "chunksize"
- [IBM Code Engine] Fixed missing parameter on clean
- [Executor] Fixed potential deadlock in wait() and get_result() when an exception is produced in a function activation


## [v3.1.0]

### Added
- [Cli] Added new 'lithops image delete' command for standalone backends
- [Cli] Added new 'lithops job list' command for standalone backends
- [Cli] Added new 'lithops worker list' command for standalone backends
- [AWS EC2] Added delete_image() method for deleting VM images through the cli
- [IBM VPC] Added delete_image() method for deleting VM images through the cli
- [localhost] New localhost backend v2 to maximize resource utilization when multiple maps are executed from the same FunctionExecutor
- [Standalone] Automatically retrieve the CPU_COUNT from the VM in case worker_processes is not set in config
- [Standalone] Keep track of the worker and job status
- [Storage] Include "Config" parameter to download_file() and upload_file() methods for boto3 related backends
- [Cli] Include 'worker name' in the 'lithops runtime list' cmd
- [AWS Lambda] Created 'namespace' config key to virtually separate worker deployments

### Changed
- [Standalone] Changed default mode of execution from 'consume' to 'reuse'
- [Joblib] Updated the joblib backend to make it compatible with new versions of joblib
- [Joblib] Spawn only one function when 'prefer' is set to 'threads'
- [AWS EC2] Changed default image name from "lithops-worker-default" to "lithops-ubuntu-jammy-22.04-amd64-server"
- [IBM VPC] Changed default image name from "lithops-worker-default" to "lithops-ubuntu-22-04-3-minimal-amd64-1"
- [Serializer] Improve serializer performance when include_modules is set in config
- [SSH Client] Do not raise LithopsValidationError on Authentication failed
- [AWS Lambda] Renamed function name to "lithops-worker-xxxx"

### Fixed
- [Job] Fixed max data size in the invocation payload
- [Multiprocessing] Fixed cpu_count
- [Standalone] Start new workers when the VM instance type changes (in reuse mode)
- [GCP Functions] Fixed issue with "function_url" variable
- [Standalone] Fixed multiple runtime usage at the same time in master VM
- [localhost] Get the correct docker/podman path for jobs that run in a container
- [k8s] Limit the size of the "user" label as the maximum allowed is 63 chars
- [Joblib] Fix shared objects utility when multiple maps run from the same executor
- [Azure VMs] Fix wrong exception when trying to connect to the master VM for the first time
- [Partitioner] Fix partitioner


## [v3.0.1]

### New
- [OCI Functions] Added new 'Oracle Cloud Functions' serverless backend
- [OCI Object Storage] Added new 'Oracle Cloud Object storage' storage backend

### Added
- [Kubernetes] Added Redis server in master pod for shared data between workers
- [Kubernetes] Allow to set "context" and "namespace" in lithops config

### Changed
- [CodeEngine] Create the CE project only when necessary instead of creating it always
- [IBM CF] Create the CF namespace only when necessary instead of creating it always

### Fixed
- [Executor] Fixed kwargs mapping in ServerlessExecutor and StandaloneExecutor
- [Serializer] Fixed issue in serializer when "include_modules" config var is set
- [CodeEngine] Fixed exception handling


## [v3.0.0]

### New
- [Azure Virtual Machines] Added new 'Azure Virtual Machines' standalone backend

### Added
- [Serverless] Added support for python 3.10 and 3.11 runtimes
- [Executor] Allow to set all the compute backend params programmatically in the FunctionExecutor()
- [AWS EC2] Allow to automatically create the VPC and all the necessary resources
- [IBM VPC & AWS EC2] General fixes and Improvements
- [Executor] Allow to pass the config file location in the FunctionExecutor()
- [Storage] Automatically create the storage bucket if not provided in the config
- [IBM] Allow to set "region" under "ibm" section
- [AWS] Allow to set "region" under "aws" section
- [Cli] Added new 'lithops image build' command for standalone backends
- [Cli] Added new 'lithops image list' command for standalone backends
- [IBM VPC] Added build_image() method for automatically building VM images
- [IBM VPC] Added list_image() method for listing the available VM images
- [AWS EC2] Added build_image() method for automatically building VM images
- [AWS EC2] Added list_image() method for listing the available VM images
- [Azure VMS] Added list_image() method for listing the available VM images
- [IBM CF] Automatically create a CF namespace if not provided in config
- [IBM VPC] Added Madrid (Spain) region
- [Code Engine] Automatically create a new project if not provided in config

### Changed
- [Azure] Changed 'location' config parameter to 'region' for compatibility
- [Aliyun] Changed 'endpoint' config parameter to 'region' for compatibility
- [AWS EC2] Reduced number of mandatory parameters
- [AWS] Allow 'region' config parameter instead of 'region_name' for compatibility
- [IBM CF] Cloud-foundry namespaces have been deprecated in IBM Cloud. From now all the users must use an IAM-based namespace
- [IBM COS] Changed 'access_key' config parameter to 'access_key_id' for compatibility
- [IBM COS] Changed 'secret_key' config parameter to 'secret_access_key' for compatibility
- [IBM] Improved token manager
- [Core] Job creation now checks that each element in 'iterdata' is smaller than 8 KB
- [MapReduce] Make 'results' variable name not mandatory in the reduce function signature
- [CLI] Renamed 'lithops test' command to 'lithops hello'
- [CLI] Renamed 'lithops verify' command to 'lithops test'

### Fixed
- [IBM VPC & AWS EC2] Make sure only VMs from the given VPC are removed
- [IBM VPC] Reuse floating IPs for public gateways
- [Serializer] Prevent analyzing the same module multiple times
- [SSH Cli] Fix issue with RSA keys
- [Tests] Fix broken links of testing files
- [Azure Container APPs] Make sure the lithops worker app is deployed
- [AWS Lambda] Fixed error with urllib3. Pin urllib3 to <2 as for now botocore does not support urllib3 2.0
- [Multiprocessing] Check redis connection before starting to submit jobs
- [Redis] Fixed redis backend exception regarding storage_bucket


## [v2.9.0]

### Added
- [AWS S3] Allow to use a public bucket without credentials
- [IBM] Automatically login to the container registry if the credentials are present in config
- [IBM] Force --platform=linux/amd64 in the "lithops runtime build" command
- [k8s] Added boto3 as a dependency of the default runtime
- [IBM VPC] Automatically get the ubuntu image ID
- [IBM VPC] Allowed to reuse floating IPs
- [IBM VPC] Automatically create resources if not provided in config
- [IBM VPC] Added 'region' config parameter
- [Partitioner] Allow wildcards in the object reference

### Changed
- [IBM VPC] Reduced the number of mandatory config parameters
- [IBM VPC] Renamed profile_name config param to worker_profile_name
- [IBM VPC] Renamed ip_address config param to floating_ip

### Fixed
- [AWS EC2] Fix spot instance price
- [Cli] Fix wrong config in the "lithops runtime update" command
- [Standalone] Fix missing private IP address
- [VM] Fix VM standalone backend


## [v2.8.0]

### Added
- [Config] Allow to store the config file in "/etc/lithops/config"
- [CLI] Allow to specify 'memory' and 'version' in the 'lithops runtime delete' command
- [GCP Cloudrun] Allow setting min_workers to the autoscaler
- [GCP Functions] Added https trigger
- [Function Executor] Added additional arguments to pass to the reduce function in map_reduce()
- [AWS] Added session token as optional

### Changed
- [Core] Include function result in the status.json file if it is < 8KB
- [Core] Include python version in the lithops worker name

### Fixed
- [Serverless] Allow to delete runtimes from different lithops versions
- [AWS Batch] Fixed list_runtimes() method
- [localhost] Fixed localhost storage backend head method


## [v2.7.1]

### Added
- [Google Cloud Functions] Added Python 3.10 runtime compatibility
- [Core] Allow to automatically transfer .so (cythonized .py) files if referenced in the code

### Changed
- [Core] Improved cython coverage
- [IBM VPC] Make 'image_id' mandatory in config
- [IBM VPC] Infer zone_name from subnet
- [Knative] Reduced service name length
- [AWS EC2] Updated ec2 default ubuntu image to 22.04

### Fixed
- [IBM VPC] Create floating IP using the specified resource group
- [IBM VPC] Attach floating IP to the subnet
- [Multiprocessing] Fix 'cpu_count' function from multiprocessing API
- [Code Engine] Add CE conflict exception to retriables
- [Core] Show logs from module_dependency.py
- [GCP Functions] Fix runtime_build command
- [Infinispan] Fix Infinispan storage backend
- [Core] Detect a Class if passed as a lithops input function


## [v2.7.0]

### New
- [Azure Container APPs] Added new 'Azure Container APPs' serverless backend

### Added
- [Azure Container APPs] Added new lithops backend for Azure Container APPs
- [Knative] Added Kourier as the networking layer
- [AWS Lambda] Added "env_vars" and "ephemeral_storage" parameters for lambda runtime config
- [Azure Functions] Allow to build a runtime from a custom requirements.txt file
- [K8s] Append 'docker_server' as a prefix of the runtime
- [Code Engine] Append 'docker_server' as a prefix of the runtime
- [Knative] Append 'docker_server' as a prefix of the runtime
- [Google Cloud Storage] Add missing logic in gcp_storage
- [Google Cloud] project_name and service_account are no longer required in config
- [Google Cloud] Allow to use GOOGLE_APPLICATION_CREDENTIALS for service_credentials
- [Google Cloud Run] Allow CPU values <1, 6 and 8
- [Alibaba Cloud Functions] Added Python 3.9 runtime compatibility
- [Alibaba Cloud Functions] Allow to build a runtime from a custom requirements.txt file
- [Core] Add support for building container runtimes with podman
- [Core] Delete only runtimes from the specified backend on 'lithops clean'
- [Executor] Added obj_newline parameter in map() and map_reduce() methods
- [Infinispan] Support DIGEST authentication by default with the Infinispan REST backend

### Changed
- [Core] Load docker command only when needed instead of loading it always
- [Core] Load runtime data only on invocation
- [Google Cloud] project_name and service_account config parameters are no longer required
- [Multiprocessing] Improved remote logging
- [Monitor] Reduce debug log verbosity, status is printed every 30s or when a future changes state
- [AWS Batch] Increased resource limits
- [Executor] Changed 'reducer_one_per_object' parameter to 'obj_reduce_by_key'

### Fixed
- [Google Cloud Functions] Fixed errors when deploying a function
- [Core] Make sure all temp files generated during build_runtime() are cleaned
- [Core] Fix internal partitioner
- [knative] AttributeError: 'KnativeServingBackend' object has no attribute 'coreV1Api'
- [knative] Fixed service deployment
- [Alibaba Cloud Functions] Fixed errors when deploying a function
- [Azure Functions] Fixed errors when deploying a function
- [Azure Functions] Fixed issue that was preventing building runtimes from a non-Linux system
- [Code Engine] Fix runtime_timeout not being applied


## [v2.6.0]

### Added
- [Code Engine] Improved except-retry logic
- [IBM COS] Enables separate IAM authorization for COS and Compute backends


## [v2.5.9]

### Added
- [Core] Add support for Python 3.10
- [Storage] Added `download_file()` and `upload_file()` methods to Storage API to enable multipart upload/download
- [AWS Lambda] Added 'architecture' option in config to allow deploy arm64 runtimes
- [AWS Batch] Added 'service_role' config parameter
- [IBM VPC] add gpu support for ibm_vpc backend
- [Standalone] Added docker login to standalone setup script
- [AWS EC2] Automatically get the default Ubuntu 20.04 AMI when not present in config
- [Code Engine] Added retry logic on connection exception

### Changed
- [CLI] Renamed "lithops runtime create" command to "lithops runtime deploy"

### Fixed
- [AWS Lambda] Fixed "layer builder" function creation necessary to deploy the default runtime
- [AWS Lambda] Allow to create container runtimes whose names contain '.', '/' and '_'.
- [AWS Lambda] List only the runtimes deployed by the current user
- [AWS Lambda] Do not raise an exception if the runtime is already deployed
- [Standalone] Fix cloudinit initialization script
- [Future] Fix host_status_query_count stat
- [Google Cloud Run] Fixed wrong variable name 'runtime_cpus'
- [Google Cloud] Changed docs for Google cloud backend regarding to id instead of name

## [v2.5.8]

### Added
- [Standalone] Raise an exception when the ssh key is not found
- [Standalone] Raise an exception when the ssh key is not valid for login to the mater VM

### Fixed
- [IBM VPC] Fixed get_ssh_client() method that in certain circumstances was not working properly


## [v2.5.7]

### Added
- [AWS Batch] Added AWS Batch backend
- [Standalone] Allow to start workers using a public key instead of using a password
- [Standalone] Added different levels of worker verification
- [Infinispan] Added new Infinispan Hot Rod storage backend

### Fixed
- [Core] Fixed map_reduce jobs
- [Standalone] Fixed internal executions in standalone
- [IBM VPC] Fixed issue that prevented creating workers on create|reuse modes
- [IBM VPC] Fixed issue with ip_address in consume mode
- [AWS Lambda] Allow to delete functions from other lithops versions through 'lithops runtime delete'
- [Core] Fixed FunctionExecutor.plot() when a list of futures is passed to the method
- [Infinispan] Fixes in Infinispan storage backend


## [v2.5.6]

### Added
- [AWS_EC2] Added AWS EC2 Standalone backend
- [AWS_EC2] Allow to start workers using Spot instances in AWS EC2 Standalone backend
- [Standalone] Added the logic to create the missing delta of workers in reuse mode
- [Standalone] Cancel running job tasks on ctrl-c
- [Standalone] New logic to verify that the master VM is correctly setup
- [Standalone] Added new command "lithops attach" that allows to create live ssh connections to the master VM
- [Config] Allow to set monitoring_interval in config

### Changed
- [Standalone] Improved the performance of the master VM when getting the free available workers (reuse mode)

### Fixed
- [Standalone] Fixed VM initial installation script
- [Standalone] Fixed get_workers method on master
- [Standalone] Deleted unnecessary extra worker
- [Standalone] Ensure all workers are properly started on reuse mode
- [Localhost] Fixed storage delete_objects method that was deleting the entire folder of a file
- [IBM VPC] General fixes in IBM VPC backend


## [v2.5.5]

### Added
- [CLI] Allow to pass all available 'docker' parameter to 'lithops runtime build' command
- [Multiprocessing] Add example file with different argument passing examples for Pool and Process

### Fixed
- [Localhost] Fixed minor issue when deleting completed jobs
- [Multiprocessing] Fixed args mismatch error when passing list of tuples to Pool.map
- [Standalone] Fixed cloud-init script that occasionally fails to set ssh credentials


## [v2.5.4]

### Fixed
- [Standalone] Avoid deleting the master VM on consume mode


## [v2.5.3]

### Fixed
- [Core] Fixed lithops.map_reduce() jobs. Sometimes jobs where not finishing
- [Core] Spawn lithops.cleaner only once in the same execution instance
- [Tests] Fix when running 'lithops verify' command
- [CodeEngine] Delete jobruns and configmaps of internal executions
- [k8s] Delete job definitions of internal executions
- [Core] Ensure all temp data is cleaned from storage backend


## [v2.5.2]

### Added
- [Core] Allow to spawn the reduce function in map_reduce() after a configurable percentage of completed map activations

### Changed
- [Config] 'max_workers' and 'worker_processes' keys must be set at backend level in config
- [Config] 'remote_invoker' key must be set at backend level in config
- [Config] 'customized_runtime' key must be set at lithops level in config
- [Config] 'serverless' section in config is no longer required

### Fixed
- [CodeEngine] Fixed 'max_workers' parameter to limit the number of max workers per map invocation
- [IBM CF] Create the runtime if not deployed when invoked
- [Localhost] Fix localhost paths for windows hosts


## [v2.5.1]

### Added
- [Localhost] Stop containers on ctrl-c

### Changed
- [Localhost] Start container with user's uid:gid
- [Localhost] Extended default execution timeout to 3600 seconds

### Fixed
- [Standalone] Fixed standalone execution on consume mode
- [Aliyun FC] Fixed Aliyun Function compute backend
- [Core] Fixed 'lithops runtime build' command when the backend is not configured in config


## [v2.5.0]

### Added
- [CLI] Add new command in cli to list deployed runtimes
- [Standalone] Add reuse mode that allows to reuse the same VMs for all the maps
- [Config] Allow to configure worker_processes parameter in serverless and standalone sections
- [Localhost] Prevent multiple jobs in the same executor to run at the same time
- [Standalone] Prevent multiple jobs submitted to the same master VM to run at the same time
- [CE] Added COS Direct endpoints for free bandwidth from/to CodeEngine

### Changed
- [Core] worker_processes parameter has been moved from map() to FunctionExecutor()
- [CE] Deleted docker naming restrictions in CE and k8s backends
- [CLI] Prevent loading storage config when using 'lithops runtime build' command
- [AWS Lambda] Moved layer build to a lambda, solves OS related errors when compiling libraries
- [AWS Lambda] Adjusted new memory configurations (128 MB minimum and removed 64 MB increments check)
- [AWS Lambda] Add support for Python3.9
- [Standalone] ssh VM password is now a 37 chars random and dynamic password (for create and resue modes)

### Fixed
- [CE] Create a new token when it expires after 20 minutes when using the same FunctionExecutor
- [CE] Prevent exception when detecting the docker username in k8s and CE backends
- [Core] Fix minor issue in jobrunner
- [AWS Lambda] Fixed aws config max timeout check
- [Standalone] Fixed issue that prevents to run multiple maps() with the same FunctionExecutor (create mode)

## [v2.4.1]

### Fixed
- [IBM VPC] Fixed a data inconsistency on consume mode

## [v2.4.0]

### Added
- [Storage] Added MinIO storage backend
- [Core] Allow to pass function args as part of the invocation payload in FaaS backends
- [Core] Optimize call_async() calls with an internal function caching system
- [AWS Lambda] New invoke method that reduces total invocation time
- [Core] Allow to set the bucket name at storage backend level in config
- [localhost] stop running jobs processes on ctrl-c or exception
- [AWS S3] Added region_name parameter in config

### Changed
- [Core] Improved performance and efficiency of the lithops cleaner background process
- [AWS Lambda] Use layer from Klayers API for pre-compiled Amazon Linux numpy binaries
- [Core] Moved invoke_pool_threads param from map and map_reduce calls. Now it must be set at backend level in config

### Fixed
- [Localhost] Fixed error when processing localhost objects
- [Localhost] Allow to create a localhost storage instance when a config file exists with a cloud configuration
- [Core] Fixed an unusual inconsistency in configuration between 'backend' and 'mode' parameters
- [Core] Fixed customized_runtime feature
- [Core] Fixed get_result() execution after wait() when throw_except is set to False
- [Core] Fixed internal executions
- [Core] Fixed 'lithops storage list' CLI when a bucket is empty
- [Standalone] Fixed execution


## [v2.3.5]

### Added
- [Core] Add function chaining pattern in the Futures API
- [Core] ob.data_stream is now also an iterator when using the partitioner
- [AWS Lambda] Add 'account_id' parameter in config (used if present instead of querying STS).
- [k8s] Allow to set the maximum number of parallel workers
- [Localhost] Allow the partitioner to process local directories

### Changed
- [Core] Add 'key' and 'bucket' attrs in localhost partitioner for compatibility with OS
- [Serverless] runtime, runtime_memory and runtime_timeout can only be set at backend level

### Fixed
- [Standalone] Fix execution
- [Core] Avoid loading the config file twice

### Deleted
- [AWS Lambda] Using custom layer runtimes for AWS Lambda due to layer size limitations.

## [v2.3.4]

### Added
- [Core] Allow to execute a Class as lithops function
- [CE] Allow to to run code engine without kubecfg file
- [CE] Allow private container registries
- [k8s] Allow private container registries
- [knative] Allow private container registries
- [Localhost] Allow the partitioner to process local files
- [joblib] Added `joblib` entry in extras_require for joblib backend dependencies

### Changed
- [CE] CPU and memory values must match predefined flavors
- [multiprocessing] Improved nanomsg Pipe implementation
- [joblib] Optimized joblib backend (concurrent args data upload/download)

### Fixed
- [Core] Fixed module analyzer
- [Core] Clear only present jobs instead of all after wait() or get_result()
- [multiprocessing] Fix put/get slice to/from mp.Array or mp.RawArray


## [v2.3.3]

### Fixed
- [Core] Allow to execute class methods as lithops function


## [v2.3.2]

### Added
- [Core] New "warm_container" and "func_result_size" in future statistics
- [Core] New logic to detect referenced modules/libs

### Changed
- [Core] New monitoring system
- [Core] Deleted strong dependency to pika==0.13.1

### Fixed
- [Partitioner] Fixed partitioner when obj url contains more than one subfolder
- [Cli] Fixed serverless runtime lifecycle methods

### Deleted
- [Core] Removed cloudpickle from lithops.libs


## [v2.3.1]

### Added
- [Core] Allow Support for Python 3.9
- [Core] Added standalone get_result() and wait() methods
- [knative] Include GCP and Azure storage libs into default knative runtime
- [CodeEngine] Enable internal kubernetes pod executions
- [k8s] Enable internal kubernetes pod executions
- [Cli] Added 'empty' function to storage cli to empty a bucket
- [Core] Added new method to FunctionExecutor() to calculate execution costs
- [IBM CF] Added formula to calculate execution costs
- [Multiprocessing] Added Nanomsg connection type for addressable backends
- [Multiprocessing] Added expiry time for Redis multiprocessing resources
- [Multiprocessing] Added Listener and Client for multiprocessing using Redis
- [Azure Functions] Added support for http trigger
- [Core] Set lithops to localhost mode when config files is empty

### Changed
- [IBM CF] Change user_key to API-key pass instead of user
- [Azure] Changed configuration keys
- [Core] Improved worker when chunksize is set to values > 1
- [Core] Check lithops version mismatch in host instead of in worker

### Fixed
- [Core] Overwrite the runtime set in config with the runtime set in the FunctionExecutor
- [Cli] Fixed --config param in lithops cli
- [Standalone] Fixed internal executions
- [Core] Fixed rabbitmq monitor when get_result() is called after wait()
- [GCP Storage] Fix GCP Storage backend put obj as stream
- [GCP Functions] Improved runtime create time
- [Azure blob] Fix in azure blob get method
- [Azure Functions] Fix build runtime command


## [v2.3.0]

### Added
- [Core] Added multiprocessing support in workers
- [Core] Added 'cunksize' param to API calls
- [Core] Added 'worker_processes' param to API calls
- [Core] Allow a worker to process more than one call trough 'chunksize' param
- [Core] All Functions logs are now synchronized with the client
- [Config] Allow 'log_level' and 'log_format' keys in configuration
- [Config] Allow 'log_stream' and 'log_filename' keys in configuration
- [Config] Allow 'runtime' being configured at serverless backend level
- [Config] Allow 'invoke_pool_threads' being configured at serverless backend level
- [Multiprocessing] Added generic Manager 
- [Kubernetes] Add kubernetes job backend
- [CLI] Extended lithops cli with storage put, get, delete and list options
- [Azure] Added missing azure functions backend methods

### Changed
- [Core] Improved Standalone execution mode
- [Core] Renamed utils.setup_logger() method to utils.setup_lithops_logger()
- [Core] Renamed partitioner 'chunk_size' param to 'obj_chunk_size'
- [Core] Renamed partitioner 'chunk_n' param to 'obj_chunk_number'
- [GCP Cloud Run] Refactor backend, removed 'gcloud' CLI calls.
- [IBM VPC] Improved IBM VPC backend
- [AWS Lambda] Lambda layer modules update

### Fixed
- [Multiprocessing] Fix issues related to Pipes and Queues
- [Multiprocessing] Fix multiprocessing.context methods
- [CodeEngine/knative] Fix getting docker username in MAC OS hosts


## [v2.2.16]

### Fixed
- [Code Engine] Fixing code engine docker image


## [v2.2.15]

### Added
- [Joblib] Joblib backend upgraded
- [AWS Lambda] Support for container-based runtimes
- [AWS Lambda] Support for running functions in a VPC
- [AWS Lambda] Support for attaching EFS volumes
- [Core] Added cloudpickle, tblib and ps-mem deps as requirement of the runtimes
- [Core] Add a new Serverless mode that allows to include the function within the runtime

### Changed
- [Core] Allow Standalone mode to start 1 VM per activation

### Fixed
- [Core] Fixed issue in clean when it is called between wait and get_result
- [Core] Fixed multiprocessing Queue and get_context
- [Core] Fixed multiprocessing args mapping in map and map_async
- [Localhost] Fixed issue when using docker images in Windows or MAC

### Deleted
- [Core] Removed tblib from lithops.libs
- [Core] Removed ps-mem from lithops.libs

### Required actions
- Run: python3 -m pip install -U cloudpickle tblib ps-mem ibm-vpc namegenerator


## [v2.2.14]

### Added
- [Azure] Azure Functions backend upgraded
- [Azure] Azure blob backend upgraded
- [Alibaba] Alibaba Functions backend upgraded
- [Alibaba] Alibaba Storage backend upgraded
- [Localhost] Support passing file-like objects to put_object
- [Localhost] Support head_bucket and head_object storage operations

### Changed
- [Core] Moved tests.py script to 'scripts' folder

### Fixed
- [Core] Fixed Storage API error when no config is provided
- [Core] Fixed expired IAM token in IBM CF during an execution
- [Core] Minor fixes in multiprocessing API
- [Core] Fixed executor logging
- [Core] Fixed issue in cleaner between wait and get_result
- [CodeEngine] Fixed issue getting region
- [Localhost] Fixed empty parent directory deletion when deleting objects
- [Localhost] Made list_keys/list_objects behavior consistent with other backends


## [v2.2.13]

### Added
- [CodeEngine] Compatible runtimes between knative and CE
- [CodeEngine] runtime name regex verification
- [CodeEngine] Added clear() method to delete all completed jobruns
- [Standalone] Append installation logs into /tmp/lithops/proxy.log

### Changed
- [Localhost] Run functions in processes instead of threads in Windows
- [CodeEngine] Reduced payload size
- [Core] Updated logging

### Fixed
- [Core] Fixed Cloudpickle 1.6 modules detection
- [Core] Added tblib.pickling_support in the local machine


## [v2.2.11]

### Changed
- [CodeEngine] Delete runtime name regex verification


## [v2.2.10]

### Added
- [Core] Allow to create a Storage() class from config file
- [CodeEngine] Improved codeengine backend

### Changed
- [Core] Improved multiprocessing API
- [Core] Improved Storage OS API


## [v2.2.9]

### Fixed
- [CodeEngine] Fixed CodeEngine runtime entrypoint


## [v2.2.8]

### Fixed
- [Core] Fix "lithops runtime create" cli
- [Core] Fixed missing executor_id variable in jobrunner


## [v2.2.7]

### Added
- [Core] Add joblib backend for scikit-learn
- [Cli] Add more config parameters in lithops cli
- [IBM COS] Add 'region' config param
- [Knative] Add 'min_instances', 'max_instances' and 'concurrency' config params

### Fixed
- [Core] Fix job monitoring on Windows hosts
- [Knative] Minor fix when using knative from master branch
- [GCE] Fix in 'lithops runtime' cli
- [Core] Minor fix in tests
- [Core] Fixed data partitioner


## [v2.2.5]

### Fixed
- [Core] Fixed issue in serverless config
- [Core] Fixed issue in localhost storage backend
- [Code Engine] Fixed issue in code engine backend

## [v2.2.4]

### Added
- [Core] New 'lithops logs' command
- [Core] New job cleaner process

### Changed
- [Core] localhost/standalone logging per job-id
- [Core] Updated tblib to 1.7.0
- [Core] Updated ps_mem lib
- [Core] Standalone logic to ssh

### Fixed
- [Core] Fixed issue in localhost executor and Mac OS
- [Core] Fixed issue in localhost storage backend


## [v2.2.3]

### Added
- [Core] Cloudpickle 1.6.0 for python>=3.8
- [Core] Multiprocessing API
- [Core] Added "--mode" option in tests
- [Core] Sync standalone function logs into a local file

### Changed
- [Core] Improved localhost/standalone logging
- [Core] Allowed to run lithops without configuration

### Fixed
- [Core] Fixed some issues in localhost executor logic


## [v2.2.2]

### Fixed
- [Core] Prevent lithops waiting forever for the proxy ready
- [Core] Multiprocessing invoker in MAC OS
- [Knative] Istio endpoint issue in knative backend


## [v2.2.1]

### Changed
- [Core] Improved standalone executor logic
- [Knative] Updated apiVersion to v1
- [Knative] Updated default python3.8 Dockerfile

### Fixed
- [Core] Fixed runtime_memory param in API calls
- [Core] Raise fn exceptions immediately when produced
- [Core] Raise exceptions during fn invocation
- [IBM COS] Get tokens for IAM API key and COS API Key
- [AWS Lambda] Fixes in Lambda compute backend


## [v2.2.0]

### Added
- [Core] New ServerlessExecutor
- [Core] New StandaloneExecutor
- [Core] New LocalhostExecutor
- [Core] New StandaloneExecutor logic
- [Core] New LocalhostExecutor logic
- [Core] New Standalone invoker logic
- [Core] New Localhost invoker logic

### Changed
- [Core] Changed some main keys in configuration


## [v2.1.1]

### Changed
- [CodeEngine] Improved Code engine backend


## [v2.1.0]

### Added
- [Core] Google Cloud Functions & Storage backends
- [Core] Azure Functions & Blob Storage backends
- [Core] AWS Lambda & AWS S3 backends
- [Core] Alibaba Aliyun Functions & Object Storage backends
- [Core] IBM Code Engine Compute backend


## [v2.0.0]

### Changed
- [Core] Rebranding to LITHOPS


## [v1.7.3]

### Added
- [Core] Generic compute client logic
- [Core] IBM IAM service client lib
- [Core] IBM VPC service client lib
- [Docker] Docker backend compatible with IBM VPC VM 

### Changed
-  [Docker] Improved Docker executor

### Fixed
-  [Ceph] Fix in Ceph endpoint



## [v1.7.2]

### Added
- [GCR] Added Google Cloud Run Backend


### Changed
- [Core] Improved Storage abstraction
- [Core] InternalStorage uses storage abstraction

### Fixed
- [Core] Fixed invoker token bucket when quota limit is reached
- [Core] Fixed logging
- [Core] Fixed invoker when it reaches quota limit
- [Core] Fixed delete cloudobject
- [Localhost] Fixed invocations ability to launch subprocesses
- [Docker] Fixed docker running as user and not root

## [v1.7.0]

### Added
- [GCS] Added Google Cloud Storage Backend
- [Knative] Configurable CPU parameter

### Fixed
- [Core] Fixed issue in extra_args when iterdata is a dict
- [Core] Fixed CloudObjects keys collisions
- [Core] Fixed case where function argument is a list or tuple


## [v1.6.0]

### Added
- [Core] New docker_executor()
- [Ceph] New Ceph Storage backend

### Changed
- [Core] Moved all stats from 'f._call_status' to a new 'f.stats' variable
- [Core] Bump httplib2 from 0.13.0 to 0.18.0
- [Localhost] Improved localhost storage backend

### Fixed
- [Core] Fixed issue in pw.clean(cs=cobjs) when passing a large list of cobjs


## [v1.5.2]

### Added
- [Core] Added 'data_limit' config param in pywren section
- [Core] Added context-manager-like executor and example
- [Core] Added debug mode in tests with '-d' flag
- [Core] Added delete_cobject() and delete_cobjects() storage methods

### Changed
- [Core] Reducer logic moved to jobrunner
- [Core] cloudobject methods moved from internal_storage to ibm_cos
- [Core] renamed cloudobject put method from 'put_object' to 'put_cobject'
- [Core] renamed cloudobject get method from 'get_object' to 'get_cobject'
- [Core] 'internal_storage' func param renamed to 'storage'
- [Core] pw.clean method can now clean cloudobjects
- [Knative] Set default Knative runtime timeout to 10 minutes
- [Knative] Added more debug logs in Knative
- [Knative] Enabled building default knative runtime locally

### Fixed
- [Core] Fixed issue in map_reduce() method
- [Core] Fixed issue in plot() method when using numpy 1.18.1
- [Core] Fixed issue in cloudpickle when iterdata contains complex objects
- [Core] Fixed issue with extra_env vars passed to functions
- [Core] Fixed issue in memory monitor
- [Core] Fixed issue in pywren-ibm-cloud cli
- [Core] Fixed issue when wait()/get_result() methods are called multiple times
- [Core] Fixed minor issue with ps_mem module in windows hosts
- [Knative] Fixed knative to pass all tests
- [Knative] Fixed remote_invoker in knative
- [Knative] Fixed issue when pywren version mismatch in Knative
- [Knative] Fixed issue in Knative when the default runtime is built
- [knative] Fixed building default runtime based on current python version
- [knative] Fixed OOM exceptions from knative to be correctly raised
- [IBM COS] Fixed issue when using local_executor with IBM COS authorized by an api_key


## [v1.5.1]

### Changed
- [Core] pw.create execution_plots() renamed to pw.plot()
- [Core] Docs updated

### Fixed
- [Core] Fixed internal issues
- [knative] Fixed minor issue in knative


## [v1.5.0]

### Added
- [Core] Added support for Python 3.8
- [Core] Added memory monitor

### Changed
- [Core] Updated knative to work for new releases
- [Core] Updated tblib from 1.4.0 to 1.6.0
- [Core] Changed get_current_memory_usage() to get_memory_usage()
- [Core] pywren-runtime client is now called pywren-ibm-cloud

### Fixed
- [Core] Fixed issue with internal partitioner
- [Core] Fixed issue with get_result()
- [Core] Fixed issue with windows hosts
- [Core] Some other Internal fixes


## [v1.4.2]

### Added
- [Core] Prevent get_result() to wait forever when using COS
- [Core] Added more debug logs
- [Infinispan] Infinispan storage backend

### Changed
- [Core] Reduced the number of COS clients created in each function activation

### Fixed
- [Core] Fixed internal issue with storage
- [Core] Fixed future exception handling
- [Core] Some other Internal fixes


## [v1.4.1]

### Added
- [Core] Prevent get_result() to wait forever when using RabbitMQ
- [knative] Added new Dockerflies for knative

### Changed
- [Core] Changed way to raise function exceptions
- [Knative] Changed way to build custom runtimes for knative
- [IBM CF] COS private_endpoint is now mandatory if using IBM CF

### Fixed
- [Knative] Fixed knative when it creates a runtime based on an already built image
- [Core] Fixed throw_except parameter on wait() and get_result()
- [Core] Some other Internal fixes


## [v1.4.0]

### Added
- [Core] New way to create RabbitMQ resources

### Changed
- [Core] Default invoker background processes set to 2
- [Core] Code refactoring

### Fixed
- [Core] Fixed issue when config in runtime is used multiple times
- [Core] Fixed invoker stop() method
- [Core] Some other Internal fixes


## [v1.3.1]

### Added
- OpenWhisk Compute backend
- openwhisk_executor()
- Allowed multiple users in same CF namespace
- Added IBM COS request retrying when ReadTimeoutError

### Changed
- COS token will expire 10 minutes before
- CF IAM token will expire 10 minutes before
- Improved remote invoker
- Reraise exception from functions
- Docs updated
- Default runtime timeout set to seconds
- default function timeout set to 595 secs

### Fixed
- Fixed new invoker usage in notebooks
- fixes in knative backend
- Some other Internal fixes


## [v1.3.0]

### Added
- New invoker mechanism
- New native remote invoker for ibm_cf
- pywren-runtime clean command to delete all tmp data
- capacity to limit the number of concurrent workers
- architecture documentation

### Changed
- Changed Internal data cleaner logic to delete only desired job
- Updated ibm_cf Dockerfiles
- Moved chunk min size from 1MB to 0MB
- changed executor id format
- Timeout waiting for functions to complete set to None by default
- Updated ibm_cf base image requirements

### Fixed
- Internal fixes
- Fixed tests
- Fixed pywren inside pywren function executions


## [v1.2.0]

### Added
- New local_executor() to run pywren jobs in the local machine
- New localhost compute backend
- New localhost storage backend
- New docker_executor() to run pywren jobs in the local machine by using docker
- New docker compute backend

### Changed
- Docs updated
- Code refactor

### Fixed
- Internal fixes
- Bump pillow from 5.4.1 to 6.2.0


## [v1.1.1]

### Added
- Allowed partitioner to split files by a number of chunks
- Missing logic in knative backend

### Changed
- Docs updated

### Fixed
- Internal fixes


## [v1.1.0]

### Added
- Added knative-serving compute backend
- Added Dockerfile skeleton for slim Python3.6 runtime (only 307MB)
- Added CACHE_DIR in ~/.pywren/cache
- knative_executor() and function_executor()
- support to work on multiple regions at a time

### Changed
- Docs updated
- Runtime Dockerfiles updated
- Runtime requirements updated
- Updated Cloudpickle lib to version 1.2.2
- Parameters introduced in the executer now overwrite the config
- updated tests

### Fixed
- Internal logic to generate runtime_metadata
- invalid call to "is_remote_cluster" method
- Cloudpickle lib to accept any kind of import
- include_modules option in serializer


## [v1.0.20]

### Added
- Storage abstraction for data partitioner
- Added 'extra_params' arg to map() and map_reduce() calls
- Logic to reuse IAM API Key tokens during 1 hour
- More debug logging

### Changed
- Docs updated
- Full support for Python3.5

### Fixed
- Fixed minor issue in config
- Fixed possible issue extracting metadata from large docker images (runtimes)


## [v1.0.19]

### Added
- Added 'obj' as an optional arg for the functions when a user wants to process objects from OS
- Added 'rabbitmq' as an optional arg for the functions
- Added 'id' as an optional arg for the functions
- Added rabbitmq example

### Changed
- Deleted 'bucket' 'key' 'data_stream' function args in favor of 'obj'
- Internal improvements related data partitioning
- Changed create_timeline_plots() method name to create_execution_plots()
- Docs updated
- updated notebooks
- Upgrade cos-sdk Python module version

### Fixed
- Fixed tests
- Fixed CVE-2019-12855 security alert


## [v1.0.18]

### Added
- Added CloudObject abstraction
- Added CloudObject example
- Restored OOM exception
- Allowed to get_results when rabbit monitoring is activated
- Allowed rabbimq to monitor multiple jobs at a time
- Statuses returned from rabbitmq to futures

### Changed
- Code refactoring about compute abstraction
- Reorganized libs folder
- Updated cloudpickle lib from 0.6.1 to 1.2.1
- Updated glob2 lib to 0.7
- Updated tests
- Modified job_id format

### Fixed
- Fixed minor issue listing CF actions
- Fixed issue when executing pywren inside pywren
- Fixed possible issue with invalid config parameters
- Fixed wrong method name: build_runtime()
- Fixed internal_storage parameter in partitioner
- Fixed crete_timeline_plots method according recent changes


## [v1.0.17]

### Changed
- Code refactoring about compute abstraction

### Fixed
- Fixed issue with invocation retries


## [v1.0.16]

### Added
- Added missing init file
- Allowed 'clean=all' arg in clean() method

### Changed
- Simplified invoker
- Moved compute and storage classes to separate files
- Deleted unnecessary files
- Close plots on finish
- Code refactoring about compute abstraction

### Fixed
- Fixed broken readme links
- Fix in invocation method


## [v1.0.15]

### Added
- Added log information
- Added init files
- Store runtime_metadata into a local cache in order to reduce exec time

### Changed
- Modularized Invoker
- Changed some variable names
- Docs updated

### Fixed
- Fixed set_memory in invoker
- Fixed unneeded memory usage
- Fixed none finished futures
- Fixed wait method
- Fixed issue with map_reduce()


## [v1.0.14]

### Added
- Pywren runtime deployment as script
- Changed name of the runtime deployment script
- Added 'pywren_runtime clean' option
- Added function_name and runtime_memory to future's status
- Added 'pywren_runtime update all' option
- Added exception when preinstalled modules list is not well provided
- Add package parameter to delete function

### Changed
- Improved sending execution statuses through rabbitmq
- Improved exception management
- Moved some logs to debug
- Improved runtime deployment script
- Changed logic order of the create_timeline_plots method

### Fixed
- Preventing false out-of-memory error
- Fixed issue when using rabbitmq to monitor executions
- Fixed issue tracking map_reduce execution with progressbar
- Some other fixes


## [v1.0.13]

### Changed
- match create_timeline_plots() to rabbitmq feature

### Fixed
- Fixed possible issue deploying runtime
- Fixed jobrunner logs
- Fix in url paths
- Some other fixes


## [v1.0.12]

### Changed
- Moved ibm_iam lib from tornado to requests package
- Minor change create_timeline_plots()

### Fixed
- Map futures before reduce wont be downloaded
- Fix in cf_connector
- Fix in tests
- private endpoint fix
- Some other fixes


## [v1.0.11]

### Added
- Support for IBM IAM authentication for IBM CF and IBM COS
- Take into account cf_region and cf_namespace in runtime_name

### Changed
- Improved invocation speed
- Improved runtime deployment
- Minor improve get_result()
- Moved 'create action name' logic to utils
- Change map_reduce to return also map futures
- Improved remote_invocation mechanism
- Moved cf_connector to libs

### Fixed
- Fixed deploy_utils script
- Some other fixes


## [v1.0.10]

### Added
- Add support to create pywren's plots in cos

### Fixed
- Fixed future status
- Fixed wait method
- Fixed minor issues in plots.py and wren.py
- Clarified when future is ready or done
- Some other fixes


## [v1.0.9]

### Added
- Added COS private_endpoint parameter
- added external config support for tests' executors
- Added exceptions management in monitor() method

### Changed
- integrated test file into PyWren
- Tuned-up some parameters
- Send jobrunner config through a parameter
- docs verify section update
- moved test call outside of wren.py

### Fixed
- Fixed issues when PyWren is used from a Windows host
- Fixed issue with 'signal' module on Windows hosts
- Check token timestamp of COS


## [v1.0.8]

### Added
- Added connection timeout on COS to avoid possible issues

### Fixed
- Fixed possible issue when calling future.result()
- Some other fixes


## [v1.0.7]

### Added
- Runtimes automatically created

### Changed
- Improved Runtime management
- Improved performance of jobrunner
- Updated notebooks
- Restored .gitignore
- Docs updated

### Fixed
- Some minor fixes


## [v1.0.6]

### Added
- Enabled memory configuration in the executor

### Changed
- Docs updated

### Fixed
- Fix issue in cf_connector
- Some other fixes


## [v1.0.5]

### Added
- log_level propagated to functions
- added an option to get debug logs from boto3
- Support for configurable IAM endpoint
- added chunk_size tests

### Changed
- Project structure refactor
- Modified create_zip_action method
- Docs updated
- Improved runtime deployment
- improved 'bucket' parallelism in partitioning
- Removed annoying info prints

### Fixed
- Fix function name
- Fixed issue in cf_connector when running PW from Windows
- Fix issue with log_level
- Fixed issue with white spaces when deploying a runtime


## [v1.0.4]

### Added
- Added rabbitmq logic
- Added is_notebook method
- Added wrapper to data_stream for partitioned data
- Created WrappedStreamingBodyPartition() class for data partitions
- Run multiple maps() in the same executor
- added multiple execution on the same executor tests
- added ibm_cos tests
- Added download_results parameter in monitor() method to ensure all results are downloaded
- Added pika package to dependencies
- Tracking new futures from a function
- Example of Docker image for dlib

### Changed
- Change name of wait() method to monitor()
- Tuned up some parameters to speedup wait method
- Moved all partitioner logic into partitioner.py
- Installation script to support PW version as a parameter
- Changed way to get last row position on data partition
- Deleted duplicated get_result method
- Hide urllib3 annoying debug logs within functions
- Activate remote_invocation when data comes from COS
- Docs updated

### Fixed
- Fixed partitioner data wrapper
- Fix tests to work with last partitioner update
- Fixed chunk threshold
- Fix printing plots
- Fixed rabbitmq config
- Some other fixes


## [v1.0.3]

### Added
- Add support to generate execution timeline plots
- pi_estimation_using_monte_carlo_with_PyWren.ipynb
- stock_prediction_monte_carlo_with_PyWren.ipynb
- Added missing modules in setup.py
- Added memory usage in action logs

### Changed
- Reverted cloudpickle usage
- Move default action memory to 512MB
- Improved installation script
- Refactored deploy_runtime script
- Updated deploy_runtime script, clone command
- Docs updated
- Finished map() and map_reduce() consistency issue
- Raise exception when some activation fails

### Fixed
- Fixed issue reusing COS tokens
- Fixed partitioner object split
- Fixed map() and map_reduce() consistency issue
- Some other fixes


## [v1.0.2]

### Added
- ibm_boto3 client as an input of the parameter 'ibm_cos' of the function
- Add functional test script
- Added retry logic
- Invoker logic
- Added missing init file
- Added user agent to identify pywren
- Added missing dependencies

### Changed
- Abstracted COS logic for map() and map_reduce() methods
- pw.map() method through COS abstractions
- Retry mechanism when exception
- Use CloudPickle module in all project for serializing/unserializing
- Docs updated
- Storage separation
- Project update. 'bx' and 'wsk' CLI tools are no longer necessary
- Updated setup.py 
- Deleted requirements.txt 
- Updated default_preinstalls

### Fixed
- Minor warnings fix
- Fixed logging
- step back with gevent until import fixed in openwhisk
- Fixed issue when running map_reduce job from COS keys
- Fixed issue retrieving results
- Fixed issue when processing a dataset from url
- Fixed issue when running map_reduce method
- Some other fixes


## [v1.0.1]

### Added
- Example of the Docker image that is based on Anaconda
- Enabled support for multiple call_assync() calls in the same pw instance
- Added 'OutOfMemory' Exception
- Jupyter notebook example
- configurable cleaner for temporary data

### Changed
- Changed and improved logging in order to log correctly within IBM Cloud Functions
- Changed Python interpreter of the data_cleaner method
- Moved some info prints to debug
- improved remote function invocation mechanism

### Fixed
- Fixing flask security issues CVE-2018-1000656
- Fixed minor issue when futures is not a list
- Fixed default config exception. API KEY is not mandatory.
- Fixes in logging
- Some other fixes


## [v1.0.0]
First release.

- New runtime based on Docker images.
- Added IBM Cloud Functions API connector for function invocations.
- Added support for IBM Cloud Object Storage (COS) backend (or S3 API).
- Added support for OpenStack Swift backend (or Swift API).
- Added timeout while PyWren is getting the results. It prevents PyWren waits forever when some function fails and the results are not stored in COS.
- Created the ibmcf/default_config.yaml config file for storing the main PyWren configuration parameters such as Cloud Functions and COS access keys.
- Enabled to use PyWren within a PyWren function.
- Enabled redirections. Now it is possible to send a *Future* class as a response of a function. This means that the function has executed another function, and the local PyWren has to wait for another response from another invocation.
- Added a new **map_reduce()**-like method: Unlike the original **map** and **reduce** methods, this new one integrates an automatic data partitioning based on a chunk size provided by the user. Both the **map** and the **reduce** functions are orchestrated and executed within Cloud Functions and the user just waits for the final result provided by the reduce function.
- Automatic data discovering in the new **map_reduce()**-like method. With this method it is possible to specify a bucket name in order to process all the objects within it instead of specifying each object one by one.
- Created a function which removes residual data from COS when the PyWren execution finishes.
- The main **executor** is a *class* and not a *method*.
- All the methods available for the users are integrated within the main *executor class*.
- Added state in the main *executor class* in order to control the correct execution order of its methods (like a Turing machine)
- When a new *executor class* is instantiated, it is created a new unique **executor_id** used to store all the objects in COS, and to retrieve the results.
- When a new *executor class* is instantiated, it is created a *storage_handler* used in the all PyWren execution.
- Now it is possible to specify the **runtime** when the user instantiates the *executor class* instead of changing the config file every time (In the config file is specified the default runtime).
- The **logging level** is now specified when the user instantiates the *executor class* instead of put it in the first line of the code within an env variable.
- The PyWren code which is executed remotely as a wrapper of the function now uses the main storage handler as the rest of the PyWren code. In previous versions, PyWren creates a new storage client directly with *boto3* library instead of using pywren/storage/storage.py wrapper. 
- Added support for multiple parameters in the functions which are executed remotely as a cloud functions. Previous versions just allows one parameter.
- Eased the usage of the storage backend within a function. By simply specifying *storage_handler* as a parameter of the function, the user will get access to the storage backend.
- Added a new method for retrieving the results of an execution called **fetch_all_resuslts()**. Previous PyWren versions already includes a method called *get_all_results()*, but this is a sequential method and it takes long time to retrieve all the results. It was also included a *wait()* class which is more similar to *get_all_results()* method, the main difference is that the new method is all based on *list the available objects in a bucket*, and it returns when all the tasks are finished. The new method also has the possibility to activate a progress bar in order to track the current status of the execution (really useful for larger executions).
- Added support for libs not included in the IBM Cloud Functions native image (*python-jessie:3*). Some libraries necessary for executing PyWren (remote code) are not included in the native CFs docker image. Now PyWren has the *pywren/libs* dir which includes all of these libraries, so it is possible to use PyWren with the native Docker image instead of building a new one with the missing libraries.
- In the COS backend, the *boto3* library was changed to the *ibm_boto3* library
- Increased function execution timeout to 600 seconds (10 minutes)
- Other minor changes
