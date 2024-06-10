# IBM Virtual Private Cloud

The IBM VPC client of Lithops can provide a truely serverless user experience on top of IBM VPC where Lithops creates new VSIs (Virtual Server Instance) dynamically in runtime, and scale Lithops jobs against them (Create & Reuse modes). Alternatively Lithops can start and stop an existing VSI instance (Consume mode).

## Installation

1. Install IBM Cloud backend dependencies:

```bash
python3 -m pip install lithops[ibm]
```

## IBM VPC
The assumption that you already familiar with IBM Cloud, have your IBM IAM API key created (you can create new keys [here](https://cloud.ibm.com/iam/apikeys)), have valid IBM COS account, region and resource group.

Follow [IBM VPC setup](https://cloud.ibm.com/vpc-ext/overview) if you need to create IBM Virtual Private Cloud. Decide the region for your VPC. The best practice is to use the same region both for VPC and IBM COS, however there is no requirement to keep them in the same region.

## Choose an operating system image for VSI
Any Virtual Service Instance (VSI) need to define the instance’s operating system and version. Lithops support both standard Ubuntu operating system choices provided by the VPC and using pre-defined custom images that already contains all dependencies required by Lithops.

- Option 1: Lithops is compatible with any Ubuntu 22.04 image provided in IBM Cloud. In this case, no further action is required and you can continue to the next step. Lithops will install all required dependencies in the VSI by itself. Notice this can consume about 3 min to complete all installations.

- Option 2: Alternatively, you can use a pre-built custom image (based on Ubuntu) that will greatly improve VSI creation time for Lithops jobs. To benefit from this approach, navigate to [runtime/ibm_vpc](https://github.com/lithops-cloud/lithops/tree/master/runtime/ibm_vpc), and follow the instructions.


## Create and reuse modes

In the `create` mode, Lithops will automatically create new worker VM instances in runtime, scale Lithops job against generated VMs, and automatically delete the VMs when the job is completed.
Alternatively, you can set the `reuse` mode to keep running the started worker VMs, and reuse them for further executions. In the `reuse` mode, Lithops checks all the available worker VMs and start new workers only if necessary.

### Lithops configuration for the *create* and *reuse* mode

Edit your lithops config and add the relevant keys:

```yaml
lithops:
    backend: ibm_vpc

ibm:
    iam_api_key: <iam-api-key>
    region: <REGION>
    resource_group_id: <RESOURCE_GROUP_ID>

ibm_vpc:
    exec_mode: reuse
```

## Configure a Container registry
To configure Lithops to access a private container registry, you need to add the following keys to the **standalone** section in config:

```yaml
ibm_vpc:
    ....
    docker_server    : <Container registry server>
    docker_user      : <Container registry username>
    docker_password  : <Container registry access token>
```

### Configure IBM Container Registry
To configure Lithops to access to a private docker repository in your IBM Container Registry, you need to extend the **standalone** config and add the following keys:

```yaml
ibm_vpc:
    ....
    docker_server    : us.icr.io  # Change-me if you have the CR in another region
    docker_user      : iamapikey
    docker_password  : <IBM IAM API KEY>
    docker_namespace : <namespace>  # namespace name from https://cloud.ibm.com/registry/namespaces
```


## Summary of configuration keys for IBM Cloud:

### IBM:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |yes | IBM Cloud IAM API key to authenticate against IBM services. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |
|ibm | region | |yes | IBM Region.  One of: `eu-gb`, `eu-de`, `us-south`, `us-east`, `br-sao`, `ca-tor`, `jp-tok`, `jp-osa`, `au-syd` |
|ibm | resource_group_id | | yes | Resource group id from your IBM Cloud account. Get it from [here](https://cloud.ibm.com/account/resource-groups) |

### IBM VPC - Create and Reuse modes

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_vpc | region | |no | VPC Region. For example `us-south`. Choose one region from [here](https://cloud.ibm.com/docs/vpc?topic=vpc-service-endpoints-for-vpc). Lithops will use the `region` set under the `ibm` section if it is not set here. Alternatively you can specify a Zone, for example: `eu-gb-2` |
|ibm_vpc | vpc_id | | no | VPC id of an existing VPC. Get it from [here](https://cloud.ibm.com/vpc-ext/network/vpcs) |
|ibm_vpc | vpc_name | | no | VPC name of an existing VPC (if `vpc_id` is not provided) |
|ibm_vpc | security_group_id | | no | Security group id of an existing VPC. Get it from [here](https://cloud.ibm.com/vpc-ext/network/securityGroups)|
|ibm_vpc | subnet_id | | no | Subnet id of an existing VPC. Get it from [here](https://cloud.ibm.com/vpc-ext/network/subnets)|
|ibm_vpc | ssh_key_id | | no | SSH public key id. Get it from [here](https://cloud.ibm.com/vpc-ext/compute/sshKeys)|
|ibm_vpc | gateway_id | | no | Gateway id. Get it from [here](https://cloud.ibm.com/vpc-ext/network/publicGateways)|
|ibm_vpc | image_id | | no | Virtual machine image id. Default is Ubuntu Server 22.04 |
|ibm_vpc | runtime | python3 | no | Runtime name to run the functions. Can be a container image name. If not set Lithops will use the default python3 interpreter of the VM |
|ibm_vpc | ssh_username | root |no | Username to access the VM |
|ibm_vpc | ssh_password |  |no | Password for accessing the worker VMs. If not provided, it is created randomly|
|ibm_vpc | ssh_key_filename | ~/.ssh/id_rsa | no | Path to the ssh key file provided to access the VPC. It will use the default path if not provided |
|ibm_vpc | boot_volume_profile | general-purpose | no | Virtual machine boot volume profile |
|ibm_vpc | boot_volume_capacity | 100 | no | Virtual machine boot volume capacity in GB. |
|ibm_vpc | worker_profile_name | cx2-2x4 | no | Profile name for the worker VMs |
|ibm_vpc | master_profile_name | cx2-2x4 | no | Profile name for the master VM |
|ibm_vpc | verify_resources | True | no | Verify the resources that are stored in the local cache, and expected to be already created (VPC, subnet, floating IP, etc.), exist every time a `FunctionExecutor()` is created |
|ibm_vpc | delete_on_dismantle | True | no | Delete the worker VMs when they are stopped |
|ibm_vpc | max_workers | 100 | no | Max number of workers per `FunctionExecutor()`|
|ibm_vpc | worker_processes | AUTO | no | Number of Lithops processes within a given worker. This is used to parallelize function activations within a worker. By default it detects the amount of CPUs in the worker VM|
|ibm_vpc | auto_dismantle | True |no | If False then the VM is not stopped automatically.|
|ibm_vpc | soft_dismantle_timeout | 300 |no| Time in seconds to stop the VM instance after a job **completed** its execution |
|ibm_vpc | hard_dismantle_timeout | 3600 | no | Time in seconds to stop the VM instance after a job **started** its execution |
|ibm_vpc | exec_mode | reuse | no | One of: **consume**, **create** or **reuse**. If set to  **create**, Lithops will automatically create new VMs for each map() call based on the number of elements in iterdata. If set to **reuse** will try to reuse running workers if exist |
|ibm_vpc | singlesocket | False | no | Try to allocate workers with single socket CPU. If eventually running on multiple socket, a warning message printed to user. Is **True** standalone **workers_policy** must be set to **strict** to trace workers states|
|ibm_vpc | gpu | False | no | If `True` docker started with gpu support. Requires host to have necessary hardware and software pre-configured, and docker image runtime with gpu support specified |

## Consume mode

In this mode, Lithops can start and stop an existing VM, and deploy an entire job to that VM. The partition logic in this scenario is different from the `create/reuse` modes, since the entire job is executed in the same VM.

### Lithops configuration for the consume mode

Edit your lithops config and add the relevant keys:

```yaml
lithops:
    backend: ibm_vpc

ibm:
    iam_api_key: <iam-api-key>

ibm_vpc:
    exec_mode: consume
    region   : <REGION>
    instance_id : <INSTANCE ID OF THE VM>
    floating_ip  : <FLOATING IP ADDRESS OF THE VM>
```

If you need to create new VM, then follow the steps to create and update Lithops configuration:

1. Create an Ubuntu 22.04 virtual server instance (VSI) in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) with CPUs and RAM needed for your application.
2. Reserve and associate a floating IP address in [IBM VPC floating IPs UI](https://cloud.ibm.com/vpc-ext/network/floatingIPs) to be used for the virtual server instance.
3. Get the floating IP address of your virtual server instance which can be found [here](https://cloud.ibm.com/vpc-ext/network/floatingIPs).
4. Get the endpoint of your subnet region, endpoint URLs list can be found [here](https://cloud.ibm.com/apidocs/vpc#endpoint-url).
5. Get the virtual server instance ID by selecting on your instance in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) and then extracting from the instance's details.

## Summary of configuration keys for IBM Cloud:

### IBM:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |no | IBM Cloud IAM API key to authenticate against IBM COS and IBM Cloud Functions. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |
|ibm | region | |no | IBM Region.  One of: `eu-gb`, `eu-de`, `us-south`, `us-east`, `br-sao`, `ca-tor`, `jp-tok`, `jp-osa`, `au-syd` |

### IBM VPC - Consume Mode

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_vpc | region | |yes | VPC Region. For example `us-south`. Choose one region from [here](https://cloud.ibm.com/docs/vpc?topic=vpc-service-endpoints-for-vpc). Lithops will use the region set under the `ibm` section if it is not set here |
|ibm_vpc | instance_id | | yes | virtual server instance ID |
|ibm_vpc | floating_ip | | yes | Floating IP address attached to your VM instance|
|ibm_vpc | ssh_username | root |no | Username to access the VM |
|ibm_vpc | ssh_key_filename | ~/.ssh/id_rsa | no | Path to the ssh key file provided to create the VM. It will use the default path if not provided |
|ibm_vpc | worker_processes | AUTO | no | Number of Lithops processes within a given worker. This is used to parallelize function activations within the worker. By default it detects the amount of CPUs in the VM|
|ibm_vpc | runtime | python3 | no | Runtime name to run the functions. Can be a container image name. If not set Lithops will use the default `python3` interpreter of the VM |
|ibm_vpc | auto_dismantle | True |no | If False then the VM is not stopped automatically.|
|ibm_vpc | soft_dismantle_timeout | 300 |no| Time in seconds to stop the VM instance after a job **completed** its execution |
|ibm_vpc | hard_dismantle_timeout | 3600 | no | Time in seconds to stop the VM instance after a job **started** its execution |


## Test Lithops

Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b ibm_vpc -s ibm_cos
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```

## VM Management

Lithops for IBM VPC follows a Mater-Worker architecture (1:N).

All the VMs, including the master VM, are automatically stopped after a configurable timeout (see hard/soft dismantle timeouts).

You can login to the master VM and get a live ssh connection with:

```bash
lithops attach -b ibm_vpc
```

The master and worker VMs contain the Lithops service logs in `/tmp/lithops-root/*-service.log`

To list all the available workers in the current moment, use the next command:

```bash
lithops worker list -b ibm_vpc
```

You can also list all the submitted jobs with:

```bash
lithops job list -b ibm_vpc
```

You can delete all the workers with:

```bash
lithops clean -b ibm_vpc -s ibm_cos
```

You can delete all the workers including the Master VM with the `--all` flag:

```bash
lithops clean -b ibm_vpc -s ibm_cos --all
```
