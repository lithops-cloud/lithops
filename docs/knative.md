# PyWren on Knative

The easiest way to make it working is to create an IBM Kuberentes (IKS) cluster (1.15.3) trough the [IBM dashboard](https://cloud.ibm.com/kubernetes/landing). You must create a cluster with at least 3 worker nodes, each one with a minimum flavor of 4vCPU and 16GB RAM.


Once created, follow instructions of the "Access" tab to configure the kubectl clt in your local machine. Then:

1. Install tekton>=0.6: `kubectl apply --filename https://storage.googleapis.com/tekton-releases/latest/release.yaml`
2. Go to the "Add-ons" tab and install knative (It will automatically install Istio as a dependency)
3. Wait until all pods are in Running state: `kubectl get pods --namespace knative-serving; kubectl get pods --namespace knative-eventing; kubectl get pods --namespace knative-monitoring`

Once all pods are ready, edit *~/.pywren_config* and add the next section:

```yaml
knative:
      endpoint: http://ip-or-url.com:31380  # istio-ingressgateway endpoint
      docker_user: my-username
      docker_token: 12e9075f-6cd7-4147-a01e-8e34ffe9196e
```

- **endpoint**: You can obtain the istio-ingressgateway endpoint by running: 
`echo http://$(kubectl get svc istio-ingressgateway --namespace istio-system --output 'jsonpath={.status.loadBalancer.ingress[0].ip}'):$(kubectl get svc istio-ingressgateway --namespace istio-system --output 'jsonpath={.spec.ports[?(@.port==80)].nodePort}')`

- **docker_token**: Login to your docker hub account and generate a new docker access token [here](https://hub.docker.com/settings/security)

To finish the process, test if everything is working:

```python
import pywren_ibm_cloud as pywren

def my_function(x):
    return x + 7

if __name__ == '__main__':
    kn = pywren.knative_executor()
    kn.call_async(my_function, 3)
    print (pw.get_result())
```

You can see in another terminal how pods and other resources are created with:

```
export KUBECONFIG=/home/... (Same as before in "Access" tab)
watch kubectl get pod,revision,service,deployment -o wide
```