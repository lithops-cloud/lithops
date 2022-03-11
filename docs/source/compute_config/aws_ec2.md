# AWS Elastic Compute Cloud (EC2)

The AWS EC2 client of Lithops can provide a truely serverless user experience on top of EC2 where Lithops creates new Virtual Machines (VMs) dynamically in runtime and scale Lithops jobs against them. Alternatively Lithops can start and stop an existing VM instances.

Note that AWS EC2 is a **standalone backend**, and as such, you can configure extra parameters in the 'standalone' section of the configuration:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|standalone | runtime | python3 | no | Runtime name to run the functions. Can be a Docker image name |
|standalone | auto_dismantle | True |no | If False then the VM is not stopped automatically.|
|standalone | soft_dismantle_timeout | 300 |no| Time in seconds to stop the VM instance after a job **completed** its execution |
|standalone | hard_dismantle_timeout | 3600 | no | Time in seconds to stop the VM instance after a job **started** its execution |
|standalone | exec_mode | consume | no | One of: **consume**, **create** or **reuse**. If set to  **create**, Lithops will automatically create new VMs for each map() call based on the number of elements in `iterdata`. If set to **reuse** will try to reuse running workers if exist |
|standalone | pull_runtime | False | no | If set to True, Lithops will execute the command `docker pull <runtime_name>` in each VM before executing the a job (in case of using a docker runtime)|

## AWS 
The assumption that you already familiar with AWS, and you have AUTH credentials to your account (HMAC Credentials).

### Choose an operating system image for the VM
Any Virtual Machine (VM) need to define the instance’s operating system and version. Lithops support both standard operating system choices provided by the VPC or using pre-defined custom images that already contains all dependencies required by Lithops.

- Option 1: By default, Lithops uses an Ubuntu 20.04 image. In this case, no further action is required and you can continue to the next step. Lithops will install all required dependencies in the VM by itself. Notice this can consume about 3 min to complete all installations.

- Option 2: Alternatively, you can use a pre-built custom image that will greatly improve VM creation time for Lithops jobs. To benefit from this approach, navigate to [runtime/aws_ec2](https://github.com/lithops-cloud/lithops/tree/master/runtime/aws_ec2), and follow the instructions.

## Lithops and the VM consume mode

In this mode, Lithops can start and stop an existing VM, and deploy an entire job to that VM. The partition logic in this scenario is different from the create/reuse mode, since entire job executed in the same VM.

### Lithops configuration for the consume mode

Edit your lithops config and add the relevant keys:

```yaml
lithops:
   backend: aws_ec2

aws:
   access_key_id: <ACCESS_KEY_ID>
   secret_access_key: <SECRET_ACCESS_KEY>

aws_ec2:
   region_name : <REGION_NAME>
   instance_id : <INSTANCE ID OF THE VM>
```

### Summary of the configuration keys for the consume mode

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws_ec2 | region_name | |yes | Endpoint of your subnet region |
|aws_ec2 | instance_id | | yes | virtual server instance ID |
|aws_ec2 | public_ip | | no | Static Public IP address attached to your VM instance. By default public IPs are dynamic|
|aws_ec2 | ssh_username | ubuntu |no | Username to access the VM |
|aws_ec2 | ssh_key_filename | | no | Path to the ssh key file provided to create the VM. It will use the default path if not provided |
|aws_ec2 | worker_processes | 2 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of the VM. |



## Lithops and the VM auto create|reuse mode
In this mode, Lithops will automatically create new worker VM instances in runtime, scale Lithops job against generated VMs, and automatically delete the VMs when the job is completed.
Alternatively, you can set the `reuse` mode to keep running the started worker VMs, and reuse them for further executions. In the `reuse` mode, Lithops checks all the available worker VMs and start new workers if necessary.

### Lithops configuration for the auto create mode

Edit your lithops config and add the relevant keys:

```yaml
lithops:
    backend: aws_ec2

standalone:
    exec_mode: create|reuse

aws:
   access_key_id: <ACCESS_KEY_ID>
   secret_access_key: <SECRET_ACCESS_KEY>

aws_ec2:
    region_name: <REGION_NAME>
    vpc_id: <VPC_ID>
    iam_role: <IAM_ROLE>
    key_name: <SSH_KEY_NAME>
    security_group_id: <SECURITY_GROUP_ID>
```

###  Important information
1. The first time you use Lithops with specific runtime, Lithops will try generate and obtain runtime metadata. For this purpose Lithops will create a VM, extract specific metadata and delete VM. All further executions against same runtime will skip this step as runtime metadata will be cached both locally and in AWS S3.
2. In certain cases where ssh access details are wrong, Lithops might fail to ssh into created VM from the previous step. In this case, fix the ssh access credentials, navigate into the dashboard and manually delete the VMs.
3. The first time you deploy Lithops job in the create|reuse mode it is advised to navigate to the dashboard and verify that VM is being created and deleted.

### Summary of the configuration keys for the create mode

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws_ec2 | region_name | |yes | Region name, for example: `eu-west-1` |
|aws_ec2 | vpc_id | | yes | VPC id. You can find all the available VPCs in the [VPC Console page](https://console.aws.amazon.com/vpc/home) |
|aws_ec2 | iam_role | | yes | IAM EC2 role name. You can find it in the [IAM Console page](https://console.aws.amazon.com/iamv2/home#/roles). Create a new EC2 role if it does not exist|
|aws_ec2 | key_name | | yes | SSH Key name. You can find the available keys in the [EC2 console page](https://console.aws.amazon.com/ec2/v2/home#KeyPairs:). Create a new one or upload your own key if it does not exist|
|aws_ec2 | security_group_id | | yes | Security group ID. You can find the available security groups in the [EC2 console page](https://console.aws.amazon.com/ec2/v2/home#SecurityGroups:). The security group must have ports 22 and 8080 open |
|aws_ec2 | ssh_username | ubuntu |no | Username to access the VM |
|aws_ec2 | ssh_password |  |no | Password for accessing the worker VMs. If not provided, it is created randomly|
|aws_ec2 | ssh_key_filename | | no | Path to the ssh key file provided to access the VPC. It will use the default path if not provided |
|aws_ec2 | request_spot_instances | True | no | Request spot instance for worker VMs|
|aws_ec2 | target_ami | | no | Virtual machine image id. Default is Ubuntu Server 20.04 |
|aws_ec2 | master_instance_type | t2.micro | no | Profile name for the master VM |
|aws_ec2 | worker_instance_type | t2.medium | no | Profile name for the worker VMs |
|aws_ec2 | delete_on_dismantle | True | no | Delete the worker VMs when they are stopped. Master VM is never deleted when stopped |
|aws_ec2 | max_workers | 100 | no | Max number of workers per `FunctionExecutor()`|
|aws_ec2 | worker_processes | 2 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of a worker VM. |


## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```

The master and worker VMs contains the Lithops service logs in `/tmp/lithops/service.log`

You can login to the master VM and get a live ssh connection with:

```bash
lithops attach -b aws_ec2
```
