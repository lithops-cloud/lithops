.. _futures-api:

Lithops Futures API
===================

The primary object in Lithops is the executor. The standard way to get everything set up is to import `lithops`, and create an instance of one of the available modes of executions.

Lithops is shipped with 3 modes of execution: **Localhost**, **Serverless** and **Standalone**. In this sense, each mode of execution has its own executor class:

* `lithops.LocalhostExecutor()`: Executor that uses local processes to run jobs in the local machine.
* `lithops.ServerlessExecutor()`: Executor to run jobs in one of the available serverless compute backends.
* `lithops.StandaloneExecutor()`: Executor to run jobs in one of the available standalone compute backends.

Additionally, Lithops includes a top-level function executor, which encompasses all three previous executors:

* `lithops.FunctionExecutor()`: Generic executor that will use the configuration to determine its mode of execution, i.e., based on the configuration it will be **localhost**, **serverless** or **standalone**.

By default, the executor load the configuration from the config file. Alternatively, you can pass the configuration with a python dictionary. In any case, note that all the parameters set in the executor will overwrite those set in the configuration.

Futures API Reference
---------------------

.. automodule:: lithops.executors
   :members:
   :undoc-members:
   :show-inheritance:
