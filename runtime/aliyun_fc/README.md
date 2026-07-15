# Lithops runtime for Aliyun Functions Compute 3.0

The runtime is the place where your functions are executed. The default runtime is automatically created the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it.

Aliyun FC supports two Lithops deploy modes (set `deploy_mode` under `aliyun_fc` in config):

- **`runtime`** (default): zip package + managed Python runtime (`python3.10`, `python3.12`, region-dependent).
- **`custom-container`**: Docker image; see [Custom container mode](#custom-container-mode) below.

For managed runtimes, see pre-installed modules [here](https://www.alibabacloud.com/help/en/functioncompute/fc/user-guide/python/). Lithops default zip runtimes use [requirements.txt](requirements.txt):

## Custom container mode

Use this mode to run any Python version (e.g. 3.12) without relying on managed FC runtimes:

```yaml
aliyun_fc:
    role_arn: <ROLE_ARN>
    deploy_mode: custom-container
    docker_user: <your_dockerhub_username>
    docker_password: <your_dockerhub_token>
    docker_server: docker.io
```

Lithops builds a Linux/amd64 image, pushes it to **Docker Hub** (`docker.io`) by default, and creates an FC function with `runtime: custom-container`. The container must expose an HTTP server on `0.0.0.0:9000` (see [FC custom container docs](https://www.alibabacloud.com/help/en/functioncompute/fc/user-guide/custom-container/)). The service role must be able to pull the image.

Reference Dockerfile: [Dockerfile](Dockerfile). Example template: [start-fc custom-container/python](https://github.com/devsapp/start-fc/tree/V3/custom-container/python).

Build a custom container runtime from `requirements.txt`:

```
$ lithops runtime build -b aliyun_fc -f requirements.txt my_container_runtime
```

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

For instance, if you wish to integrate the `matplotlib` module into your runtime, which isn't part of the default setup, you need to append it to the existing [requirements.txt](requirements.txt) file. Note that this `requirements.txt` contains the mandatory packages required by Lithops, so you don't have to remove any of them from the list, but just add your packages at the end.

After updating the file accordingly, you can proceed to build the custom runtime by specifying the modified `requirements.txt` file along with a chosen runtime name:

```
$ lithops runtime build -b aliyun_fc -f requirements.txt my_matplotlib_runtime 
```

This command will build and deploy a runtime called `my_matplotlib_runtime` to the available Aliyun Functions Compute runtimes.

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

Note that both the client and the runtime must have the same Python version. If you are running Lithops, for example, with Python 3.10, `my_matplotlib_runtime` will be a Python 3.10 runtime with the extra modules specified installed.
