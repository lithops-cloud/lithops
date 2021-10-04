# Lithops on a Virtual Machine

Lithops can run functions in a regular remote virtual machine by using processes, either in the default interpreter or within a Docker container. For testing purposes, it is preferable to have an Ubuntu 20.04 VM.


### Configuration

1. Edit your lithops config and add the following keys:

```yaml
    lithops:
        backend: vm
        
    vm:
        ip_address: <ip>
        ssh_username: <username>
        ssh_password: <password>
```

### Summary of configuration keys for a single Virtual Machine:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|vm | ip_address | |yes | IP Address of the VM |
|vm | ssh_username   | | yes | SSH username for accessing the VM |
|vm | ssh_password | | yes | SSH password for accessing the VM |
|vm | worker_processes | 1 | no | Number of Lithops processes within the VM. This can be used to parallelize function activations within a worker. It is recommendable to set it with same number CPUs of the VM |
|vm | runtime |  python3  |no | Docker image name |


### Execution environments

The remote virtual machine executor can run functions in multiple environments. Currently it supports the *default python3* and the *Docker* environments. The environment is automatically chosen depending on if you provided a Docker image as a runtime or not. 

In both cases, you can view the executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```

#### Default Environment
The default environment runs the functions in the same *python3* interpreter that you ran the lithops script.
It does not require any extra configuration. You must ensure that all the dependencies of your script are installed in your machine.

```yaml
    standalone:
        runtime: python3
```

#### Docker Environment
The Docker environment runs the functions within a Docker container. In this case you must [install the Docker CE version](https://docs.docker.com/get-docker/) in your machine. This environment is automatically activated when you provide a docker image as a runtime. For example, by adding the following keys in the config:

```yaml
    standalone:
        runtime: lithopscloud/ibmcf-python-v38
```

In this mode of execution, you can use any docker image that contains all the required dependencies. For example, the IBM Cloud Functions and Knative runtimes are compatible with it.
