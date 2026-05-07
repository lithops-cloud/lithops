# Lithops runtime for Google Cloud Run functions (v2)

This backend targets Google Cloud Run functions (formerly Cloud Functions 2nd gen) through the Cloud Functions v2 API. Runtimes are deployed from source and built by Google-managed buildpacks, so you provide Python dependencies in `requirements.txt` instead of a custom container image.

You can check supported runtimes and language details in the Cloud Run functions docs:
- [Runtime support](https://docs.cloud.google.com/functions/docs/runtime-support)
- [Python dependencies](https://docs.cloud.google.com/run/docs/runtimes/python-dependencies)

In addition, the Lithops default runtimes are built with the packages included in this [requirements.txt](requirements.txt) file:

The default runtime is created automatically the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it. In this sense, to run a function with the default runtime you don't need to specify anything in the code, since everything is managed internally by Lithops:

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

**Build your own Lithops runtime for Google Cloud Run functions (v2)**

If you require additional Python modules not included in the default runtime, you can create your own custom Lithops runtime incorporating them. To create a custom runtime, compile all the necessary modules into a `requirements.txt` file.

For instance, if you wish to integrate the `matplotlib` module into your runtime, which isn't part of the default setup, you need to append it to the existing [requirements.txt](requirements.txt) file. Note that this `requirements.txt` contains the mandatory packages required by lithops, so you don't have to remove any of them from the list, but just add your packages at the end.

After updating the file accordingly, you can proceed to build the custom runtime by specifying the modified `requirements.txt` file along with a chosen runtime name:

```
$ lithops runtime build -b gcp_functions -f requirements.txt my_matplotlib_runtime 
```

This command will add an extra runtime called `my_matplotlib_runtime` to the available Google Cloud Run functions (v2) runtimes.

Finally, you can specify this new runtime when creating a Lithops Function Executor:

```python
import lithops

def test():
    import matplotlib
    return repr(matplotlib)

lith = lithops.FunctionExecutor(runtime='my_matplotlib_runtime')
lith.call_async(test, data=())
res = lith.get_result()
print(res)  # Prints <module 'matplotlib' from '/layers/google.python.pip/pip/lib/python3.12/site-packages/matplotlib/__init__.py'>
```

If we are running Lithops, for example, with Python 3.12, `my_matplotlib_runtime` will be a Python 3.12 runtime with the extra modules specified installed.
