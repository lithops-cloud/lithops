# Lithops Command Line Tool

Lithops is shipped with a *command line tool* (or cli) called `lithops`. It brings **runtime**, **logs**, and **storage** management to the terminal of your computer. Lithops CLI is automatically installed when you install Lithops through `pip3 install lithops`.


## Lithops management

### `lithops clean`
Deletes all the information related to Lithops except the config file. It includes deployed runtimes and temporary data stored in the storage backend.
Run this command is like *start from scratch* with Lithops. In some circumstances, when there is some inconsistency between the local machine and the cloud,  it is convenient to run this command.

|Parameter | Description|
|---|---|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--storage, -s | Storage backend name|
|--debug, -d | Activate debug logs (Flag)|

* **Usage example**:
   `lithops clean -b ibm_cf -s ibm_cos`


### `lithops test`
Runs a *hello-world* test function.

|Parameter | Description|
|---|---|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--storage, -s | Storage backend name|
|--debug, -d | Activate debug logs (Flag)|

* **Usage example**:
   `lithops test -b ibm_cf -s ibm_cos`


### `lithops verify`
Runs the unit testing suite.

|Parameter | Description|
|---|---|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--storage, -s | Storage backend name|
|--debug, -d | Activate debug logs (Flag)|
|--test, -t | Run a specific tester |
|--groups, -g |  Run all testers belonging to a specific group |
|--fail_fast, -f | Stops test run upon first occurrence of a failed test (Flag)|
|--keep_datasets, -k | Keeps datasets in storage after the test run (Flag)|


* **Usage example**:
   `lithops verify -b ibm_cf -s ibm_cos -f`


## Runtime management
For complete instructions on how to build runtimes for Lithops, please refer to [runtime/](../runtime) folder and choose your compute backend.


### `lithops runtime build <runtime-name>`
Build a new runtime image. Depending of the compute backend, there must be a Dockerfile located in the same folder you run the command, otherwise use `-f` parameter. Note that this command only builds the image and puts it to a container registry. This command do not deploy the runtime to the compute backend.

|Parameter | Description|
|---|---|
|<runtime-name>| Name of your runtime|
|--file, -f | Path to Dockerfile/requirements|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--debug, -d | Activate debug logs (Flag)|


* **Usage example**:
   `lithops runtime build -f Dockefile.pythonv39 -b ibm_cf lithopscloud/my-runtime-name-v39:01`


### `lithops runtime create <runtime-name>`
Creates/deploy a new Lithops runtime based on a image built with the previous command. When you build a runtime, for example from a Dockerfile, the runtime is uploaded to a docker registry, however it is not deployed to the compute backend. To do so run this command. Note that the runtime is automatically created/deployed in the compute backend the first time you run a function with it, so in most of the cases you can avoid using this command.

|Parameter | Description|
|---|---|
|<runtime-name>| Name of your runtime|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--storage, -s | Storage backend name|
|--debug, -d | Activate debug logs (Flag)|
|--memory, -m | Memory size in MBs to assign to the runtime.|
|--timeout, -t | Timeout is seconds to assign to the runtime|


* **Usage example**:
   `lithops runtime create -b ibm_cf lithopscloud/my-runtime-name-v39:01 -m 1024 -t 300`


### `lithops runtime update <runtime-name>`
Updates an already created/deployed runtime with the local lithops code. This command is useful when developers change the local python Lithops code and want to update the deployed runtimes with it. As an alternative, you can run `lithops clean -b <backend-name>` and then let Lithops create the runtime automatically with the new Lithops code.

|Parameter | Description|
|---|---|
|<runtime-name>| Name of your runtime|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--storage, -s | Storage backend name|
|--debug, -d | Activate debug logs (Flag)|


* **Usage example**:
   `lithops runtime update -b ibm_cf lithopscloud/my-runtime-name-v39:01`


### `lithops runtime list`
Lists all created/deployed runtimes of an specific compute backend.

|Parameter | Description|
|---|---|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--debug, -d | Activate debug logs (Flag)|


* **Usage example**:
   `lithops runtime list -b ibm_cf`


### `lithops runtime delete <runtime-name>`
Deletes all runtimes created/deployed in the compute backend that matches the provided runtime-name. As an alternative, you can run `lithops clean -b <backend-name>` to delete not only the runtimes that match the provided runtime-name, but all them.

|Parameter | Description|
|---|---|
|<runtime-name>| Name of your runtime|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--storage, -s | Storage backend name|
|--debug, -d | Activate debug logs (Flag)|

* **Usage example**:
   `lithops runtime delete -b ibm_cf -s ibm_cos lithopscloud/my-runtime-name-v39:01`


## Logs management

### `lithops logs poll`
Prints to the screen the Lithops function logs as they are produced.


* **Usage example**:
   `lithops logs poll`

### `lithops logs get <job-key>`
Prints to the screen the Lithops function of a specific job.

|Parameter | Description|
|---|---|
|<job-key>| Job key|


* **Usage example**:
   `lithops logs get fa6071-26-M000`

## Storage management
