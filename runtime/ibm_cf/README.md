# Lithops runtime for IBM Cloud Functions

The runtime is the place where your functions are executed. In Lithops, runtimes are based on docker images, and it includes by default three different runtimes that allows you to run functions with Python 3.5, 3.6, 3.7 adn 3.8 environments. Lithops main runtime is responsible to execute Python functions within IBM Cloud Functions cluster. The strong requirement here is to match Python versions between the client and the runtime. The runtime may also contain additional packages which your code depends on.

Lithops for IBM Cloud is shipped with these default runtimes:

| Runtime name | Python version | Packages included |
| ----| ----| ---- |
| lithopscloud/ibmcf-python-v35 | 3.5 | [list of packages](requirements.txt) |
| lithopscloud/ibmcf-python-v36 | 3.6 | [list of packages](requirements.txt) |
| lithopscloud/ibmcf-python-v37 | 3.7 | [list of packages](requirements.txt) |
| lithopscloud/ibmcf-python-v38 | 3.8 | [list of packages](requirements.txt) |

The default runtime is created the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it.

Alternatively, you can create the default runtime by running the following command:

```bash
$ lithops runtime deploy default
```

To run a function with the default runtime you don't need to specify anything in the code, since everything is managed internally by Lithops:

```python
import lithops

def my_function(x):
    return x + 7

pw = lithops.FunctionExecutor()
pw.call_async(my_function, 3)
result = pw.get_result()
```

By default, Lithops uses 256MB as runtime memory size. However, you can change it in the `config` or when you obtain the executor, for example:

```python
import lithops
pw = lithops.FunctionExecutor(runtime_memory=512)
```

## Custom runtime

1. **Build your own Lithops runtime**

    If you need some Python modules (or other system libraries) which are not included in the default docker images (see table above), it is possible to build your own Lithops runtime with all of them.

    This alternative usage is based on to build a local Docker image, deploy it to the docker hub (you need a [Docker Hub account](https://hub.docker.com)) and use it as a Lithops base runtime.
    Project provides some base skeletons of Docker images for each supported python version, for example:

    * [Dockerfile](ibm_cf/Dockerfile.python36) - The image is based on `python:3.6-slim-buster`. 
    * [Dockerfile](ibm_cf/Dockerfile.python37) - The image is based on `python:3.7-slim-buster`. 
    * [Dockerfile](ibm_cf/Dockerfile.python38) - The image is based on `python:3.8-slim-buster`. 

    To build your own runtime, first install the Docker CE version in your client machine. You can find the instructions [here](https://docs.docker.com/get-docker/). If you already have Docker installed omit this step.

    Login to your Docker hub account by running in a terminal the next command.

        $ docker login

    Navigate to [ibm_cf/](imb_cf/) and update the Dockerfile that better fits to your requirements with your required system packages and Python modules.
    If you need another Python version, for example Python 3.8, you must use the [Dockerfile.python38](ibm_cf/Dockerfile.python38) that
    points to a source image based on Python 3.8. Finally run the build script:

        $ lithops runtime build docker_username/runtimename:tag

    Note that Docker hub image names look like *"docker_username/runtimename:tag"* and must be all lower case, for example:

        $ lithops runtime build jsampe/lithops-custom-runtime-3.8:0.1

    By default the Dockerfile should be located in the same folder from where you execute the **lithops runtime** command. If your Dockerfile is located in another folder, or the Dockerfile has another name, you can specify its location with the **-f** parameter, for example:

        $ lithops runtime build -f ibm_cf/Dockerfile.conda jsampe/lithops-conda-runtime-3.8:0.1

    Once you have built your runtime with all of your necessary packages, you can already use it with Lithops.
    To do so, you have to specify the full docker image name in the configuration or when you create the **ibm_cf_executor** instance, for example:

    ```python
    import lithops
    fexec = lithops.FunctionExecutor(runtime='jsampe/lithops-custom-runtime-3.8:0.1')
    ```

    *NOTE: In this previous example we built a Docker image based on Python 3.8, this means that now we also need Python 3.8 in the client machine.*

2. **Use an already built runtime from a public repository**

    Maybe someone already built a Docker image with all the packages you need, and put it in a public repository.
    In this case, you can use that Docker image and avoid the building process by simply specifying the image name when creating a new executor, for example:

    ```python
    import lithops
    fexec = lithops.FunctionExecutor(runtime='jsampe/lithops-conda-3.8:0.1')
    ```

    Alternatively, you can create a Lithops runtime based on already built Docker image by executing the following command, which will deploy all the necessary information to use the runtime with your Lithops.

        $ lithops runtime deploy docker_username/runtimename:tag

    For example, you can use an already built runtime based on Python 3.8 and with the *matplotlib* and *nltk* libraries by running:

        $ lithops runtime deploy jsampe/lithops-matplotlib-3.8:0.1

    Once finished, you can use the runtime in your Lithops code:

    ```python
    import lithops
    fexec = lithops.FunctionExecutor(runtime='jsampe/lithops-matplotlib:3.8:0.1')
    ```

## Runtime Management

1. **Update an existing runtime**

    If you are a developer, and modified the Lithops source code, you need to deploy the changes before executing Lithops.

    You can update default runtime by:

        $ lithops runtime update default

    You can update any other runtime deployed in your namespace by specifying the docker image that the runtime depends on:

        $ lithops runtime update docker_username/runtimename:tag

    For example, you can update an already created runtime based on the Docker image `jsampe/lithops-conda-3.8:0.1` by:

        $ lithops runtime update jsampe/lithops-conda-3.8:0.1

    Alternatively, you can update all the deployed runtimes at a time by:

        $ lithops runtime update all

2. **Delete a runtime**

    You can also delete existing runtimes in your namespace.

    You can delete default runtime by:

        $ lithops runtime delete default

    You can delete any other runtime deployed in your namespace by specifying the docker image that the runtime depends on:

        $ lithops runtime delete docker_username/runtimename:tag

    For example, you can delete runtime based on the Docker image `jsampe/lithops-conda-3.8:0.1` by:

        $ lithops runtime delete jsampe/lithops-conda-3.8:0.1

    You can delete all the runtimes at a time by:

        $ lithops runtime delete all

3. **Clean everything**

     You can clean everything related to Lithops, such as all deployed runtimes and cache information, and start from scratch by simply running the next command (Configuration is not deleted):

        $ lithops clean -b ibm_cf
