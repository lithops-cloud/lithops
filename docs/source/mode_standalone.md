# Lithops Standalone Execution Mode

This mode allows to run functions by using a Virtual machine (VM). In the VM, functions run using parallel processes. This mode of executions is similar to the localhost mode, but using remote machines. In this case, it is not needed to install anything in the remote VMs since Lithops does this process automatically the first time you use them. 

Moreover, like the localhost execution mode, it also provides both the *default python3* and the *Docker* environments. The environment is automatically chosen depending on whether do you provided a Docker image as a runtime or not.

In both cases, you can view the executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```

### Default Environment
The default environment runs the functions in the same *python3* interpreter that you ran the lithops script.
It does not require any extra configuration. You must ensure that all the dependencies of your script are installed in your machine.

```python
    # As we use the default FunctionExecutor(), mode must be set to standalone in config
    fexec = lithops.FunctionExecutor()
```

or alternatively you can force the standalone mode with:

```python
    # As we use/force the StandaloneExecutor(), mode does not need to be set to standalone in config
    fexec = lithops.StandaloneExecutor()
```


### Docker Environment
The Docker environment runs the functions within a Docker container. This environment is automatically activated when you provide a docker image as a runtime. For example, by adding the following keys in the config:

```yaml
    standalone:
        runtime: ibmfunctions/action-python-v3.6
```

or by using the *runtime* param in a function executor:

```python
    # As we use the default FunctionExecutor(), mode must be set to standalone in config
    fexec = lithops.FunctionExecutor(runtime='jsampe/action-python-v3.8')
```

```python
    # As we use/force the StandaloneExecutor(), mode does not need to be set to standalone in config
    fexec = lithops.StandaloneExecutor(runtime='jsampe/action-python-v3.8')
```


In this mode of execution, you can use any docker image that contains all the required dependencies. For example, the IBM Cloud Functions and Knative runtimes are compatible with it.
