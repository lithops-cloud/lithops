# Lithops runtime for AWS Lambda

The runtime is the place where your functions are executed.

AWS Lambda provides two methods for packaging the function code and dependencies of a runtime:

## Using predefined **runtimes** and **layers**
An AWS Lambda *runtime* is a predefined environment to run code on Lambda. For example, for Lithops we use runtimes for python >= 3.6 that come with already preinstalled modules. A *layer* is a set of packaged dependencies that can be used by multiple runtimes. For example, Lithops dependencies are deployed as a layer, so if multiple runtimes are created with different memory values, they can mount the same layer containing the dependencies, instead
of deploying them separately for each runtime.

[In this link](https://gist.github.com/gene1wood/4a052f39490fae00e0c3#gistcomment-3131227) you can find which modules are preinstalled by default in an AWS Lambda Python runtime. Moreover, Lithops runtime also ships with the following packages:

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

Update the [template Dockerfile](Dockerfile) that better fits to your requirements with your required system packages and Python modules.
You can add a container layer (`RUN ...`) to install additional Python modules using `pip` or system libraries using `apt`, or even change Python version to a older/newer one.

If you plan to use the **ARM64** architecture, you should consider creating a new dockerfile with an arm image from [https://gallery.ecr.aws/lambda/python](https://gallery.ecr.aws/lambda/python), in the tab "image tags". For example, you should start the dockerfile with the line `FROM public.ecr.aws/lambda/python:3.9-arm64`	

Then, to build the custom runtime, use `lithops runtime build` CLI specifying the modified `Dockerfile` file and a runtime name. 
Note that you only need to specify the container name: `my-container-runtime-name`. 
As far as possible, avoid using 'points' ('.') in the runtime name.

```
lithops runtime build -f MyDockerfile -b aws_lambda my-container-runtime-name
```

For example:

```
lithops runtime build -f MyDockerfile -b aws_lambda lithops-ndvi-v312:01
```

Finally, we can specify this new runtime in the lithops config:

```yaml
aws_lambda:
    runtime: lithops-ndvi-v312:01
```

or when creating a Lithops Function Executor:

```python
import lithops

def test():
    return 'hello'

lith = lithops.FunctionExecutor(runtime='lithops-ndvi-v312:01')
lith.call_async(test, data=())
res = lith.get_result()
print(res)  # Prints 'hello'
```

**View your deployed runtimes**

To view the already deployed runtimes in your account, you can submit the next command in the console:

```
lithops runtime list -b aws_lambda
```
