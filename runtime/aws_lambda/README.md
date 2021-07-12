# Lithops runtime for AWS Lambda

The runtime is the place where your functions are executed.

AWS Lambda provides two methods for packaging the function code and dependencies of a runtime:

## Using predefined **runtimes** and **layers**
An AWS Lambda *runtime* is a predefined environment to run code on Lambda. For example, for Lithops we use runtimes `python3.8`, `python3.7` or `python3.6` that
come with already preinstalled modules. A *layer* is a set of packaged dependencies that can be used by multiple runtimes. For example, Lithops dependencies are
deployed as a layer, so if multiple runtimes are created with different memory values, they can mount the same layer containing the dependencies, instead
of deploying them separately for each runtime.

Here you can find which modules are preinstalled by default in an AWS Lambda Python runtime:  

| Runtime name | Python version | Packages included |
| ---- | ---- | ---- |
| python36 | 3.6 | [list of packages](https://gist.github.com/gene1wood/4a052f39490fae00e0c3#gistcomment-3131227) |
| python37 | 3.7 | [list of packages](https://gist.github.com/gene1wood/4a052f39490fae00e0c3#gistcomment-3131227) |
| python38 | 3.8 | [list of packages](https://gist.github.com/gene1wood/4a052f39490fae00e0c3#gistcomment-3131227) |

Lithops runtime also ships with the following packages:
```
requests
numpy
redis
pika
cloudpickle
ps-mem
tblib
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

## Using a Container Runtime

**Build your own Lithops runtime for AWS Lambda**

Layers maximum unzipped size is 250 MB. Counting Lithops dependencies, this limit leaves little room for extra modules.

If you need some Python modules which are not included in the default runtime, it is possible to build your own Lithops runtime with all of them.

AWS Lambda allows using container images as runtime for the Lambda functions. This is useful to package, not only Python modules but also system libraries
so that they can be used in the Lambda code.

To build your own runtime, first install [Docker CE](https://docs.docker.com/get-docker/) in your client machine.

Update the [template Dockerfile](Dockerfile.python38) that better fits to your requirements with your required system packages and Python modules.
You can add a container layer (`RUN ...`) to install additional Python modules using `pip` or system libraries using `apt`, or even change Python version to a older/newer one.

Then, to build the custom runtime, use `lithops runtime build` CLI specifying the modified `Dockerfile` file and a runtime name.
Note that the runtime name must be a Docker image name, that is, `docker_username/container_image_name`:

```
$ lithops runtime build -f MyDockerfile docker_username/my_container_runtime -b aws_lambda
```

Finally, we can specify this new runtime when creating a Lithops Function Executor:

```python
import lithops

def test():
    return 'hello'

lith = lithops.FunctionExecutor(runtime='docker_username/my_container_image')
lith.call_async(test, data=())
res = lith.get_result()
print(res)  # Prints 'hello'
```

