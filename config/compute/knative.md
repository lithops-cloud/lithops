# Lithops on Knative

Lithops with *Knative* as serverless compute backend. Lithops also supports vanilla Knative for running applications. The easiest way to make it working is to create an IBM Kubernetes (IKS) cluster through the [IBM dashboard](https://cloud.ibm.com/kubernetes/landing). Alternatively you can use your own kubernetes cluster or a minikube installation.

### Installation

Note that Lithops automatically builds the default runtime the first time you run a script. For this task it uses the **docker** command installed locally in your machine. If for some reason you can't install the Docker CE package locally, you must provide the **docker_token** parameter in the configuration. This way lithops will use Tekton of your k8s cluster to build the default runtime to your docker hub account. In this case, omit steps 1 and 2.

1. [Install the Docker CE version](https://docs.docker.com/get-docker/).

2. Login to your docker account:
   ```bash
   docker login
   ```

3. Choose one of these 2 installation options:

#### Option 1 (IBM IKS):

4. Access to the [IBM dashboard](https://cloud.ibm.com/kubernetes/landing) and create a new Kubernetes cluster. For testing purposes, it is preferable to use this setup:
    - Install Kubernetes >= v1.16
    - Select a **single zone** to place the worker nodes
    - *Master service endpoint*: Public endpoint only
    - Your cluster must have 3 or more worker nodes with at least 4 cores and 16GB RAM.
    - No need to encrypt local disk

5. Once the cluster is running, follow the instructions of the "Access" tab of the dashboard to configure the *kubectl* client in your local machine. 

6. In the dashboard of your cluster, go to the "Add-ons" tab and install Knative. It automatically installs Istio and Tekton.


#### Option 2 (IBM IKS or any other Kubernetes Cluster):

4. Install Kubernetes >= v1.16 and make sure the *kubectl* client is running.

5. Install the **helm** Kubernetes package manager in your local machine. Instructions can be found [here](https://github.com/helm/helm#install).

6. Install the Knative environment into the k8s cluster:
    ```
    curl http://cloudlab.urv.cat/knative/install_env.sh | bash
    ```

### Configuration

7. Make sure you have the ~/.kube/config file. Alternatively, you can set KUBECONFIG environment variable:
   ```bash
   export KUBECONFIG=<path-to-kube-config-file>
   ```

8. Edit your lithops config and add the following keys:
    ```yaml
    lithops:
        backend: knative
    ```

### Configure a private container registry for your runtime

#### Configure Docker hub
To configure Lithops to access a private repository in your docker hub account, you need to extend the Knative config and add the following keys:

```yaml
knative:
    ....
    docker_user      : <Docker hub Username>
    docker_password  : <DOcker hub access TOEKN>
```

#### Configure IBM Container Registry
To configure Lithops to access to a private repository in your IBM Container Registry, you need to extend the Knative config and add the following keys:

```yaml
knative:
    ....
    docker_server    : us.icr.io
    docker_user      : iamapikey
    docker_password  : <IBM IAM API KEY>
```

#### Summary of configuration keys for Knative:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|knative | istio_endpoint | |no | Istio IngressGateway Endpoint. Make sure to use http:// prefix |
|knative | kubecfg_path | |no | Path to kubecfg file. Mandatory if config file not in `~/.kube/config` or KUBECONFIG env var not present|
|knative | docker_server | https://index.docker.io/v1/ |no | Docker server URL |
|knative | docker_user | |no | Docker hub username |
|knative | docker_password | |no | Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|knative | git_url | |no | Git repository to build the image |
|knative | git_rev | |no | Git revision to build the image |
|knative | max_workers | 250 | no | Max number of workers per `FunctionExecutor()`|
|knative | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of the container. |
|knative | runtime |  |no | Docker image name|
|knative | runtime_cpu | 0.5 |no | CPU limit. Default 0.5vCPU |
|knative | runtime_memory | 256 |no | Memory limit in MB. Default 256Mi |
|knative | runtime_timeout | 600 |no | Runtime timeout in seconds. Default 600 seconds |
|knative | invoke_pool_threads | {lithops.workers} |no | Number of concurrent threads used for invocation |


### Verify

9. Verify that all the pods from the following namespaces are in *Running* status: 
    ```bash
    kubectl get pods --namespace istio-system
    kubectl get pods --namespace knative-serving
    kubectl get pods --namespace knative-eventing
    kubectl get pods --namespace tekton-pipelines
    ```

10. Monitor how pods and other resources are created:
    ```bash
    watch kubectl get pod,service,revision,deployment -o wide
    ```
