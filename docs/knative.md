# Lithops on Knative

Lithops with *Knative* as compute backend. Lithops also supports vanilla Knative for running applications. The easiest way to make it working is to create an IBM Kubernetes (IKS) cluster through the [IBM dashboard](https://cloud.ibm.com/kubernetes/landing). Alternatively you can use your own kubernetes cluster or a minikube installation.

### Installation

#### Option 1 (IBM IKS):

1. Access to the [IBM dashboard](https://cloud.ibm.com/kubernetes/landing) and create a new Kubernetes cluster. For testing purposes, it is preferable to use this setup:
    - Install Kubernetes >= v1.16
    - Select a **single zone** to place the worker nodes
    - *Master service endpoint*: Public endpoint only
    - Your cluster must have 3 or more worker nodes with at least 4 cores and 16GB RAM.
    - No need to encrypt local disk

2. Once the cluster is running, follow the instructions of the "Access" tab of the dashboard to configure the *kubectl* client in your local machine. 

3. In the dashboard of your cluster, go to the "Add-ons" tab and install Knative. It automatically installs Istio and Tekton.


#### Option 2 (IBM IKS or any other Kubernetes Cluster):

1. Install Kubernetes >= v1.16 and make sure the *kubectl* client is running.

2. Install the **helm** Kubernetes package manager in your local machine. Instructions can be found [here](https://github.com/helm/helm#install).

3. Install the Knative environment into the k8s cluster:
    ```
    curl http://cloudlab.urv.cat/knative/install_env.sh | bash
    ```

### Configuration

4. Make sure you have the ~/.kube/config file. Alternatively, you can set KUBECONFIG environment variable:
   ```bash
   export KUBECONFIG=<path-to-kube-config-file>
   ```

5. Edit your cloudbutton config file and add the following keys:
    ```yaml
    lithops:
        compute_backend: knative
        
    knative:
        docker_user: username
        docker_token: 12e9075f-6cd7-4147-a01e-8e34ffe9196e
    ```

#### Summary of configuration keys for Knative:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|knative | istio_endpoint | |no | Istio IngressGateway Endpoint. Make sure to use http:// prefix |
|knative | docker_user | |no | Docker hub username |
|knative | docker_token | |no | Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|knative | git_url | |no | Git repository to build the image |
|knative | git_rev | |no | Git revision to build the image |
|knative | cpu | 1000 |no | CPU limit in millicpu. Default 1vCPU (1000m) |


### Verify

6. Verify that all the pods from the following namespaces are in *Running* status: 
    ```bash
    kubectl get pods --namespace istio-system
    kubectl get pods --namespace knative-serving
    kubectl get pods --namespace knative-eventing
    kubectl get pods --namespace tekton-pipelines
    ```

7. Test if Lithops on Coligo is working properly:

   
   ```python
   from cloudbutton.engine.executor import FunctionExecutor
   
   def hello_world(name):
       return 'Hello {}!'.format(name)
    
   if __name__ == '__main__':
        cb_exec = FunctionExecutor()
        cb_exec.call_async(hello_world, 'World')
        print("Response from function: ", cb_exec.get_result())
   ```

8. Monitor how pods and other resources are created:
    ```bash
    watch kubectl get pod,service,revision,deployment -o wide
    ```
