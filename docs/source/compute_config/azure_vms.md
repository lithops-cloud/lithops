# Azure Virtual Machines (Beta)

The Azure Virtual Machines client of Lithops can provide a truely serverless user experience on top of Azure VMs where Lithops creates new Virtual Machines (VMs) dynamically in runtime and scale Lithops jobs against them. Alternatively Lithops can start and stop an existing VM instances.


### Choose an operating system image for the VM
- Option 1: By default, Lithops uses an Ubuntu 22.04 image. In this case, no further action is required and you can continue to the next step. Lithops will install all required dependencies in the VM by itself. Notice this can consume about 3 min to complete all installations.

- Option 2: Alternatively, you can use a pre-built custom image that will greatly improve VM creation time for Lithops jobs. To benefit from this approach, navigate to [runtime/azure_vms](https://github.com/lithops-cloud/lithops/tree/master/runtime/azure_vms), and follow the instructions.

## Lithops and the VM consume mode

In this mode, Lithops can start and stop an existing VM, and deploy an entire job to that VM. The partition logic in this scenario is different from the `create/reuse` modes, since the entire job is executed in the same VM.

### Lithops configuration for the consume mode

Edit your lithops config and add the relevant keys:

```yaml
    lithops:
        backend: azure_vms

    azure:
        resource_group: <RESOURCE_GROUP_NAME>
        region: <LOCATION>
        subscription_id: <SUBSCRIPTION_ID>

    azure_vms:
        exec_mode: consume
        instance_name: <VM_NAME>
        ssh_username: <SSH_USERNAME>
        ssh_key_filename: <SSH_KEY_PATH>
```


### Azure

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure| resource_group | | yes | Name of a resource group, for example: `LithopsResourceGroup` |
|azure| region |  |yes | Location of the resource group, for example: `westeurope`, `westus2`, etc|
|azure| subscription_id |  |yes | Subscription ID from your account. Find it [here](https://portal.azure.com/#view/Microsoft_Azure_Billing/SubscriptionsBlade)|

### Azure VMs - Consume Mode

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_vms | instance_name | | yes | virtual server instance Name. The instance must exists in your resource group |
|azure_vms | ssh_username | ubuntu | yes | Username to access the VM. It will use `ubuntu` if not provided |
|azure_vms | ssh_key_filename | ~/.ssh/id_rsa | yes | Path to the ssh key file provided to create the VM. It will use the default path if not provided |
|azure_vms | region | |no | Location of the resource group, for example: `westeurope`, `westus2`, etc. Lithops will use the region set under the `azure` section if it is not set here |
|azure_vms | worker_processes | AUTO | no | Number of Lithops processes within a given worker. This is used to parallelize function activations within the worker. By default it detects the amount of CPUs in the VM|
|azure_vms | runtime | python3 | no | Runtime name to run the functions. Can be a container image name. If not set Lithops will use the defeuv python3 interpreter of the VM |
|azure_vms | auto_dismantle | True |no | If False then the VM is not stopped automatically.|
|azure_vms | soft_dismantle_timeout | 300 |no| Time in seconds to stop the VM instance after a job **completed** its execution |
|azure_vms | hard_dismantle_timeout | 3600 | no | Time in seconds to stop the VM instance after a job **started** its execution |


## Lithops and the VM auto create and reuse modes
In the `create` mode, Lithops will automatically create new worker VM instances in runtime, scale Lithops job against generated VMs, and automatically delete the VMs when the job is completed.
Alternatively, you can set the `reuse` mode to keep running the started worker VMs, and reuse them for further executions. In the `reuse` mode, Lithops checks all the available worker VMs and start new workers only if necessary.

### Lithops configuration for the create or reuse modes

Edit your lithops config and add the relevant keys:

```yaml
    lithops:
        backend: azure_vms

    azure:
        resource_group: <RESOURCE_GROUP_NAME>
        region: <LOCATION>
        subscription_id: <SUBSCRIPTION_ID>

    azure_vms:
        exec_mode: reuse
```


### Azure

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure| resource_group | | yes | Name of a resource group, for example: `LithopsResourceGroup` |
|azure| region |  |yes | Location of the resource group, for example: `westeurope`, `westus2`, etc|
|azure| subscription_id |  |yes | Subscription ID from your account. Find it [here](https://portal.azure.com/#view/Microsoft_Azure_Billing/SubscriptionsBlade)|

### Azure VMs - Create and Reuse Modes

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_vms| region |  |no | Azure location for deploying the VMS. For example: `westeurope`, `westus2`, etc. Lithops will use the `region` set under the `azure` section if it is not set here|
|azure_vms | image_id | Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest |no | Image ID. ARM resource identifier |
|azure_vms | ssh_username | ubuntu |no | Username to access the VM |
|azure_vms | ssh_password |  |no | Password for accessing the worker VMs. If not provided, it is created randomly|
|azure_vms | ssh_key_filename | ~/.ssh/id_rsa | no | Path to the ssh key file provided to access the VPC. It will use the default path if not provided |
|azure_vms | master_instance_type | Standard_B1s | no | Profile name for the master VM |
|azure_vms | worker_instance_type | Standard_B2s | no | Profile name for the worker VMs |
|azure_vms | delete_on_dismantle | False | no | Delete the worker VMs when they are stopped. Master VM is never deleted when stopped. `True` is NOT YET SUPPORTED |
|azure_vms | max_workers | 100 | no | Max number of workers per `FunctionExecutor()`|
|azure_vms | worker_processes | 2 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of a worker VM. |
|azure_vms | runtime | python3 | no | Runtime name to run the functions. Can be a container image name. If not set Lithops will use the default python3 interpreter of the VM |
|azure_vms | auto_dismantle | True |no | If False then the VM is not stopped automatically.|
|azure_vms | soft_dismantle_timeout | 300 |no| Time in seconds to stop the VM instance after a job **completed** its execution |
|azure_vms | hard_dismantle_timeout | 3600 | no | Time in seconds to stop the VM instance after a job **started** its execution |
|azure_vms | exec_mode | reuse | no | One of: **consume**, **create** or **reuse**. If set to  **create**, Lithops will automatically create new VMs for each map() call based on the number of elements in iterdata. If set to **reuse** will try to reuse running workers if exist |
|azure_vms | pull_runtime | False | no | If set to True, Lithops will execute the command `docker pull <runtime_name>` in each VSI before executing the a job (in case of using a docker runtime)|
|azure_vms | workers_policy | permissive | no | One of: **permissive**, **strict**. If set to **strict** will force creation of required workers number |

## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b azure_vms -s azure_storage
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```

The master and worker VMs contain the Lithops service logs in `/tmp/lithops-root/service.log`

You can login to the master VM and get a live ssh connection with:

```bash
lithops attach -b azure_vms
```
