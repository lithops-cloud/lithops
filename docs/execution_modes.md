#Lithops Execution Modes
=======================


##Localhost mode

Lithops uses local processes to run functions by default. In this mode of execution it is not necessary to provide any kind of configuration or create a configuration file.

### Execution environments

The localhost executor can run functions in multiple environments. Currently it supports the *default python3* and the *Docker* environments. The environment is automatically chosen depending on if you provided a Docker image as a runtime or not. 

In both cases, you can view the executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```

#### Default Environment
The default environment runs the functions in the same *python3* interpreter that you ran the lithops script.
It does not require any extra configuration. You must ensure that all the dependencies of your script are installed in your machine.

```python
    fexec = lithops.FunctionExecutor()
```

or alternatively you can force the localhost mode with:

```python
    fexec = lithops.FunctionExecutor(mode='localhost')
```

or with its own executor:

```python
    fexec = lithops.LocalhostExecutor()
```


#### Docker Environment
The Docker environment runs the functions within a Docker container. In this case you must [install the Docker CE version](https://docs.docker.com/get-docker/) in your machine. This environment is automatically activated when you provide a docker image as a runtime. For example, by adding the following keys in the config:

```yaml
    localhost:
        runtime: ibmfunctions/action-python-v3.6
```

of by using the *runtime* param in a function executor:

```python
    fexec = lithops.FunctionExecutor(mode='localhost', runtime='jsampe/action-python-v3.8')
```

or:

```python
    fexec = lithops.LocalhostExecutor(runtime='jsampe/action-python-v3.8')
```



In this mode of execution, you can use any docker image that contains all the required dependencies. For example, the IBM Cloud Functions and Knative runtimes are compatible with it.


Serverless mode
---------------
This mode allows to run functions by using one or multiple function-as-a-service (FaaS) Serverless compute backends. In this mode of execution, each function invocation equals to a parallel task running in the cloud in an isolated environment.

In this mode of execution, the execution environment depends of the serverless compute backend. For example, in IBM Cloud Functions, Google Cloud Run, IBM Code Engine and knative you must use a Docker image as execution environment. In contrast, AWS Lambda, Google cloud functions and Azure functions use their own formats of environments. 

In the serverless mode of execution a default runtime is automatically deployed the first time you run a function over it. This runtime (or execution environment) contains some basic packages or dependencies. In this sense, if you need to build a custom runtime with extra packages to run your functions, navigate to the [runtime/](../runtime) folder, choose your backend, and follow the instructions to build it.

Once you have your backend configured, you can create an executor with:

```python
    fexec = lithops.FunctionExecutor()
```

or alternatively, you can force the serverless mode with:

```python
    fexec = lithops.FunctionExecutor(mode='serverless)
```

or with its own executor:

```python
    fexec = lithops.ServerlessExecutor()
```


Standalone mode
---------------

This mode allows to run functions by using a cluster of Virtual machines (VM). In the VMs that conform the cluster, functions run using parallel processes. This mode of executions is simlitar to the localhost, but using remote machines. In this sense, it provides both the *default python3* and the *Docker* environments. The environment is automatically chosen depending on if you provided a Docker image as a runtime or not. 

In both cases, you can view the executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```

#### Default Environment
The default environment runs the functions in the same *python3* interpreter that you ran the lithops script.
It does not require any extra configuration. You must ensure that all the dependencies of your script are installed in your machine.

```python
    fexec = lithops.FunctionExecutor()
```

or alternatively you can force the standalone mode with:

```python
    fexec = lithops.FunctionExecutor(mode='standalone')
```

or with its own executor

```python
    fexec = lithops.StandaloneExecutor()
```


#### Docker Environment
The Docker environment runs the functions within a Docker container. In this case you must [install the Docker CE version](https://docs.docker.com/get-docker/) in your machine. This environment is automatically activated when you provide a docker image as a runtime. For example, by adding the following keys in the config:

```yaml
    localhost:
        runtime: ibmfunctions/action-python-v3.6
```

of by using the *runtime* param in a function executor:

```python
    fexec = lithops.FunctionExecutor(mode='standalone', runtime='jsampe/action-python-v3.8')
```

or:

```python
    fexec = lithops.StandaloneExecutor(runtime='jsampe/action-python-v3.8')
```


In this mode of execution, you can use any docker image that contains all the required dependencies. For example, the IBM Cloud Functions and Knative runtimes are compatible with it.
