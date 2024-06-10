# Localhost

In localhost, Lithops will use local CPUs to run functions in parallel. In this mode of execution it is not necessary to provide any kind of configuration or create a configuration file.

## Configuration

1. In case you have a config file, edit it and add these keys:

```yaml
lithops:
    backend: localhost
    storage: localhost  # You can also set it to a public storage backend, such as aws_s3 or ibm_cos
```

## Execution Environments

The localhost backend can run functions both using the local ``python3`` interpreter, or using a ``container`` image. The environment is automatically chosen depending on whether or not you provided a Docker image as a runtime.

In both cases, you can view the executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```

### Default Environment

By default Lithops uses the local python interpreter to run the functions. That is, if for example you executed the main script with ``python3.12``, your functions will run with ``python3.12``. in this case, you must ensure that all the dependencies of your script are installed in your machine.

```python
# As we use the default FunctionExecutor(), backend must be set to localhost in config
fexec = lithops.FunctionExecutor()
```

or alternatively, you can force the Localhost executor with:

```python
# As we use/force the LocalhostExecutor(), backend does not need to be set to localhost in config
fexec = lithops.LocalhostExecutor()
```

### Container Environment

The Container environment runs the functions within a ``docker container``. In this case you must [install the Docker CE version](https://docs.docker.com/get-docker/) in your machine. This environment is automatically activated when you provide a docker image as a runtime. For example, by adding the following keys in the config:

```yaml
localhost:
    runtime: docker.io/lithopscloud/ibmcf-python-v312
```

or by using the ``runtime`` param in a function executor:

```python
# As we use the default FunctionExecutor(), the "backend" config parameter must be set to localhost in config
fexec = lithops.FunctionExecutor(runtime='docker.io/lithopscloud/ibmcf-python-v312')
```

```python
# As we use/force the LocalhostExecutor(), the "backend" config parameter does not need to be set to localhost in config
fexec = lithops.LocalhostExecutor(runtime='docker.io/lithopscloud/ibmcf-python-v312')
```

In this mode of execution, you can use any docker image that contains all the required dependencies. For example, the IBM Cloud Functions and Knative runtimes are compatible with it.

## Summary of configuration keys for Localhost:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|localhost | runtime | python3 | no | By default it uses the `python3` interpreter. It can be a container image name |
|localhost | version | 2 | no | There are 2 different localhost implementations. Use '1' for using the alternative version |
|localhost | worker_processes | CPU_COUNT | no | Number of Lithops processes. This is used to parallelize function activations. By default it is set to the number of CPUs of your machine |

## Test Lithops

Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b localhost -s localhost
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```

You can view the localhost runner logs in `/tmp/lithops-*/localhost-runner.log`