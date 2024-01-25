# Lithops runtime for IBM Code Engine

The runtime is the place where the functions are executed. In IBM Code Engine, runtimes are based on docker images, in this sense you can run functions using any Python version > 3.6.

For running lithops on Code Engine, you need a runtime build on the docker hub (or any other container registry), or you need a docker hub account for placing the runtimes automatically created by lithops.

If you don't have an already built runtime, the default runtime is built the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it.

Alternatively, you can create the default runtime by running the following command:

```bash
$ lithops runtime deploy default -b code_engine -s ibm_cos
```

To run a function with the default runtime you don't need to specify anything in the code, since everything is managed internally by Lithops:

```python
import lithops

def my_function(x):
    return x + 7

fexec = lithops.FunctionExecutor()
fexec.call_async(my_function, 3)
result = fexec.get_result()
```

By default, Lithops uses 256MB as runtime memory size and 0.125vCPU for the Code Engine runtimes. However, you can change it in the `config` by setting the appropriate vCPU  and memory sizes:

```yaml
code_enigne:
    runtime_memory: 256
    runtime_cpu: 0.5
```


## Custom runtime

1. **Build your own Lithops runtime**

    If you need some Python modules (or other system libraries) which are not included in the default docker images (see table above), it is possible to build your own Lithops runtime with all of them.

    This alternative usage is based on to build a local Docker image, deploy it to the docker hub (you need a [Docker Hub account](https://hub.docker.com)) and use it as a Lithops base runtime.
    Project provides some skeletons of Docker images, for example:

    * [Dockerfile](Dockerfile) 

    To build your own runtime, first install the Docker CE version in your client machine. You can find the instructions [here](https://docs.docker.com/get-docker/). If you already have Docker installed omit this step.

    Login to your Docker hub account by running in a terminal the next command.

        $ docker login

    Update the Dockerfile that better fits to your requirements with your required system packages and Python modules.
    If you need another Python version, for example Python 3.9, you must change the initial line of the Dockefile:

        $ lithops runtime build docker_username/runtimename:tag -b code_engine

    Note that Docker hub image names look like *"docker_username/runtimename:tag"* and must be all lower case, for example:

        $ lithops runtime build -b code_engine myaccount/lithops-ce-custom-v39:01

    By default the Dockerfile should be located in the same folder from where you execute the **lithops runtime** command. If your Dockerfile is located in another folder, or the Dockerfile has another name, you can specify its location with the **-f** parameter, for example:

        $ lithops runtime build -b code_engine -f code_engine/Dockerfile.conda myaccount/lithops-ce-custom-v39:01

    Once you have built your runtime with all of your necessary packages, you can already use it with Lithops.
    To do so, you have to specify the full docker image name in the configuration or when you create the **FunctionExecutor** instance, or directly in the config file, for example:

    ```python
    import lithops
    fexec = lithops.FunctionExecutor(runtime='myaccount/lithops-ce-custom-v39:01')
    ```

    *NOTE: In this previous example shows how to build a Docker image based on Python 3.9, this means that now you also need Python 3.9 in the client machine.*

2. **Use an already built runtime from a public repository**

    Maybe someone already built a Docker image with all the packages you need, and put it in a public repository.
    In this case, you can use that Docker image and avoid the building process by simply specifying the image name when creating a new executor, for example:

    ```python
    import lithops
    fexec = lithops.FunctionExecutor(runtime='lithopscloud/ce-conda-v39:01')
    ```

    Alternatively, you can create a Lithops runtime based on already built Docker image by executing the following command, which will deploy all the necessary information to use the runtime with your Lithops.

        $ lithops runtime deploy -b code_engine -s ibm_cos docker_username/runtimename:tag

    For example, you can use an already created runtime based on Python 3.9 and with the *matplotlib* and *nltk* libraries by running:

        $ lithops runtime deploy -b code_engine -s ibm_cos lithopscloud/ce-matplotlib-v39:01

    Once finished, you can use the runtime in your Lithops code:

    ```python
    import lithops
    fexec = lithops.FunctionExecutor(runtime='lithopscloud/ce-matplotlib:v39:01')
    ```

## Runtime Management

1. **Update an existing runtime**

    If you are a developer, and modified the PyWeen source code, you need to deploy the changes before executing Lithops.

    You can update default runtime by:

        $ lithops runtime update default -b code_engine -s ibm_cos

    You can update any other runtime deployed in your namespace by specifying the docker image that the runtime depends on:

        $ lithops runtime update docker_username/runtimename:tag -b code_engine -s ibm_cos

    For example, you can update an already created runtime based on the Docker image `lithopscloud/ce-matplotlib-v39:01` by:

        $ lithops runtime update lithopscloud/ce-matplotlib-v39:01 -b code_engine -s ibm_cos

    Alternatively, you can update all the deployed runtimes at a time by:

        $ lithops runtime update all -b code_engine -s ibm_cos

2. **Delete a runtime**

    You can also delete existing runtimes in your namespace.

    You can delete default runtime by:

        $ lithops runtime delete default -b code_engine -s ibm_cos

    You can delete any other runtime deployed in your namespace by specifying the docker image that the runtime depends on:

        $ lithops runtime delete docker_username/runtimename:tag -b code_engine -s ibm_cos

    For example, you can delete runtime based on the Docker image `lithopscloud/ce-conda-v39:01` by:

        $ lithops runtime delete lithopscloud/ce-conda-v39:01 -b code_engine -s ibm_cos

    You can delete all the runtimes at a time by:

        $ lithops runtime delete all -b code_engine -s ibm_cos

3. **Clean everything**

     You can clean everything related to Lithops, such as all deployed runtimes and cache information, and start from scratch by simply running the next command (Configuration is not deleted):

        $ lithops clean -b code_engine -s ibm_cos
