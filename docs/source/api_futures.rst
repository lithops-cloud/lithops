.. _futures-api:

Lithops Futures API
===================

The core abstraction in Lithops is the **executor**, responsible for orchestrating the execution of your functions across different environments.

To get started, you typically import `lithops` and create an executor instance to run your code. Lithops provides a flexible set of executors to suit different needs.

Primary Executors
-----------------

* **FunctionExecutor** (`lithops.FunctionExecutor()`):  
  The main, generic executor that automatically selects its execution mode based on the provided configuration.  
  This lets you write your code once and run it seamlessly on localhost, serverless, or standalone backends without changing your code.

* **RetryingFunctionExecutor** (`lithops.RetryingFunctionExecutor()`):  
  A robust wrapper around `FunctionExecutor` that transparently handles retries on failed tasks.  
  It supports all features of `FunctionExecutor` with added automatic retry logic, improving fault tolerance and reliability for unstable or transient failure-prone environments.

Secondary Executors
-------------------

For more specialized use cases, Lithops also provides explicit executors for each execution mode:

* **LocalhostExecutor** (`lithops.LocalhostExecutor()`):  
  Runs jobs locally using multiple processes on your machine. Ideal for development, debugging, or small-scale workloads.

* **ServerlessExecutor** (`lithops.ServerlessExecutor()`):  
  Executes jobs on serverless compute platforms, managing scaling and deployment automatically. Best for massively parallel, ephemeral workloads.

* **StandaloneExecutor** (`lithops.StandaloneExecutor()`):  
  Runs jobs on standalone compute backends such as clusters or virtual machines, suitable for long-running or resource-heavy tasks.


Configuration and Initialization
================================

By default, executors load configuration from the Lithops configuration file (e.g., `lithops_config.yaml`). You can also supply configuration parameters programmatically via a Python dictionary when creating an executor instance. Parameters passed explicitly override those in the config file, allowing for flexible customization on the fly.

This layered executor design lets Lithops provide a powerful, unified API for parallel function execution — from local development to multi-cloud production deployments with fault tolerance and retries built-in.


Futures API Reference
---------------------

.. automodule:: lithops.executors
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: lithops.retries.RetryingFunctionExecutor
   :members:
   :undoc-members:
   :show-inheritance:
