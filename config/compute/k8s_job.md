# Lithops on kubernetes (batch/job)

Lithops with kubernetes as serverless compute backend.


### Configuration

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

### Configure a private container registry for your runtime

#### Configure Docker hub
To configure Lithops to access a private repository in your docker hub account, you need to extend the kubernetes config and add the following keys:

```yaml
k8s:
    ....
    docker_user      : <Docker hub Username>
    docker_password  : <DOcker hub access TOEKN>
```

#### Configure IBM Container Registry
To configure Lithops to access to a private repository in your IBM Container Registry, you need to extend the kubernetes config and add the following keys:

```yaml
k8s:
    ....
    docker_server    : us.icr.io
    docker_user      : iamapikey
    docker_password  : <IBM IAM API KEY>
```

#### Summary of configuration keys for kubernetes:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|k8s | kubecfg_path | |no | Path to kubecfg file. Mandatory if config file not in `~/.kube/config` or KUBECONFIG env var not present|
|k8s | docker_server | https://index.docker.io/v1/ |no | Docker server URL |
|k8s | docker_user | |no | Docker hub username |
|k8s | docker_password | |no | Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|k8s | max_workers | 100 | no | Max number of workers per `FunctionExecutor()`|
|k8s | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of the container. |
|k8s | runtime |  |no | Docker image name.|
|k8s | runtime_cpu | 0.125 |no | CPU limit. Default 0.125vCPU |
|k8s | runtime_memory | 256 |no | Memory limit in MB. Default 256Mi |
|k8s | runtime_timeout | 600 |no | Runtime timeout in seconds. Default 600 seconds |
