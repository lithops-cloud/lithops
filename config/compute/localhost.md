# Lithops on Localhost

Lithops uses local processes to run functions by default. In this mode of execution it is not necessary to provide any kind of configuration or create a configuration file. 

### Configuration

1. Edit your lithops config and add the following keys:

```yaml
    lithops:
        backend: localhost
        
    localhost:
        runtime: <docker_name>
        worker_processes: CPU_COUNT
```

### Summary of configuration keys for Localhost:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|localhost | runtime |  python3  | no | Docker image name |
|localhost | worker_processes | CPU_COUNT | no | Number of Lithops processes. This is used to parallelize function activations. By default it is set to the number of CPUs of your machine |



### Execution environments

The localhost executor can run functions in multiple environments. Currently it supports the *default python3* and the *Docker* environments. The environment is automatically chosen depending on whether or not you provided a Docker image as a runtime.

In both cases, you can view the executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```

Localhost backend does not require any configuration file to work, so you can directly create a function executor:

```python
    fexec = lithops.FunctionExecutor()
```

or alternatively, you can force the localhost backend with:

```python
    fexec = lithops.LocalhostExecutor()
```

If in contrast you already have a config file/dict, you must set the next keys in your config to make it working:

```yaml
lithops:
    backend: localhost
    storage: localhost  # You can also point it to a public storage backend, such as aws_s3 or ibm_cos
```

#### Default Environment
The default environment runs the functions in the same *python3* interpreter that you ran the lithops script.
It does not require any extra configuration. You must ensure that all the dependencies of your script are installed in your machine and then crate one of the availabe function executors.

```python
    # As we use the default FunctionExecutor(), backend must be set to localhost in config
    fexec = lithops.FunctionExecutor()
```

or alternatively, you can force the Localhost executor with:

```python
    # As we use/force the LocalhostExecutor(), backend does not need to be set to localhost in config
    fexec = lithops.LocalhostExecutor()
```


#### Docker Environment
The Docker environment runs the functions within a Docker container. In this case you must [install the Docker CE version](https://docs.docker.com/get-docker/) in your machine. This environment is automatically activated when you provide a docker image as a runtime. For example, by adding the following keys in the config:

```yaml
    localhost:
        runtime: ibmfunctions/action-python-v3.8
```

of by using the *runtime* param in a function executor:


```python
    # As we use the default FunctionExecutor(), backend must be set to localhost in config
    fexec = lithops.FunctionExecutor(runtime='jsampe/action-python-v3.8')
```

```python
    # As we use/force the LocalhostExecutor(), backend does not need to be set to localhost in config
    fexec = lithops.LocalhostExecutor(runtime='jsampe/action-python-v3.8')
```

In this mode of execution, you can use any docker image that contains all the required dependencies. For example, the IBM Cloud Functions and Knative runtimes are compatible with it.
