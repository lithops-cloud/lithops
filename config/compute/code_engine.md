# Lithops on IBM Code Engine

[IBM Code Engine](https://cloud.ibm.com/codeengine/overview) allows you to run your application, job or container on a managed serverless platform. Auto-scale workloads and only pay for the resources you consume.

IBM Code Engine expose both Knative and Kubernetes Job Descriptor API. Lithops support both of them. Follow IBM Code Engine documentation to get more details on the difference between those APIs.

###  Initial requirements
In this step you are required to install IBM Cloud CLI tool, Code Engine plugin and create new Code Engine project

1. Install the [IBM Cloud CLI](https://cloud.ibm.com/docs/cli?topic=cli-getting-started):

   ```bash
   curl -sL https://ibm.biz/idt-installer | bash
   ```

2. Login to your account (IBM Code Engine is currently present on us_south region, so login to this region)

   ```bash
   ibmcloud login -r us_south
   ```

3. Install the IBM Code Engine plugin:

   ```bash
   ibmcloud plugin install code-engine
   ```

4. Create a new Code Engine project (you can also do this through the dashboard):

   ```bash
   ibmcloud ce project create --name myproject
   ```

5. Target to this project:

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

9. Login to your docker account:
   ```bash
   docker login
   ```

### Lithops using Knative API of Code Engine

The only requirement to make it working is to have the KUBECONFIG file properly configured. To do so, follow the next steps:


Note that Lithops automatically builds the default runtime the first time you run a script. For this task it uses the **docker** command installed locally in your machine. If for some reason you can't install the Docker CE package locally, you must provide the **docker_token** parameter in the configuration. This way lithops will use Tekton of your k8s cluster to build the default runtime to your docker hub account. In this case, omit the steps 8 and 9.


#### Edit your lithops config file and add the following keys:

   ```yaml
   lithops:
       compute_backend: knative

   knative:
       docker_user: <DOCKER_USERNAME>
   ```

#### Summary of configuration keys for Knative:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|knative | istio_endpoint | |no | Istio IngressGateway Endpoint. Make sure to use http:// prefix |
|knative | docker_user | |yes | Docker hub username |
|knative | docker_token | |no | Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|knative | git_url | |no | Git repository to build the image |
|knative | git_rev | |no | Git revision to build the image |
|knative | cpu | 1000 |no | CPU limit in millicpu. Default 1vCPU (1000m) |

### Lithops using Kubernetes Job API of Code Engine


Note that Lithops automatically builds the default runtime the first time you run a script. For this task it uses the **docker** command installed locally in your machine. 

#### Edit your lithops config file and add the following keys:

   ```yaml
   lithops:
       compute_backend: code_engine

   code_engine:
       kubectl_config: <PATH TO CONFIG YAML FIlE>
   ```

#### Summary of configuration keys for Job API:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|code_engine | cpu | 1000 |no | CPU limit in millicpu. Default 1vCPU (1000m) |
