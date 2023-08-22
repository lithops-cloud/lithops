# AWS Batch

Lithops with *AWS Batch* as serverless batch compute backend.

## Installation

1. Install Amazon Web Services backend dependencies:

```
python3 -m pip install lithops[aws]
```

2. [Login](https://console.aws.amazon.com/?nc2=h_m_mc) to Amazon Web Services Console (or signup if you don't have an account)
 
3. Navigate to **IAM > Roles** to create the ECS Task Execution Role. AWS provides a defualt role named `ecsTaskExecutionRole`, which can be used instead. If you want to create another role or it is missing, create a new role attached to `Elastic Container Service Task`, and add the following policies:
    - `SecretsManagerReadWrite`
    - `AmazonEC2ContainerRegistryFullAccess`
    - `CloudWatchFullAccess`
    - `AmazonECSTaskExecutionRolePolicy`

4. Navigate to **IAM > Roles** to create the ECS Instance Role. AWS provides a defualt role named `ecsInstanceRole`, which can be used instead. If you want to create another role or it is missing, create a new role attached to `EC2`, and add the following policy:
    - `AmazonEC2ContainerServiceforEC2Role`

## Configuration

5. Edit your lithops config and add the following keys:

```yaml
aws:
    region: <REGION_NAME>
    access_key_id: <AWS_ACCESS_KEY_ID>
    secret_access_key: <AWS_SECRET_ACCESS_KEY>

aws_batch:
    runtime : <RUNTIME_NAME>
    runtime_timeout: <RUNTIME_TIMEOUT>
    runtime_memory: <RUNTIME_MEMORY>
    worker_processes: <WORKER_PROCESSES>
    container_vcpus: <CONTAINER_VCPUS>
    execution_role: <EXECUTION_ROLE_ARN>
    instance_role: <INSTANCE_ROLE_ARN>
    env_type: <COMPUTE_ENVIRONMENT_TYPE>
    env_max_cpus: <COMPUTE_ENVIRONMENT_MAX_CPUS>
    assign_public_ip: <ASSING_PUBLIC_IP_TO_CONTAINERS>
    subnets:
        - <SUBNET_ID_1>
        - <SUBNET_ID_2>
        - ...
    security_groups:
        - <SECURITY_GROUP_1>
        - <SECURITY_GROUP_2>
        - ...
```

## Summary of configuration keys for AWS

### AWS

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws | region | |yes | AWS region name. For example `us-east-1` |
|aws | access_key_id | |yes | Account access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | secret_access_key | |yes | Account secret access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | session_token | |no | Session token for temporary AWS credentials |
|aws | account_id | |no | *This field will be used if present to retrieve the account ID instead of using AWS STS. The account ID is used to format full image names for container runtimes. |

### AWS Batch

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
| aws_batch  | execution_role   |  | yes | ARN of the execution role used to execute AWS Batch tasks on ECS for Fargate environments |
| aws_batch  | instance_role    |  | yes | ARN of the execution role used to execute AWS Batch tasks on ECS for EC2 environments |
| aws_batch  | security_groups  |  | yes | List of Security groups to attach for ECS task containers. By default, you can use a security group that accepts all outbound traffic but blocks all inbound traffic. |
| aws_batch  | subnets          |  | yes | List of subnets from a VPC where to deploy the ECS task containers. Note that if you are using a **private subnet**, you can set `assing_public_ip` to `false` but make sure containers can reach other AWS services like ECR, Secrets service, etc., by, for example, using a NAT gateway. If you are using a **public subnet** you must set `assing_public_ip` to `true` |
| aws_batch  | region      |  | no | Region name (like `us-east-1`) where to deploy the ECS cluster. Lithops will use the region set under the `aws` section if it is not set here |
| aws_batch  | assign_public_ip | `true` | no | Assing public IPs to ECS task containers. Set to `true` if the tasks are being deployed in a public subnet. Set to `false` when deploying on a private subnet. |
| aws_batch  | runtime          | `default_runtime-v3X` | no | Runtime name |
| aws_batch  | runtime_timeout  | 180 | no | Runtime timeout |
| aws_batch  | runtime_memory   | 1024 | no | Runtime memory |
| aws_batch  | worker_processes | 1 | no | Worker processes |
| aws_batch  | container_vcpus  | 0.5 | no | Number of vCPUs assigned to each task container. It can be different from `worker_processes`. Use it to run a task that uses multiple processes within a container. |
| aws_batch  | service_role     | `None` | no | Service role for AWS Batch. Leave empty for use a service-linked execution role. More info [here](https://docs.aws.amazon.com/batch/latest/userguide/using-service-linked-roles.html) |
| aws_batch  | env_max_cpus     | 10 | no | Maximum total CPUs of the compute environment  |
| aws_batch  | env_type         | FARGATE_SPOT | no | Compute environment type, one of: `["EC2", "SPOT", "FARGATE", "FARGATE_SPOT"]` |


## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b aws_batch -s aws_s3
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```