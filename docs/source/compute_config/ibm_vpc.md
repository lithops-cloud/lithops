# IBM Virtual Private Cloud

The IBM VPC client of Lithops can provide a truely serverless user experience on top of IBM VPC where Lithops creates new VSIs (Virtual Server Instance) dynamically in runtime, and scale Lithops jobs against them. Alternatively Lithops can start and stop an existing VSI instances.

Note that IBM VPC is a **standalone backend**, and as such, you can configure extra parameters in the 'standalone' section of the configuration:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|standalone | runtime | python3 | no | Runtime name to run the functions. Can be a Docker image name |
|standalone | auto_dismantle | True |no | If False then the VM is not stopped automatically.|
|standalone | soft_dismantle_timeout | 300 |no| Time in seconds to stop the VM instance after a job **completed** its execution |
|standalone | hard_dismantle_timeout | 3600 | no | Time in seconds to stop the VM instance after a job **started** its execution |
|standalone | exec_mode | consume | no | One of: **consume**, **create** or **reuse**. If set to  **create**, Lithops will automatically create new VMs for each map() call based on the number of elements in iterdata. If set to **reuse** will try to reuse running workers if exist |
|standalone | pull_runtime | False | no | If set to True, Lithops will execute the command `docker pull <runtime_name>` in each VSI before executing the a job (in case of using a docker runtime)|
|standalone | workers_policy | permissive | no | One of: **permissive**, **strict**. If set to **strict** will force creation of required workers number |
|standalone | gpu | False | no | If True docker started with gpu support. Requires host to have neccessary hardware and software preconfigured and docker image runtime with gpu support specified |

## Configure Docker hub
To configure Lithops to access a private docker repository, you need to add the following keys to **standalone** config:

```yaml
standalone:
    ....
    docker_server    : <Docker registry server>
    docker_user      : <Docker registry username>
    docker_password  : <Docker registry access token>
```

### Configure IBM Container Registry
To configure Lithops to access to a private docker repository in your IBM Container Registry, you need to extend the **standalone** config and add the following keys:

```yaml
standalone:
    ....
    docker_server    : us.icr.io  # Change-me if you have the CR in another region
    docker_user      : iamapikey
    docker_password  : <IBM IAM API KEY>
```

