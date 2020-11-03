# Lithops on localhost

Lithops can run functions in the localhost by using processes, either in the default interpreter or within a Docker container.


### Configuration

2. Edit your lithops config and add the following keys:

```yaml
    lithops:
        executor: localhost
```

- Note that in the *storage* key you can set any publicly accessible storage backend implementation, such as IBM Cloud Object Storage, although using the localhost implementation is much faster for running local jobs.


### Execution environments

The localhost executor can run functions in multiple environments. Currently it supports the *default python3* and the *Docker* environments. The environment is automatically chosen depending on if you provided a Docker image as a runtime or not. In both cases, you can view the executions logs at */tmp/lithops/functions.log* (Or equivalent in Windows, Mac OS).

#### Default Environment
The default environment runs the functions in the same *python3* interpreter that you ran the lithops script.
It does not require any extra configuration. You must ensure that all the dependencies of your script are installed in your machine.

#### Docker Environment
The Docker environment runs the functions within a Docker container. In this case you must [install the Docker CE version](https://docs.docker.com/get-docker/) in your machine. This environment is automatically activated when you provide a docker image as a runtime. For example, by adding the following keys in the config:

```yaml
    localhost:
        runtime: ibmfunctions/action-python-v3.6
```

In this mode of execution, you can use any docker image that contains all the required dependencies. For example, the IBM Cloud Functions and Knative runtimes are compatible with it.
