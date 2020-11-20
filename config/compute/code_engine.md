# Lithops on IBM Code Engine

[IBM Code Engine](https://cloud.ibm.com/codeengine/overview) allows you to run your application, job or container on a managed serverless platform. Auto-scale workloads and only pay for the resources you consume.

IBM Code Engine expose both Knative and Kubernetes Job Descriptor API. Lithops supports both of them. Follow IBM Code Engine documentation to get more details on the difference between those APIs.

###  Initial requirements
In this step you are required to install IBM Cloud CLI tool, Code Engine plugin and create new Code Engine project

1. Install the [IBM Cloud CLI](https://cloud.ibm.com/docs/cli?topic=cli-getting-started):

   ```bash
   curl -sL https://ibm.biz/idt-installer | bash
   ```

2. Login to your account (IBM Code Engine is currently present on us_south region, so login to this region)

   ```bash
   ibmcloud login -r us-south
   ```

3. Install the IBM Code Engine plugin:

   ```bash
   ibmcloud plugin install code-engine
   ```

4. Create a new Code Engine project (you can also do this through the dashboard). If you already have existing project, then proceed to step 5:

   ```bash
   ibmcloud ce project create --name myproject
   ```

5. Target to your project:

   ```bash
   ibmcloud ce project select --name myproject
   ```
   
6. Locate the kubernetes config file:

   ```bash
   ibmcloud ce project current
   ```

7. Set the KUBECONFIG environment variable as printed in the previous step:

   ```bash
   export KUBECONFIG=<PATH TO YAML FILE>
   ```

8. [Install the Docker CE version](https://docs.docker.com/get-docker/).
    Note that Lithops automatically builds the default runtime the first time you run a script. For this task it uses the **docker** command installed locally in your machine.

9. Login to your docker account:
   ```bash
   docker login
   ```

### Lithops using Knative API of Code Engine

The only requirement to make it working is to have the KUBECONFIG file properly configured.


#### Edit your lithops config and add the following keys:

   ```yaml
   serverless:
       backend: knative
   ```

#### Summary of configuration keys for Knative:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|knative | istio_endpoint | |no | Istio IngressGateway Endpoint. Make sure to use http:// prefix |
|knative | docker_user | |no | Docker hub username |
|knative | docker_token | |no | Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|knative | git_url | |no | Git repository to build the image |
|knative | git_rev | |no | Git revision to build the image |
|knative | min_instances | 0 |no | Minimum number of parallel runtimes |
|knative | max_instances | 250 |no | Maximum number of parallel runtimes |
|knative | cpu | 1000 |no | CPU limit in millicpu. Default 1vCPU (1000m) |
|knative | concurrency | 1 |no | Number of workers per runtime instance |


### Lithops using Kubernetes Job API of Code Engine

To work with Code Engine there is need to use dedicated runtime. You can either use default runtime that we maintain or alternatively create new runtime with required dependencies.

|Default runtime name| Python version | What is included | Lithops version |
|----|-----|----|-----|
|ibmfunctions/lithops-ce-3.7.5-2.2.0:1.0.0 | 3.7.5 | [included](../../runtime/code_engine/requirements.txt) | 2.2.0 |
|ibmfunctions/lithops-ce-3.8.5-2.2.2:1.0.0 | 3.8.5 | [included](../../runtime/code_engine/requirements385.txt) | 2.2.2 |

If you need to create new runtime, please follow [Building and managing Lithops runtimes to run the functions](../../runtime/)


#### Edit your lithops config and add the following keys:

   ```yaml
   serverless:
       backend: code_engine
       runtime: <RUNTIME NAME>

   code_engine:
       kubectl_config: <PATH TO CONFIG YAML FIlE>
   ```

#### Summary of configuration keys for Job API:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|code_engine | cpu | 1000 |no | CPU limit in millicpu. Default 1vCPU (1000m) |

### Usage Example

```
import lithops

iterdata = ['Gil', 'Dana', 'John', 'Scott']

def add_value(name):
    return 'Hello ' + name

if __name__ == '__main__':
	lt = lithops.FunctionExecutor(type="serverless",
			backend='code_engine',
			runtime = 'ibmfunctions/lithops-ce-3.8.5-2.2.2:1.0.0')
	lt.map(add_value,  iterdata)
	print (lt.get_result())
```