## IBM VPC
The assumption that you already familiar with IBM Cloud, have your IBM IAM API key created (you can create new keys [here](https://cloud.ibm.com/iam/apikeys)), have valid IBM COS account, region and resource group.

Follow [IBM VPC setup](https://cloud.ibm.com/vpc-ext/overview) if you need to create IBM Virtual Private Cloud. Decide the region for your VPC. The best practice is to use the same region both for VPC and IBM COS, hoewever there is no requirement to keep them in the same region.

### Minimum setup requirements

1. Create new VPC if you don't have one already. More details [here](https://cloud.ibm.com/vpc-ext/network/vpcs)
2. Create new subnet with public gateway and IP range and total count. More details [here](https://cloud.ibm.com/vpc-ext/network/subnets)
3. Create new access contol list. More details [here](https://cloud.ibm.com/vpc-ext/network/acl)
4. Create security group for your resource group. More details [here](https://cloud.ibm.com/vpc-ext/network/securityGroups)
5. Create a SSH key in [IBM VPC SSH keys UI](https://cloud.ibm.com/vpc-ext/compute/sshKeys)

### Choose an operating system image for VSI
Any Virtual Service Instance (VSI) need to define the instance’s operating system and version. Lithops support both standard operting system choices provided by the VPC or using pre-defined custom images that already contains all dependencies required by Lithops.

- Option 1: By default, Lithops uses an Ubuntu 20.04 image. In this case, no further action is required and you can continue to the next step. Lithops will install all required dependencies in the VSI by itself. Notice this can consume about 3 min to complete all installations.

- Option 2: Alternatively, you can use a pre-built custom image that will greatly improve VSI creation time for Lithops jobs. To benefit from this approach, navigate to [runtime/ibm_vpc](https://github.com/lithops-cloud/lithops/tree/master/runtime/ibm_vpc), and follow the instructions.


## Lithops and the VSI auto create mode
In this mode, Lithops will automatically create new worker VM instances in runtime, scale Lithops job against generated VMs, and automatically delete VMs when the job is completed.

### Lithops configuration for the auto create mode

Edit your lithops config and add the relevant keys:

```yaml
lithops:
    backend: ibm_vpc

ibm:
    iam_api_key: <iam-api-key>

standalone:
    exec_mode: create

ibm_vpc:
    endpoint: <REGION_ENDPOINT>
    vpc_id: <VPC_ID>
    resource_group_id: <RESOURCE_GROUP_ID>
    security_group_id: <SECURITY_GROUP_ID>
    subnet_id: <SUBNET_ID>
    key_id: <PUBLIC_KEY_ID>
```

The fastest way to find all the required keys for `ibm_vpc` section as follows:

1. Login to IBM Cloud and open up your [dashboard](https://cloud.ibm.com/).
2. Navigate to your [IBM VPC create instance](https://cloud.ibm.com/vpc-ext/provision/vs).
3. On the left, fill all the parameters required for your new VM instance creation: name, resource group, location, ssh key, vpc. Choose either Ubuntu 20.04 VSI standard image or choose your **custom image** from the previous step
4. On the right, click `Get sample API call`.
5. Copy to clipboard the code from the `REST request: Creating a virtual server instance` dialog and paste to your favorite editor.
6. Close the `Create instance` window without creating it.
7. In the code, find `security_groups` section and paste its `id` value to the .lithops_config ibm_vpc section security_group_id key.
8. Find `subnet` section and paste its `id` value to the .lithops_config ibm_vpc section subnet_id key.
9. Find `keys` section and paste its `id` value to the .lithops_config ibm_vpc section key_id key.
10. Find `resource_group` section and paste its `id` value to the .lithops_config ibm_vpc section resource_group_id key.
11. Find `vpc` section and paste its `id` value to the .lithops_config ibm_vpc section vpc_id key.


### Verify auto create mode with Lithops

To verify auto create mode is working, use the following example

```python
iterdata = [1, 2, 3, 4]

def my_map_function(x):
    return x + 7

if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    fexec.map(my_map_function, iterdata)
    print(fexec.get_result())
```

This will create 4 different VM instance and execute `my_map_function` in the each of created VM. Upon completion, Lithops will delete the VMs.

###  Important information
1. The first time you use Lithops with specific runtime, Lithops will try generate and obtain runtime metadata. For this purpose Lithops will create a VM, extract specific metadata and delete VM. All further executions against same runtime will skip this step as runtime metadata will be cached both locally and in IBM COS.
2. In certain cases where ssh access details are wrong, Lithops might fail to ssh into created VM from the previous step. In this case, fix the ssh access credentials, navigate into dashboard of IBM VPC and manually delete the VM and floating IP associated with it.
3.	The first time you deplopy Lithops job in the auto create mode it is advised to navigate to dashboard of IBM VPC and verify that VM is being created and deleted.
4. If running Lithops over Gen2 fails with error message that decode() in pyJWT need `algorithms` then please make sure pyJWT is version `1.7.1` installed. If needed execute `pip install -U PyJWT==1.7.1`

### Summary of the configuration keys for the create mode

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_vpc | endpoint | |yes | Endpoint of your subnet region |
|ibm_vpc | vpc_id | | yes | VPC id |
|ibm_vpc | resource_group_id | | yes | Resource group id |
|ibm_vpc | security_group_id | | yes | Security group id |
|ibm_vpc | subnet_id | | yes | Subnet id |
|ibm_vpc | key_id | | yes | Ssh public key id |
|ibm_vpc | ssh_username | root |no | Username to access the VPC |
|ibm_vpc | ssh_password |  |no | Password for accessing the worker VMs. If not provided, it is created randomly|
|ibm_vpc | ssh_key_filename | | no | Path to the ssh key file provided to access the VPC. It will use the default path if not provided |
|ibm_vpc | image_id | | no | Virtual machine image id |
|ibm_vpc | boot_volume_profile | general-purpose | no | Virtual machine boot volume profile |
|ibm_vpc | boot_volume_capacity | 100 | no | Virtual machine boot volume capacity in GB |
|ibm_vpc | profile_name | cx2-2x4 | no | Profile name for the worker VMs |
|ibm_vpc | master_profile_name | cx2-2x4 | no | Profile name for the master VM |
|ibm_vpc | delete_on_dismantle | True | no | Delete the worekr VMs when they are stopped |
|ibm_vpc | max_workers | 100 | no | Max number of workers per `FunctionExecutor()`|
|ibm_vpc | worker_processes | 2 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of a worker VM. |
|ibm_vpc | singlesocket | False | no | Try to allocate workers with single socket CPU. If eventually running on multiple socket, a warning message printed to user. Is **True** standalone **workers_policy** must be set to **strict** to trace workers states|

## Lithops and the VSI consume mode

In this mode, Lithops can start and stop an existing VM, and deploy an entire job to that VM. The partition logic in this scenario is different from the auto create mode, since entire job executed in the same VM.

### Lithops configuration for the consume mode

Edit your lithops config and add the relevant keys:

   ```yaml
   lithops:
	  backend: ibm_vpc

   ibm:
	  iam_api_key: <iam-api-key>

   ibm_vpc:
      endpoint   : <REGION_ENDPOINT>
      instance_id : <INSTANCE ID OF THE VM>
      ip_address  : <FLOATING IP ADDRESS OF THE VM>
   ```

If you need to create new VM, then follow the steps to create and update Lithops configuration:

1. Create an Ubuntu 20.04 virtual server instance (VSI) in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) with CPUs and RAM needed for your application.
2. Reserve and associate a floating IP address in [IBM VPC floating IPs UI](https://cloud.ibm.com/vpc-ext/network/floatingIPs) to be used for the virtual server instance.
3. Get the floating IP address of your virtual server instance which can be found [here](https://cloud.ibm.com/vpc-ext/network/floatingIPs).
4. Get the endpoint of your subnet region, endpoint URLs list can be found [here](https://cloud.ibm.com/apidocs/vpc#endpoint-url).
5. Get the virtual server instance ID by selecting on your instance in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) and then extracting from the instance's details.

### Summary of the configuration keys for the consume mode

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_vpc | endpoint | |yes | Endpoint of your subnet region |
|ibm_vpc | instance_id | | yes | virtual server instance ID |
|ibm_vpc | ip_address | | yes | Floatting IP address atached to your Vm instance|
|ibm_vpc | ssh_key_filename | | no | Path to the ssh key file provided to create the VM. It will use the default path if not provided |
|ibm_vpc | worker_processes | 2 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of the VM. |

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```

The master and worker VMs contains the Lithops service logs in `/tmp/lithops/service.log`

You can login to the master VM and get a live ssh connection with:

```bash
lithops attach -b ibm_vpc
```
