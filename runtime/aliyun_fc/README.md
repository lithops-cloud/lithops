# Lithops runtime for Aliyun Functions Compute

The runtime is the place where your functions are executed. The default runtime is automatically created the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it.

Currently, Aliyun Functions Compute supports Python 3.6, 3.9 and 3.10. You can find the list of pre-installed modules [here](https://www.alibabacloud.com/help/en/function-compute/latest/python-event-functions). In addition, the Lithops default runtimes are built with the packages included in this [requirements.txt](requirements.txt) file:

To run a function with the default runtime you don't need to specify anything in the code, since everything is handled internally by Lithops:

```python
import lithops

def my_function(x):
    return x + 7

fexec = lithops.FunctionExecutor()
fexec.call_async(my_function, 3)
result = lithops.get_result()
```

By default, Lithops uses 256MB as runtime memory size. However, you can change it in the `config` or when you obtain the executor, for example:

```python
import lithops
pw = lithops.FunctionExecutor(runtime_memory=512)
```

## Custom runtime

**Build your own Lithops runtime for Aliyun Functions Compute**

If you require additional Python modules not included in the default runtime, you can create your own custom Lithops runtime incorporating them. To create a custom runtime, compile all the necessary modules into a `requirements.txt` file.

For instance, if you wish to integrate the `matplotlib` module into your runtime, which isn't part of the default setup, you need to append it to the existing [requirements.txt](requirements.txt) file. Note that this `requirements.txt` contains the mandatory pakcges required by lithops, so you don't have to remove any of them from the list, but just add your packages at the end.

After updating the file accordingly, you can proceed to build the custom runtime by specifying the modified `requirements.txt` file along with a chosen runtime name:

```
$ lithops runtime build -b aliyun_fc -f requirements.txt my_matplotlib_runtime 
```

This command will built and deploy a runtime called `my_matplotlib_runtime` to the available Aliyun FUnctions Compute runtimes.

Finally, we can specify this new runtime when creating a Lithops Function Executor:

```python
import lithops

def test():
    import matplotlib
    return repr(matplotlib)

lith = lithops.FunctionExecutor(runtime='my_matplotlib_runtime')
lith.call_async(test, data=())
res = lith.get_result()
print(res)
```

Note that both the client and the runtime must have the same python version. If you are running Lithops, for example, with Python 3.8, `my_matplotlib_runtime` will be a Python 3.8 runtime with the extra modules specified installed.
