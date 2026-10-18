# Knative

Lithops with [Knative Serving](https://knative.dev/docs/serving/) as serverless compute backend. Each runtime is deployed as a Knative service that runs one function call per container at a time, scales up to `max_workers` containers, and scales down to zero when it is idle.

The backend is tested with Knative Serving 1.23 and works with any Kubernetes cluster where Knative Serving runs: a managed cluster (EKS, GKE, AKS, IKS, ...), your own cluster, or a local [kind](https://kind.sigs.k8s.io/) or minikube cluster.

## Installation

1. Install the Knative backend dependencies:

    ```bash
    python3 -m pip install lithops[knative]
    ```

2. Make sure `kubectl` reaches your cluster, either through `~/.kube/config` or the `KUBECONFIG` environment variable.

3. [Install Knative Serving](https://knative.dev/docs/install/yaml-install/serving/install-serving-with-yaml/) and one of its networking layers: **Kourier** (the default in Lithops), **Istio** or **Contour**.

4. Configure a domain for Knative, so that its services can be reached from outside the cluster. Knative uses `svc.cluster.local` by default, which only routes requests that come from inside the cluster. Follow [Configure DNS](https://knative.dev/docs/install/yaml-install/serving/install-serving-with-yaml/#configure-dns): *Magic DNS* (`sslip.io`) when the ingress has a load balancer, a real domain, or, for a test cluster, any domain such as `example.com`:

    ```bash
    kubectl patch configmap/config-domain -n knative-serving --type merge -p '{"data":{"example.com":""}}'
    ```

5. Install Docker. Lithops builds the default runtime with it the first time you run a function, and pushes it to your container registry.

### Local cluster with kind

On a laptop, a kind cluster with a [local registry](https://kind.sigs.k8s.io/docs/user/local-registry/) needs no account anywhere:

1. Create the cluster and the `localhost:5001` registry as the kind guide explains, then install Knative Serving and Kourier as above, and set the `example.com` domain.

2. Knative resolves image tags to digests from inside the cluster, where `localhost:5001` is not the registry. Tell it to skip that registry:

    ```bash
    kubectl patch configmap/config-deployment -n knative-serving --type merge \
      -p '{"data":{"registries-skipping-tag-resolving":"kind.local,ko.local,dev.local,localhost:5001"}}'
    ```

3. The addresses of the kind nodes are not reachable from macOS or Windows. Forward the ingress to your machine, and keep it running:

    ```bash
    kubectl port-forward -n kourier-system svc/kourier 8080:80
    ```

4. Configure Lithops with:

    ```yaml
    knative:
        kubecfg_context: kind-<cluster name>
        docker_server: localhost:5001
        ingress_endpoint: http://127.0.0.1:8080
    ```

## Configuration

1. Edit your Lithops config and add the following keys:

    ```yaml
    lithops:
        backend: knative
    ```

2. Lithops finds the ingress of the networking layer by itself: its load balancer when it has one, or else the node port of a node. If the ingress is reachable at another address (a port forward, a DNS name), set it in `ingress_endpoint`. If the services can be reached at their own URL, as with Magic DNS, Lithops calls them there when it finds no ingress.

3. When Lithops itself runs inside the cluster, it calls the services at their cluster-local address, and needs neither the ingress nor a domain.

### Configure a private container registry for your runtime

#### Configure Docker Hub
To configure Lithops to access a private repository in your Docker Hub account, you need to extend the Knative config and add the following keys:

```yaml
knative:
    ....
    docker_server    : docker.io
    docker_user      : <Docker Hub username>
    docker_password  : <Docker Hub access token>
```

#### Configure IBM Container Registry
To configure Lithops to access to a private repository in your IBM Container Registry, you need to extend the Knative config and add the following keys:

```yaml
knative:
    ....
    docker_server    : us.icr.io
    docker_user      : iamapikey
    docker_password  : <IBM IAM API KEY>
    docker_namespace : <namespace>  # namespace name from https://cloud.ibm.com/registry/namespaces
```

With registry credentials, Lithops creates the `lithops-regcred` secret in the namespace, which Knative and the kubelet use to pull the runtime image.

## Summary of configuration keys for Knative:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|knative | kubecfg_path | |no | Path to kubecfg file. Mandatory if config file not in `~/.kube/config` or KUBECONFIG env var not present|
|knative | kubecfg_context | |no | kubeconfig context to use. The current context by default |
|knative | namespace | |no | Namespace of the Knative services. The namespace of the kubeconfig context, or `default` |
|knative | networking_layer | kourier |no | One of: **kourier**, **istio** or **contour**. Used to find the ingress  |
|knative | ingress_endpoint | |no | Ingress endpoint, with the `http://` prefix. Found automatically when not set |
|knative | docker_server | docker.io |no | Container registry URL |
|knative | docker_user | |no | Container registry user name |
|knative | docker_password | |no | Container registry password/token. For Docker Hub, log in to your Docker Hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|knative | docker_namespace | |no | Container registry namespace, for registries that need one, such as IBM Container Registry |
|knative | max_workers | 100 | no | Max number of workers per `FunctionExecutor()`, which is the maximum number of containers of each service|
|knative | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommended to set this value to the same number of CPUs as the container. |
|knative | runtime |  |no | Docker image name|
|knative | runtime_cpu | 1 |no | CPU limit. Default 1vCPU |
|knative | runtime_memory | 512 |no | Memory limit in MB. Default 512 |
|knative | runtime_timeout | 600 |no | Runtime timeout in seconds. Default 600 seconds. Knative refuses services with a timeout over its `max-revision-timeout-seconds` setting, 600 seconds unless you raise it in the `config-defaults` ConfigMap |
|knative | runtime_arch | |no | `amd64` or `arm64`: the platform of the runtime image Lithops builds. The architecture of the cluster nodes by default, or `amd64` |

### Verify

1. Verify that all the pods of Knative are in *Running* status:
    ```bash
    kubectl get pods -n knative-serving
    ```

2. Monitor how the services, revisions and pods are created:
    ```bash
    watch kubectl get ksvc,revision,pod -o wide
    ```

## Test Lithops

Once you have your compute and storage backends configured, you can run a Hello World function with:

```bash
lithops hello -b knative -s aws_s3
```

The workers read and write their data in the storage backend, so it has to be reachable from the cluster as well as from your machine.

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```
