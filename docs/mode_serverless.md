# Lithops Serverless Execution Mode

This mode allows to run functions by using one or multiple function-as-a-service (FaaS) Serverless compute backends. In this mode of execution, each function invocation equals to a parallel task running in the cloud in an isolated environment.

In this mode of execution, the execution environment depends of the serverless compute backend. For example, in IBM Cloud Functions, Google Cloud Run, IBM Code Engine and knative you must use a Docker image as execution environment. In contrast, AWS Lambda, Google cloud functions and Azure functions use their own formats of environments. 

In this mode of execution, you must use the backend specific client to see the function executions logs. For example, if you use the IBM Cloud Functions backend, you can see the logs navigating to the web dashboard or by using the *ibmcloud* cli interface.

In the serverless mode of execution a default runtime is automatically deployed the first time you run a function over it. This runtime (or execution environment) contains some basic packages or dependencies. In this sense, if you need to build a custom runtime with extra packages to run your functions, navigate to the [runtime/](../runtime) folder, choose your backend, and follow the instructions to build it.

Once you have your backend configured, you can create an executor with:

```python
    fexec = lithops.FunctionExecutor()
```

or alternatively, you can force the serverless mode with:

```python
    fexec = lithops.FunctionExecutor(mode='serverless')
```

or with its own executor:

```python
    fexec = lithops.ServerlessExecutor()
```

### Dynamic runtime customization
This new feature enables early preparation of Lithops workers with the map function and custom Lithops runtime already deployed, and ready to be used in consequent computations. This can reduce overall map/reduce computation latency significantly, especially when the computation overhead (pickle stage) is long compared to the actual computation performed at the workers.

To activate this mode, set to True the "customized_runtime" property under "serverless" section of the config file.

Warning: to protect your privacy, use a private docker registry instead of public docker hub.

```
serverless:
    customized_runtime: True
```