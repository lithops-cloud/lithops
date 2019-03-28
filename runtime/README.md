# PyWren runtime for IBM Cloud Functions

PyWren runtime responsible to execute user function in the cloud.
PyWren main branch uses runtime that is based on a Conda environment. 
IBM Cloud Functions allows more freedom in this sense and it does not need the previous approach.
As IBM Cloud Functions allows to run a function within your own (self-built) Docker image as a base runtime,
this version of PyWren also uses Docker images as runtimes. In this sense, IBM PyWren uses by default 
the IBM Cloud Functions native Python docker image `python:3.6`. 

The main runtime is created by the following command:
    
    ./deploy_runtime

This script will automatically create a Python 3.6 action named `pywren_3.6` which is based on `--kind python:3.6` IBM docker image (Debian Jessie).
Note that in this version of PyWren the name of the action will be the name of the runtime, so the name of the runtime is, also, `pywren_3.6`.
The default runtime that PyWren uses is stated in the config file `~/.pywren_config`, so to run a function with this runtime you don't need
to specify anything in the code.
```python
import pywren_ibm_cloud as pywren

def my_function(x):
    return x + 7

pw = pywren.ibm_cf_executor()
pw.call_async(my_function, 3)
result = pw.get_result()
```

IMPORTANT: Make sure you have the same Python version on both the client and the server.
As stated before, the default runtime is based on Python 3.6, this means that you must have also Python 3.6 in you client machine.

Otherwise, if you need another Python version (like Python 3.5) because is not possible to update it in the client machine, or if you need some Python modules (or other system libraries)
which are not included in the [python:3.6](https://console.bluemix.net/docs/openwhisk/openwhisk_reference.html#openwhisk_ref_python_environments_3.6)
image, it is possible to build your own PyWren runtime with all of them.

1. **Build your own PyWren runtime**

    This alternative usage is based on to build a local Docker image, deploy it to the docker hub (you need a [Docker Hub account](https://hub.docker.com)) and use it as a PyWren base runtime.
    Project provides the skeleton of the Docker image:
    
    * [Dockerfile](Dockerfile) - The image is based on `python:3.6-slim-jessie`. 
    
    To create your own runtime, first install the Docker CE version in your client machine. You can find the instructions [here](https://docs.docker.com/install/). If you already have Docker installed omit this step.
    
    Login to your Docker hub account by running in a terminal the next command.
    
    	docker login
    
    Navigate to `runtime` and update the Dockerfile with your required packages and Python modules.
    If you need another Python version, for example Python 3.5, you must change the first line of the Dockerfile `FROM python:3.6-slim-jessie`
    to point to a source image based on Python 3.5, for example: `FROM python:3.5-slim-jessie`. Finally run the build script:
    
        ./deploy_runtime create docker_username/runtimename:tag
    
    Note that Docker hub image names look like *"docker_username/runtimename:tag"* and must be all lower case, for example:
    
    	./deploy_runtime create jsampe/pywren-custom-runtime:3.5
    
    Once you have built your runtime with all of your necessary packages, now you are able to use it with PyWren.
    To do so you have to specify the *runtimename* when you create the *ibm_cf_executor* instance, for example:
    ```python
    import pywren_ibm_cloud as pywren
    
    def my_function(x):
        return x + 7
    
    pw = pywren.ibm_cf_executor(runtime='pywren-custom-runtime_3.5')
    pw.call_async(my_function, 3)
    result = pw.get_result()
    ```
    
    *NOTE: In this previous example we built a docker image based on Python 3.5, this means that now we also need Python 3.5 in the client machine.*
  
Maybe someone already built a PyWren runtime with all the packages you need, and put it in a public repository.
In this case you can use that Docker image and avoid the building process.

2. **Use an already built runtime from a public repository**

    This alternative usage is based on to clone the Docker image (runtime) from a public repository.
    To do so execute the following command which will create all the necessary information to use the runtime with your PyWren.
    
        ./deploy_runtime clone docker_username/runtimename:tag
      
    For example, you can use an already created runtime based on Python 3.5 and with the *matplotlib* and *nltk* libraries by running:
    
        ./deploy_runtime clone jsampe/pw-mpl-nltk:3.5
        
    Once finished, you can use the runtime in your PyWren code:
    ```python
    import pywren_ibm_cloud as pywren
    
    def my_function(x):
        return x + 7
    
    pw = pywren.ibm_cf_executor(runtime='pw-mpl-nltk_3.5')
    pw.call_async(my_function, 3)
    result = pw.get_result()
    ```
    
Note that if you put a tag in the docker image name, the ':' character will be replaced with a '_' in the runtime name.
For example, if you put `jsampe/pw-mpl-nltk:3.5` as a Docker image name in the *create* or *clone* commands, then the name of the runtime will be `pw-mpl-nltk_3.5` as in the previous examples.

In order to use them from IBM Cloud functions, you have to login to your [Docker Hub account](https://hub.docker.com) and ensure that the image is **public**.
