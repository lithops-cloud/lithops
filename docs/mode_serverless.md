# Lithops Serverless Execution Mode

This mode allows to run functions by using one or multiple function-as-a-service (FaaS) Serverless compute backends.  In this mode of execution, each function invocation equals to a parallel task running in the cloud in an isolated environment.

In this mode of execution, the execution environment depends of the serverless compute backend. For example, in IBM Cloud Functions, Google Cloud Run, IBM Code Engine and knative you must use a Docker image as execution environment. In contrast, AWS Lambda, Google cloud functions and Azure functions use their own formats of environments. 

In the serverless mode of execution a default runtime is automatically deployed the first time you run a function. Note that these default runtimes (or execution environments) contains some basic packages and dependencies. So, if you need to use extra packages and libraries to run your functions you must build a custom runtime. In this case, navigate to the [runtime/](../runtime) folder, choose your backend, and follow the instructions to build it.

You can view the executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```

This is the default mode of execution, this means no extra configuration is required to make it working. So once you have your compute backend configured, you can create an executor with:

```python
    # As we use the default FunctionExecutor(), mode must be set to serverless in config (it set by default)
    fexec = lithops.FunctionExecutor()
```

or alternatively, you can force the serverless mode with:

```python
    # As we use/force the ServerlessExecutor(), mode does not need to be set to serverless in config
    fexec = lithops.ServerlessExecutor()
```

## Dynamic runtime customization

This new feature enables early preparation of Lithops workers with the map function and custom Lithops runtime already deployed, and ready to be used in consequent computations. This can reduce overall map/reduce computation latency significantly, especially when the computation overhead (pickle stage) is long compared to the actual computation performed at the workers.

To activate this mode, set to True the "customized_runtime" property under "serverless" section of the config file.

Warning: to protect your privacy, use a private docker registry instead of public docker hub.

```
serverless:
    customized_runtime: True
```