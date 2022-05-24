# Knative

Lithops with *Knative* as serverless compute backend. Lithops also supports vanilla Knative for running applications. The easiest way to make it working is to create an IBM Kubernetes (IKS) cluster through the [IBM dashboard](https://cloud.ibm.com/kubernetes/landing). Alternatively you can use your own kubernetes cluster or a kind/minikube installation.

## Installation

Note that Lithops automatically builds the default runtime the first time you run a script. For this task it uses the **docker** command installed locally in your machine.

1. [Install the Docker CE version](https://docs.docker.com/get-docker/).

2. Login to your docker account:
   ```bash
   docker login
   ```

3. Choose one of these 2 installation options:

### Option 1 (IBM IKS):

4. Access to the [IBM dashboard](https://cloud.ibm.com/kubernetes/landing) and create a new Kubernetes cluster.

5. Once the cluster is running, follow the instructions of the "Actions"--> "Connect via CLI" option of the dashboard to configure the *kubectl* client in your local machine. 

6. [Follow this instructions to install knative serving.](https://knative.dev/docs/install/yaml-install/serving/install-serving-with-yaml/)

7. Install a networking layer. Currently lithops supports **Istio**. [Follow these instructions to install Istio.](https://knative.dev/docs/install/yaml-install/serving/install-serving-with-yaml/#install-a-networking-layer)


### Option 2 (IBM IKS or any other Kubernetes Cluster):

4. Install Kubernetes >= v1.16 and make sure the *kubectl* client is running.

6. [Follow this instructions to install knative serving.](https://knative.dev/docs/install/yaml-install/serving/install-serving-with-yaml/)

7. Install a networking layer. Currently Lithops supports **Istio**. [Follow these instructions to install Istio.](https://knative.dev/docs/install/yaml-install/serving/install-serving-with-yaml/#install-a-networking-layer)


## Configuration

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
    docker_server    : docker.io
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

## Summary of configuration keys for Knative:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|knative | istio_endpoint | |no | Istio IngressGateway Endpoint. Make sure to use http:// prefix |
|knative | kubecfg_path | |no | Path to kubecfg file. Mandatory if config file not in `~/.kube/config` or KUBECONFIG env var not present|
|knative | docker_server | docker.io |no | Docker server URL |
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
    kubectl get pods -n knative-serving
    ```

10. Monitor how pods and other resources are created:
    ```bash
    watch kubectl get pod,service,revision,deployment -o wide
    ```
