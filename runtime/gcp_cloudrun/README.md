# Lithops runtime for Google Cloud Run

The runtime is the place where the functions are executed. In Google Cloud Run, runtimes are based on container images.

Google Cloud Run requires container images to be pushed to Google Cloud Container Registry (images pushed to Dockerhub are not permitted).

Lithops automatically tags and pushes the image to GCR with authentication from the service account key file. 

If you don't have an already built runtime, the default runtime is built the first time you execute a function. Lithops automatically detects the Python version of your environment and deploys the default runtime based on it.

Alternatively, you can create the default runtime by running the following command:

```bash
$ lithops runtime deploy default -b gcp_cloudrun -s gcp_storage
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

By default, Lithops uses 256MB as runtime memory size. However, you can change it in the `config` or when you obtain the executor, for example:

```python
import lithops
pw = lithops.FunctionExecutor(runtime_memory=512)
```

By default, Lithops uses 1vCPU for the Google Cloud Run runtimes. However, you can change it in the `config` by setting the appropiate vCPU size in vCPUs units.

```yaml
gcp_cloudrun:
    runtime_cpu: 2
```

## Custom runtime

1. **Build your own Lithops runtime**

    If you need some Python modules (or other system libraries) which are not included in the default container image, it is possible to build your own Lithops runtime with all of them.

    This alternative usage is based on to build a local container image, deploy it to GCR and use it as a Lithops base runtime.
    Project provides some skeletons of Docker images, for example:

    * [Dockerfile](Dockerfile) 

    To build your own runtime, first install the Docker CE version in your client machine. You can find the instructions [here](https://docs.docker.com/get-docker/). If you already have Docker installed omit this step.

    Update the Dockerfile that better fits to your requirements with your required system packages and Python modules.
    If you need another Python version, for example Python 3.12, you must change the initial line of the Dockefile.
    
    For example, we will add `PyTorch` to our Lithops runtime. The Dockerfile would look like this:
    ```dockerfile
    FROM python:3.12-slim-bookworm
    
    RUN apt-get update && apt-get install -y \
            zip \
            && rm -rf /var/lib/apt/lists/*
    
    RUN pip install --upgrade setuptools six pip \
        && pip install --no-cache-dir \
            gunicorn \
            pika \
            flask \
            gevent \
            ibm-cos-sdk \
            redis \
            requests \
            PyYAML \
            kubernetes \
            numpy \
            cloudpickle \
            ps-mem \
            tblib \
            namegenerator \
            torch \
            torchvision \
            google-cloud-storage \
            google-api-python-client \
            google-auth
    
    ENV PYTHONUNBUFFERED TRUE
    
    # Copy Lithops proxy and lib to the container image.
    ENV APP_HOME /lithops
    WORKDIR $APP_HOME
    
    COPY lithops_cloudrun.zip .
    RUN unzip lithops_cloudrun.zip && rm lithops_cloudrun.zip
    
    CMD exec gunicorn --bind :$PORT lithopsproxy:proxy
    ```
    
    We can then build the custom runtime named `pytorchruntime`. 

        $ lithops runtime build -b gcp_cloudrun pytorchruntime

    By default the Dockerfile should be located in the same folder from where you execute the **lithops runtime** command. If your Dockerfile is located in another folder, or the Dockerfile has another name, you can specify its location with the **-f** parameter, for example:

        $ lithops runtime build -b gcp_cloudrun -f PyTorchDockerfile pytorchruntime

    Once you have built your runtime with all of your necessary packages, you can already use it with Lithops.
    To do so, you have to specify the runtime name in the configuration or when you create the **FunctionExecutor** instance, or directly in the config file, for example:

    ```python
    import lithops
    
    def my_function(x):
        import torch
        return torch.__repr__()
   
    fexec = lithops.FunctionExecutor(runtime='pytorchruntime')
    fexec.call_async(my_function, 'hello')
    print(fexec.get_result())  # Prints <module 'torch' from '/usr/local/lib/python3.12/site-packages/torch/__init__.py'>
    ```

## Runtime Management

1. **Update an existing runtime**

    If you are a developer, and modified the Lithops source code, you need to deploy the changes before executing Lithops.

    You can update default runtime by:

        $ lithops runtime update default -b gcp_cloudrun -s gcp_storage

    You can update any other runtime deployed in your namespace by specifying the runtime name:

        $ lithops runtime update myruntime -b gcp_cloudrun -s gcp_storage

    Alternatively, you can update all the deployed runtimes at a time by:

        $ lithops runtime update all -b gcp_cloudrun -s gcp_storage

2. **Delete a runtime**

    You can also delete existing runtimes in your namespace.

    You can delete default runtime by:

        $ lithops runtime delete default -b gcp_cloudrun -s gcp_storage

    You can delete any other runtime deployed in your namespace by specifying the runtime name:

        $ lithops runtime delete myruntime -b gcp_cloudrun -s gcp_storage

    You can delete all the runtimes at a time by:

        $ lithops runtime delete all -b gcp_cloudrun -s gcp_storage

3. **Clean everything**

     You can clean everything related to Lithops, such as all deployed runtimes and cache information, and start from scratch by simply running the next command (Configuration is not deleted):

        $ lithops clean -b gcp_cloudrun -s gcp_storage
