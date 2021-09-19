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
Runs a *hello-world* function.

|Parameter | Description|
|---|---|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--storage, -s | Storage backend name|
|--debug, -d | Activate debug logs (Flag)|

* **Usage example**:
   `lithops test -b ibm_cf -s ibm_cos`


### `lithops verify`
Runs the unit testing.

|Parameter | Description|
|---|---|
|--config, -c | Path to your config file|
|--backend, -b |  Compute backend name|
|--storage, -s | Storage backend name|
|--debug, -d | Activate debug logs (Flag)|
|--test, -t | Run a specific tester |
|--groups, -g |  Run all testers belonging to a specific group |
|--fail_fast, -f | Stops test run upon first occurrence of a failed test (Flag)|
|--keep_datasets, -f | Keeps datasets in storage after the test run (Flag)|


* **Usage example**:
   `lithops verify -b ibm_cf -s ibm_cos -f`


## Runtime management




## Logs management




## Storage management