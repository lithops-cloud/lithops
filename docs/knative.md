# PyWren on Knative (Experimental)

The easiest way to make it working is to create an IBM Kubernetes (IKS) cluster trough the [IBM dashboard](https://cloud.ibm.com/kubernetes/landing). At this moment, for testing purposes, it is preferable to use this setup:
- Install Kubernetes v1.15.3
- Select a **single zone** to place the worker nodes
- *Master service endpoint*: Public endpoint only
- You must create a cluster with at least 3 worker nodes, each one with a minimum flavor of 4vCPU and 16GB RAM.

Then, follow these steps:

1. Wait until the cluster is created. Then follow the instructions of the "Access" tab to configure the *kubectl* client in your local machine.

2. Install tekton>=0.6: 
    ```
    kubectl apply --filename https://storage.googleapis.com/tekton-releases/latest/release.yaml`
    ```
    Wait until all pods in `kubectl get pods --namespace tekton-pipelines` are in *Running* status.

3. In the IBM Dashboard of your cluster, go to the "Add-ons" tab and install knative (It will automatically install Istio as dependency)
    Wait until all the pods from the output of these commands are in Running status: 
    ```
    kubectl get pods --namespace istio-system
    kubectl get pods --namespace knative-serving
    kubectl get pods --namespace knative-eventing
    kubectl get pods --namespace knative-monitoring
    ```

4. Edit *~/.pywren_config* and add the next section:

    ```yaml
    knative:
          endpoint: http://ip-or-url.com:31380  # istio-ingressgateway endpoint
          docker_user: my-username
          docker_token: 12e9075f-6cd7-4147-a01e-8e34ffe9196e
    ```

    - **endpoint**: You can obtain the istio-ingressgateway endpoint by running:
        ```
        echo http://$(kubectl get svc istio-ingressgateway --namespace istio-system --output 'jsonpath={.status.loadBalancer.ingress[0].ip}'):$(kubectl get svc istio-ingressgateway --namespace istio-system --output 'jsonpath={.spec.ports[?(@.port==80)].nodePort}')
        ```

    - **docker_token**: Login to your docker hub account and generate a new docker access token [here](https://hub.docker.com/settings/security)

To finish the process, test if everything is working properly:

```python
import pywren_ibm_cloud as pywren

def my_function(x):
    return x + 7

if __name__ == '__main__':
    kn = pywren.knative_executor()
    kn.call_async(my_function, 3)
    print(kn.get_result())
```

You can see in another terminal how pods and other resources are created with:

```
export KUBECONFIG=/home/... (Same as before in "Access" tab)
watch kubectl get pod,revision,service,deployment -o wide
```