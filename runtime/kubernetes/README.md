# Lithops runtime for Kubernetes

The runtime is the place where the functions are executed. In Kubernetes, runtimes are based on docker images. 

For running lithops on kubernetes, you need a runtime build on the docker hub (or any other container registry), or you need a docker hub account for placing the runtimes created by lithops.

If you don't have an already built runtime, the default runtime is built the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it.


By default, Lithops uses 256MB as runtime memory size and 0.5vCPU for the kubernetes runtimes. However, you can change it in the `config` by setting the appropriate vCPU size:

```yaml
k8s:
    runtime_memory: 512
    runtime_cpu: 1
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
    If you need another Python version, for example Python 3.12, you must change the initial line of the Dockefile:

        $ lithops runtime build -b k8s docker_username/runtimename:tag

    Note that Docker hub image names look like *"docker_username/runtimename:tag"* and must be all lower case, for example:

        $ lithops runtime build -b k8s myaccount/lithops-k8s-custom-v312:01

    By default the Dockerfile should be located in the same folder from where you execute the **lithops runtime** command. If your Dockerfile is located in another folder, or the Dockerfile has another name, you can specify its location with the **-f** parameter, for example:

        $ lithops runtime build -b k8s -f kubernetes/Dockerfile.conda myaccount/lithops-k8s-custom-v312:01

    Once you have built your runtime with all of your necessary packages, you can already use it with Lithops.
    To do so, you have to specify the full docker image name in the configuration or when you create the **FunctionExecutor** instance, or directly in the config file, for example:

    ```python
    import lithops
    fexec = lithops.FunctionExecutor(runtime='myaccount/lithops-k8s-custom-v312:01')
    ```

    *NOTE: In this previous example shows how to build a Docker image based on Python 3.12, this means that now you also need Python 3.12 in the client machine.*

2. **Use an already built runtime from a public repository**

    Maybe someone already built a Docker image with all the packages you need, and put it in a public repository.
    In this case, you can use that Docker image and avoid the building process by simply specifying the image name when creating a new executor, for example:

    ```python
    import lithops
    fexec = lithops.FunctionExecutor(runtime='docker.io/lithopscloud/lithops-k8s-conda-v312:01')
    ```

    Alternatively, you can create a Lithops runtime based on already built Docker image by executing the following command, which will deploy all the necessary information to use the runtime with your Lithops.

    ```
    $ lithops runtime deploy -b k8s docker_username/runtimename:tag
    ```

    For example, you can use an already buit runtime based on Python 3.12 and with the *matplotlib* and *nltk* libraries by running:

    ```
    $ lithops runtime deploy -b k8s docker.io/lithopscloud/lithops-k8s-matplotlib-v312:01
    ```

    ```python
    import lithops
    fexec = lithops.FunctionExecutor(runtime='docker.io/lithopscloud/lithops-k8s-matplotlib:v312:01')
    ```

3. **Clean everything**

     You can clean everything related to Lithops, such as all deployed runtimes and cache information, and start from scratch by simply running the next command (Configuration is not deleted):

        $ lithops clean -b k8s
