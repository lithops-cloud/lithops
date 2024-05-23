# Virtual Machine

Lithops can run functions using a remote host or a virtual machine (VM). In this backend, Lithops uses all the available VM CPUs to parallelize the tasks of a job. For testing purposes, it is preferable to have an Ubuntu > 22.04 host.

## Configuration

1. Edit your Lithops config and add the following keys:

```yaml
lithops:
    backend: vm
    
vm:
    ip_address: <ip>
    ssh_username: <username>
    ssh_password: <password>
```

## Execution Environments

The virtual machine backend can run functions both using the default ``python3`` interpreter of the VM, or by using a ``docker container`` within the VM. The environment is automatically chosen depending on if you provided a Docker image as a runtime or not.

### Default Environment
The default environment runs the functions in the same ``python3`` interpreter that you ran the Lithops script. It does not require any extra configuration. You must ensure that your VM contains the same ``python3`` interpreter, and all the dependencies required by your Lithops app. So, once the backend is configured in the config file, you only need to create a ``FunctionExecutor`` to work with it:

```python
fexec = lithops.FunctionExecutor()
```

### Docker Environment

The Docker environment runs the functions within a ``docker container``. In this case you must [install the Docker CE version](https://docs.docker.com/get-docker/) in your VM. Note that in this case the container image must contain all the dependencies required by your Lithops app. This environment is automatically activated when you provide a docker image as a runtime. For example, by adding the following keys in the config:

```yaml
vm:
    runtime: lithopscloud/ibmcf-python-v312
```

or by using the ``runtime`` param in a function executor:

```python
fexec = lithops.FunctionExecutor(runtime='lithopscloud/ibmcf-python-v312')
```

In this backend, you can use any docker image that contains all the required dependencies. For example, the IBM Cloud Functions and Knative runtimes are compatible with it.

## Summary of configuration keys for a single Virtual Machine:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|vm | ip_address | |yes | IP Address of the VM |
|vm | ssh_username   | | yes | SSH username for accessing the VM |
|vm | ssh_password | | no | SSH password for accessing the VM |
|vm | ssh_key_filename | | no | Path to SSH key |
|vm | runtime |  python3  |no | `python3` or a docker image name |
|vm | worker_processes | 1 | no | Number of Lithops processes within the VM. This can be used to parallelize function activations within the VM. It is recommendable to set it with the same number CPUs of the VM |

## Test Lithops

Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b vm -s ibm_cos
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```