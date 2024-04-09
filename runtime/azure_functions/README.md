# Lithops runtime for Azure Functions

The runtime is the place where your functions are executed. The default runtime is automatically created the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it.

Currently, Azure Functions supports Python 3.6, 3.7, 3.8 and 3.9. You can find the list of pre-installed modules [here](https://github.com/Azure/azure-functions-python-worker/wiki/Preinstalled-Python-Libraries). In addition, the Lithops default runtimes are built with the packages included in this [requirements.txt](requirements.txt) file

To run a function with the default runtime you don't need to specify anything in the code, since everything is handled internally by Lithops:

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

If you require additional Python modules not included in the default runtime, you can create your own custom Lithops runtime incorporating them. To create a custom runtime, compile all the necessary modules into a `requirements.txt` file.

For instance, if you wish to integrate the `matplotlib` module into your runtime, which isn't part of the default setup, you need to append it to the existing [requirements.txt](requirements.txt) file. Note that this `requirements.txt` contains the mandatory pakcges required by lithops, so you don't have to remove any of them from the list, but just add your packages at the end.

**IMPORTANT**: Note that the runtime is built using your local machine, and some libraries, like Numpy, compile some *C* code based on the Operating System you are using. Azure functions run on a Linux machine, this mean that if you use **MacOS** or **Windows** for building the runtime, those libraries that compiled *C* code cannot be executed from within the function. In this case, you must use a Linux machine for building the runtime.

After updating the file accordingly, you can proceed to build the custom runtime by specifying the modified `requirements.txt` file along with a chosen runtime name:
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
