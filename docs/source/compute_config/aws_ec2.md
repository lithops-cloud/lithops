# AWS Elastic Compute Cloud (EC2)

The AWS EC2 client of Lithops can provide a truely serverless user experience on top of EC2 where Lithops creates new Virtual Machines (VMs) dynamically in runtime and scale Lithops jobs against them. Alternatively Lithops can start and stop an existing VM instances.

## AWS 
The assumption that you already familiar with AWS, and you have AUTH credentials to your account (HMAC Credentials).

### Choose an operating system image for the VM
Any Virtual Machine (VM) need to define the instance’s operating system and version. Lithops support both standard operating system choices provided by the VPC or using pre-defined custom images that already contains all dependencies required by Lithops.

- Option 1: By default, Lithops uses an Ubuntu 22.04 image. In this case, no further action is required and you can continue to the next step. Lithops will install all required dependencies in the VM by itself. Notice this can consume about 3 min to complete all installations.

- Option 2: Alternatively, you can use a pre-built custom image that will greatly improve VM creation time for Lithops jobs. To benefit from this approach, navigate to [runtime/aws_ec2](https://github.com/lithops-cloud/lithops/tree/master/runtime/aws_ec2), and follow the instructions.

## Installation

1. Install AWS backend dependencies:

```bash
python3 -m pip install lithops[aws]
```

## Lithops Consume mode

In this mode, Lithops can start and stop an existing VM, and deploy an entire job to that VM. The partition logic in this scenario is different from the `create/reuse` modes, since the entire job is executed in the same VM.

### AWS Credential setup

Lithops loads AWS credentials as specified in the [boto3 configuration guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html).

In summary, you can use one of the following settings:

1. Provide the credentials via the `~/.aws/config` file, or set the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables.

    You can run `aws configure` command if the AWS CLI is installed to setup the credentials. Then set in the Lithops config file:
    ```yaml
    lithops:
        backend: aws_ec2

    aws_ec2:
        region : <REGION_NAME>
        exec_mode: consume
        instance_id : <INSTANCE ID OF THE VM>
    ```

2. Provide the credentials in the `aws` section of the Lithops config file:
    ```yaml
    lithops:
        backend: aws_ec2

    aws:
        access_key_id: <AWS_ACCESS_KEY_ID>
        secret_access_key: <AWS_SECRET_ACCESS_KEY>
        region: <REGION_NAME>

    aws_ec2:
        exec_mode: consume
        instance_id : <INSTANCE ID OF THE VM>
    ```


### Summary of configuration keys for AWS

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws | region | |no | AWS Region. For example `us-east-1` |
|aws | access_key_id | |no | Account access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | secret_access_key | |no | Account secret access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | session_token | |no | Session token for temporary AWS credentials |
|aws | account_id | |no | *This field will be used if present to retrieve the account ID instead of using AWS STS. The account ID is used to format full image names for container runtimes. |

### Summary of configuration keys for the consume Mode

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws_ec2 | instance_id | | yes | virtual server instance ID |
|aws_ec2 | region | |yes | Region name of the VPC. For example `us-east-1`. Lithops will use the region set under the `aws` section if it is not set here |
|aws_ec2 | ssh_username | ubuntu |no | Username to access the VM |
|aws_ec2 | ssh_key_filename | ~/.ssh/id_rsa | no | Path to the ssh key file provided to create the VM. It will use the default path if not provided |
|aws_ec2 | worker_processes | AUTO | no | Number of Lithops processes within a given worker. This is used to parallelize function activations within the worker. By default it detects the amount of CPUs in the VM|
|aws_ec2 | runtime | python3 | no | Runtime name to run the functions. Can be a container image name. If not set Lithops will use the defeuv python3 interpreter of the VM |
|aws_ec2 | auto_dismantle | True |no | If False then the VM is not stopped automatically.|
|aws_ec2 | soft_dismantle_timeout | 300 |no| Time in seconds to stop the VM instance after a job **completed** its execution |
|aws_ec2 | hard_dismantle_timeout | 3600 | no | Time in seconds to stop the VM instance after a job **started** its execution |


## Lithops create and reuse modes
In the `create` mode, Lithops will automatically create new worker VM instances in runtime, scale Lithops job against generated VMs, and automatically delete the VMs when the job is completed.
Alternatively, you can set the `reuse` mode to keep running the started worker VMs, and reuse them for further executions. In the `reuse` mode, Lithops checks all the available worker VMs and start new workers only if necessary.

### AWS Credential setup

Lithops loads AWS credentials as specified in the [boto3 configuration guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html).

In summary, you can use one of the following settings:

1. Provide the credentials via the `~/.aws/config` file, or set the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables.

    You can run `aws configure` command if the AWS CLI is installed to setup the credentials. Then set in the Lithops config file:
    ```yaml
    lithops:
        backend: aws_ec2

    aws_ec2:
        region : <REGION_NAME>
        iam_role: <IAM_ROLE_NAME>
        exec_mode: reuse
    ```

2. Provide the credentials in the `aws` section of the Lithops config file:
    ```yaml
    lithops:
        backend: aws_ec2

    aws:
        access_key_id: <AWS_ACCESS_KEY_ID>
        secret_access_key: <AWS_SECRET_ACCESS_KEY>
        region: <REGION_NAME>

    aws_ec2:
        iam_role: <IAM_ROLE_NAME>
        exec_mode: reuse
    ```

### Summary of configuration keys for AWS

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws | region | |yes | AWS Region. For example `us-east-1` |
|aws | access_key_id | |no | Account access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | secret_access_key | |no | Account secret access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | session_token | |no | Session token for temporary AWS credentials |
|aws | account_id | |no | *This field will be used if present to retrieve the account ID instead of using AWS STS. The account ID is used to format full image names for container runtimes. |

### EC2 - Create and Reuse Modes

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws_ec2 | region | |no | Region name, for example: `eu-west-1`. Lithops will use the `region` set under the `aws` section if it is not set here |
|aws_ec2 | iam_role | | yes | IAM EC2 role name. You can find it in the [IAM Console page](https://console.aws.amazon.com/iamv2/home#/roles). Create a new EC2 role if it does not exist|
|aws_ec2 | vpc_id | | no | VPC id. You can find all the available VPCs in the [VPC Console page](https://console.aws.amazon.com/vpc/v2/home#vpcs:) |
|aws_ec2 | subnet_id | | no | Subnet id. You can find all the available Subnets in the [VPC Console page](https://console.aws.amazon.com/vpc/v2/home#subnets:) |
|aws_ec2 | security_group_id | | no | Security group ID. You can find the available security groups in the [VPC console page](https://console.aws.amazon.com/vpc/v2/home#SecurityGroups:). The security group must have ports 22 and 8080 open |
|aws_ec2 | ssh_key_name | | no | SSH Key name. You can find the available keys in the [EC2 console page](https://console.aws.amazon.com/ec2/v2/home#KeyPairs:). Create a new one or upload your own key if it does not exist|
|aws_ec2 | ssh_username | ubuntu |no | Username to access the VM |
|aws_ec2 | ssh_password |  |no | Password for accessing the worker VMs. If not provided, it is created randomly|
|aws_ec2 | ssh_key_filename | ~/.ssh/id_rsa | no | Path to the ssh key file provided to access the VPC. It will use the default path if not provided |
|aws_ec2 | request_spot_instances | True | no | Request spot instance for worker VMs|
|aws_ec2 | target_ami | | no | Virtual machine image id. Default is Ubuntu Server 22.04 |
|aws_ec2 | master_instance_type | t2.micro | no | Profile name for the master VM |
|aws_ec2 | worker_instance_type | t2.medium | no | Profile name for the worker VMs |
|aws_ec2 | delete_on_dismantle | True | no | Delete the worker VMs when they are stopped. Master VM is never deleted when stopped |
|aws_ec2 | max_workers | 100 | no | Max number of workers per `FunctionExecutor()`|
|aws_ec2 | worker_processes | 2 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of a worker VM. |
|aws_ec2 | runtime | python3 | no | Runtime name to run the functions. Can be a container image name. If not set Lithops will use the default python3 interpreter of the VM |
|aws_ec2 | auto_dismantle | True |no | If False then the VM is not stopped automatically.|
|aws_ec2 | soft_dismantle_timeout | 300 |no| Time in seconds to stop the VM instance after a job **completed** its execution |
|aws_ec2 | hard_dismantle_timeout | 3600 | no | Time in seconds to stop the VM instance after a job **started** its execution |
|aws_ec2 | exec_mode | reuse | no | One of: **consume**, **create** or **reuse**. If set to  **create**, Lithops will automatically create new VMs for each map() call based on the number of elements in iterdata. If set to **reuse** will try to reuse running workers if exist |


## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b aws_ec2 -s aws_s3
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```

## VM Management

Lithops for AWS EC2 follows a Mater-Worker architecrue (1:N).

All the VMs, including the master VM, are automatically stopped after a configurable timeout (see hard/soft dismantle timeouts).

You can login to the master VM and get a live ssh connection with:

```bash
lithops attach -b aws_ec2
```

The master and worker VMs contain the Lithops service logs in `/tmp/lithops-root/*-service.log`

To list all the available workers in the current moment, use the next command:

```bash
lithops worker list -b aws_ec2
```

You can also list all the submitted jobs with:

```bash
lithops job list -b aws_ec2
```

You can delete all the workers with:

```bash
lithops clean -b aws_ec2 -s aws_s3 
```

You can delete all the workers including the Master VM with the `--all` flag:

```bash
lithops clean -b aws_ec2 -s aws_s3 --all
```
