# Lithops runtime for AWS Lambda

The runtime is the place where your functions are executed.

Unlike other Serverless backends like IBM Cloud Functions or Google Cloud Run, AWS Lambda is not based on Docker, so it is not possible to provide a Docker image as the function's runtime.
However, it is possible to expand the default installed packages by providing a different `requirements.txt` file. In consequence, it is not possible to add a system library to the runtime, only Python modules that can be installed using `pip`.

AWS Lambda provide the following default runtimes with some packages already preinstalled:

| Runtime name | Python version | Packages included |
| ----| ----| ---- |
| python3.6 | 3.6 | [list of packages](https://gist.github.com/gene1wood/4a052f39490fae00e0c3#gistcomment-3131227) |
| python3.7 | 3.7 | [list of packages](https://gist.github.com/gene1wood/4a052f39490fae00e0c3#gistcomment-3131227) |
| python3.8 | 3.8 | [list of packages](https://gist.github.com/gene1wood/4a052f39490fae00e0c3#gistcomment-3131227) |

Lithops runtime also ships with the following packages:
```
beautifulsoup4
httplib2
kafka-python
lxml
python-dateutil
requests
scrapy
simplejson
virtualenv
Twisted
PyJWT
Pillow
redis
pika==0.13.1
```

The default runtime is created the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it.

To run a function with the default runtime you don't need to specify anything in the code, since everything is managed internally by Lithops:

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

**Build your own Lithops runtime for AWS Lambda**

If you need some Python modules which are not included in the default runtime, it is possible to build your own Lithops runtime with all of them.

To build your own runtime, you have to collect all necessary modules in a `requirements.txt` file.

For example, we want to add module `matplotlib` to our runtime, since it is not provided in the default runtime.

First, we need to extend the default `requirements.txt` file provided with Lithops with all the modules we need. For our example, the `requirements.txt` will contain the following modules:
```
beautifulsoup4
httplib2
kafka-python
lxml
python-dateutil
requests
scrapy
simplejson
virtualenv
Twisted
PyJWT
Pillow
redis
pika==0.13.1
matplotlib
```

Then, we will build the runtime, specifying the modified `requirements.txt` file and a runtime name:
```
$ lithops runtime build -f requirements.txt my_matplotlib_runtime
```

This command will add an extra runtime called `my_matplotlib_runtime` to the available AWS Lambda runtimes.

Finally, we can specify this new runtime when creating a Lithops Function Executor:

```python
import lithops

def test():
    import matplotlib
    return repr(matplotlib)

lith = lithops.FunctionExecutor(runtime='my_matplotlib_runtime')
lith.call_async(test, data=())
res = lith.get_result()
print(res)  # Prints <module 'matplotlib' from '/layers/google.python.pip/pip/lib/python3.8/site-packages/matplotlib/__init__.py'>
```

If we are running Lithops, for example, with Python 3.8, `my_matplotlib_runtime` will be a Python 3.8 runtime with the extra modules specified installed.
