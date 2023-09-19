# Kubernetes RabbitMQ (batch/job)

**Lithops for Kubernetes RabbitMQ (Lithops k8s_rabbitmq)** introduces an innovative architectural approach for deploying and executing functions within a Kubernetes environment. This version is designed to maximize resource utilization and performance, providing users with an efficient and streamlined way to harness the full computational capabilities of their Kubernetes cluster.

Lithops K8s RabbitMQ serves as an **experimental backend** that aims to accelerate parallel programming workflows. By leveraging this cutting-edge technology, users can take advantage of several key benefits over the previous version of Lithops:

### Advantages of Lithops K8s

* **Improved Cold Start Time:** Lithops K8s RabbitMQ offers a significant enhancement in cold start time, effectively reducing the delay before your functions start executing. This improvement can lead to quicker response times and increased overall efficiency.

* **Warm Start Capability:** Unlike K8s, Lithops K8s RabbitMQ introduces the ability to perform warm starts. This means that previously executed functions can be cached and reused, further reducing execution time and resource utilization.

* **Efficient Function Invocation:** With Lithops K8s RabbitMQ, you can execute multiple functions with just a single RabbitMQ invocation. This optimization minimizes overhead and simplifies the process of invoking functions, making your applications more responsive and resource-efficient.

* **Accelerated Parallel Programming:** Lithops K8s RabbitMQ is specifically designed to accelerate parallel programming tasks. It maximizes resource utilization by creating dedicated pods for each cluster node, allowing for parallel execution of functions across the Kubernetes cluster. This approach results in improved parallelism and resource efficiency, enabling you to make the most of your cluster's computational capabilities.


## Configuration

1. Edit your Lithops config and add the following keys:

```yaml
  lithops:
      backend : k8s_rabbitmq
```

2. Make sure you have a kubernetes cluster configuration file.
   - Option 1: You have the config file in `~/.kube/config`

   - Option 2: You have the config file in another location, and you exported the KUBECONFIG variable:
     ```bash
     export KUBECONFIG=<path-to-kube-config-file>
     ```

   - Option 3: You have the config file in another location, and you set the `kubecfg_path` var in the Lithops config:
     ```yaml
     k8s_rabbitmq:
         kubecfg_path: <path-to-kube-config-file>
     ```
3. For this version, a connection to [rabbitMQ](../monitoring.rst) is required.
To enable Lithops to use this service, add the AMQP_URL key into the rabbitmq section in the configuration, for example:

```yaml
rabbitmq:
    amqp_url: <AMQP_URL>  # amqp://
```
In addition, you need to activate the monitoring service in the configuration (Lithops section):

```yaml
lithops:
   monitoring: rabbitmq
```

## Configure a private container registry for your runtime

### Configure Docker hub
To configure Lithops to access a private repository in your docker hub account, you need to extend the kubernetes config and add the following keys:

```yaml
k8s_rabbitmq:
    ....
    docker_server    : docker.io
    docker_user      : <Docker hub Username>
    docker_password  : <DOcker hub access TOEKN>
```

### Configure IBM Container Registry
To configure Lithops to access to a private repository in your IBM Container Registry, you need to extend the kubernetes config and add the following keys:

```yaml
k8s_rabbitmq:
    ....
    docker_server    : us.icr.io
    docker_user      : iamapikey
    docker_password  : <IBM IAM API KEY>
```

## Summary of configuration keys for kubernetes:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|k8s_rabbitmq | kubecfg_path | |no | Path to kubecfg file. Mandatory if config file not in `~/.kube/config` or KUBECONFIG env var not present|
|k8s_rabbitmq | docker_server | docker.io |no | Docker server URL |
|k8s_rabbitmq | docker_user | |no | Docker hub username |
|k8s_rabbitmq | docker_password | |no | Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|k8s_rabbitmq | max_workers | 200 | no | Max number of workers per `FunctionExecutor()`|
|k8s_rabbitmq | runtime |  |no | Docker image name.|
|k8s_rabbitmq | runtime_cpu | 0.5 |no | CPU limit. Default 0.5vCPU |
|k8s_rabbitmq | runtime_memory | 256 |no | Memory limit in MB. Default 256Mi |
|k8s_rabbitmq | runtime_timeout | 600 |no | Runtime timeout in seconds. Default 600 seconds |

## Test Lithops

Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b k8s_rabbitmq -s ibm_cos
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```
