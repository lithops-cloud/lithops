# PyWren on Knative

The easiest way to make it working is to create an IBM Kubernetes (IKS) cluster trough the [IBM dashboard](https://cloud.ibm.com/kubernetes/landing). For testing purposes, it is preferable to use this setup:
- Install Kubernetes >= v1.15
- Select a **single zone** to place the worker nodes
- *Master service endpoint*: Public endpoint only
- Your cluster must have 3 or more worker nodes with at least 4 cores and 16GB RAM.
- No need to encrypt local disk

Once the cluster is running, follow the instructions of the "Access" tab to configure the *kubectl* client in your local machine. Then, follow one of this two options to install the PyWren environment:

  - Option 1 (IBM IKS):

    1. In the Dashboard of your cluster, go to the "Add-ons" tab and install knative v0.12.1. It automatically installs Istio v1.4 and Tekton v0.10.1.


  - Option 2 (IBM IKS or any other Kubernetes Cluster):

    1. Install the **helm** Kubernetes package manager in your local machine. Instructions can be found [here](https://github.com/helm/helm#install).

    2. Install the PyWren environment into the k8s cluster: Istio v1.4.6, Knative v0.14.0 and Tekton v0.11.1:
        ```
        curl http://cloudlab.urv.cat/josep/knative/install_pywren_env.sh | bash
        ```

**Before running** any pywren operation, **first** get or create k8s config file and set it in KUBECONFIG environment variable. For example in ~/.kube/config, or if you are using IKS cluster, download the kubeconfig files by (follow instructions in the access dashboard):
		
	ibmcloud ks cluster config --cluster <ID from IKS access dashboard>

Set the KUBECONFIG environment variable:

	export KUBECONFIG=<path-to-kube-config-file>

#### Verify that all the pods from the following namespaces are in *Running* status: 
```
kubectl get pods --namespace istio-system
kubectl get pods --namespace knative-serving
kubectl get pods --namespace knative-eventing
kubectl get pods --namespace tekton-pipelines
```


#### Edit your pywren config file and add the next section:

```yaml
pywren:
    compute_backend: knative
    
knative:
    docker_user: username
    docker_token: 12e9075f-6cd7-4147-a01e-8e34ffe9196e
```
- **docker_token**: Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)



#### Test if PyWren on Knative is working properly:

Run the next command:

```bash
$ pywren-ibm-cloud test
```

or run the next Python code:

```python
import pywren_ibm_cloud as pywren

def hello_world(name):
    return 'Hello {}!'.format(name)

if __name__ == '__main__':
    kn = pywren.knative_executor()
    kn.call_async(hello_world, 'World')
    print("Response from function: ", kn.get_result())
```


#### Monitor how pods and other resources are created:

```
watch kubectl get pod,service,revision,deployment -o wide
```