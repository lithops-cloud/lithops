# Kubernetes

Lithops with kubernetes as serverless compute backend.

## Installation

1. Install kubernetes backend dependencies:

```bash
python3 -m pip install lithops[kubernetes]
```

## Configuration

1. Edit your Lithops config and add the following keys:

```yaml
  lithops:
      backend : k8s
```

2. Make sure you have a kubernetes cluster configuration file.
   - Option 1: You have the config file in `~/.kube/config`

   - Option 2: You have the config file in another location, and you exported the KUBECONFIG variable:
     ```bash
     export KUBECONFIG=<path-to-kube-config-file>
     ```

   - Option 3: You have the config file in another location, and you set the `kubecfg_path` var in the Lithops config:
     ```yaml
     k8s:
         kubecfg_path: <path-to-kube-config-file>
     ```

## Configure a private container registry for your runtime

### Configure Docker hub
To configure Lithops to access a private repository in your docker hub account, you need to extend the kubernetes config and add the following keys:

```yaml
k8s:
    ....
    docker_server    : docker.io
    docker_user      : <Docker hub Username>
    docker_password  : <DOcker hub access TOEKN>
```

### Configure IBM Container Registry
To configure Lithops to access to a private repository in your IBM Container Registry, you need to extend the kubernetes config and add the following keys:

```yaml
k8s:
    ....
    docker_server    : us.icr.io
    docker_user      : iamapikey
    docker_password  : <IBM IAM API KEY>
    docker_namespace : <namespace>  # namespace name from https://cloud.ibm.com/registry/namespaces
```

## Summary of configuration keys for kubernetes:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|k8s | kubecfg_path | |no | Path to kubecfg file. Mandatory if config file not in `~/.kube/config` or KUBECONFIG env var not present|
|k8s | kubecfg_context |  |no | kubernetes context to use from your kubeconfig file. It will use the default active context if not provided |
|k8s | namespace | default |no | Kubernetes namespace to use for lithops execution |
|k8s | docker_server | docker.io |no | Container registry URL |
|k8s | docker_user | |no | Container registry user name |
|k8s | docker_password | |no | Container registry password/token. In case of Docker hub, login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|k8s | rabbitmq_executor | False | no | Alternative K8s backend accelerating parallel function execution (map) thanks to rabbitmq group calls and warm-state pods of higher granularity. For more information [here](./kubernetes_rabbitmq.md).|
|k8s | max_workers | 100 | no | Max number of workers per `FunctionExecutor()`|
|k8s | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of the container. |
|k8s | runtime |  |no | Docker image name.|
|k8s | runtime_cpu | 1 |no | CPU limit. Default 1vCPU |
|k8s | runtime_memory | 512 |no | Memory limit in MB. Default 512MB |
|k8s | runtime_timeout | 600 |no | Runtime timeout in seconds. Default 600 seconds |
|k8s | master_timeout | 600 |no | Master pod timeout in seconds. Default 600 seconds |

## Test Lithops

Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b k8s -s ibm_cos
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```