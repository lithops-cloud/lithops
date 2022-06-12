# Lithops runtime for Azure Functions

The runtime is the place where your functions are executed.

The default runtime is created the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it.

Currently, Azure Functions supports Python 3.6, 3.7, 3.8 and 3.9, and it provides the following default runtimes with some packages already preinstalled:

| Runtime name | Python version | Packages included |
| ----| ----| ---- |
| lithops-runtime-v36 | 3.6 | [list of packages](https://github.com/Azure/azure-functions-python-worker/wiki/Preinstalled-Python-Libraries) |
| lithops-runtime-v38 | 3.7 | [list of packages](https://github.com/Azure/azure-functions-python-worker/wiki/Preinstalled-Python-Libraries) |
| lithops-runtime-v38 | 3.8 | [list of packages](https://github.com/Azure/azure-functions-python-worker/wiki/Preinstalled-Python-Libraries) |
| lithops-runtime-v38 | 3.9 | [list of packages](https://github.com/Azure/azure-functions-python-worker/wiki/Preinstalled-Python-Libraries) |

Lithops default runtimes are also ship with the following packages:
```
azure-functions
azure-storage-blob
azure-storage-queue
pika
flask
gevent
redis
requests
PyYAML
kubernetes
numpy
cloudpickle
ps-mem
tblib
```

To run a function with the default runtime you don't need to specify anything in the code, since everything is managed internally by Lithops:

```python
import lithops

def my_function(x):
    return x + 7

fexec = lithops.FunctionExecutor()
fexec.call_async(my_function, 3)
result = lithops.get_result()
```

* Note that Azure Functions does not allow to set a specific memory size for the runtimes, so the parameter `runtime_memory` won't take effect.

## Custom runtime

**Build your own Lithops runtime for Azure Functions**

If you need some Python modules which are not included in the default runtime, it is possible to build your own Lithops runtime with all of them.

To build your own runtime, you have to collect all necessary modules in a `requirements.txt` file. For example, if you want to add the modules `numpy` and `matplotlib` to our runtime, since they are not provided in the default runtime.

First, we need to extend the `requirements.txt` file provided with Lithops with all the modules we need. For our example, the `requirements.txt` should contain the following modules (note that we added `numpy` and `matplotlib` at the end):
```
azure-functions
azure-storage-blob
azure-storage-queue
pika
flask
gevent
redis
requests
PyYAML
kubernetes
cloudpickle
ps-mem
tblib
numpy
matplotlib
```

**IMPORTANT**: Note that the runtime is built using your local machine, and some libraries, like Numpy, compile some *C* libraries based on the Operating System you are using. Azure functions run on a Linux machine, this mean that if you use **MacOS** or **Windows**, those libraries that complied *C* code cannot be executed from within the function. In this case, you must use a Linux machine for building the runtime.

Then, we will build the runtime, specifying the modified `requirements.txt` file and a runtime name:
```
$ lithops runtime build -b azure_functions -f requirements.txt matplotlib-runtime 
```

This command will built a runtime called `matplotlib-runtime` in your local machine. Then, to deploy the runtime to the available Azure Functions runtimes, execute:
```
$ lithops runtime deploy -b azure_functions -s azure_storage matplotlib-runtime 
```

Finally, we can specify this new runtime when creating a Lithops Function Executor:

```python
import lithops

def test():
    import matplotlib
    return repr(matplotlib)

lith = lithops.FunctionExecutor(runtime='matplotlib-runtime')
lith.call_async(test, data=())
res = lith.get_result()
print(res)
```

Note that both the client and the runtime must have the same python version. If you are running Lithops, for example, with Python 3.8, the `matplotlib-runtime` will be a Python 3.8 runtime with the extra modules specified installed.
